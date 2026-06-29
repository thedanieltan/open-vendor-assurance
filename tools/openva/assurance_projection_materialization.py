from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from tools.openva.assurance_projection import (
    ASSURANCE_PROJECTION_DATETIME_NAIVE,
    PROJECTION_PROFILE,
    AssuranceProjectionError,
    format_utc_datetime,
    json_material,
    normalize_aware_datetime,
)
from tools.openva.paths import relative_repo_path
from tools.openva.schema_registry import ROOT

ProjectionMaterializationMode = Literal[
    "current",
    "rebuild",
    "scheduled_reevaluation",
    "historical",
]

ASSURANCE_PROJECTION_LATEST_INVALID = "ASSURANCE_PROJECTION_LATEST_INVALID"
ASSURANCE_PROJECTION_INDEX_INVALID = "ASSURANCE_PROJECTION_INDEX_INVALID"
ASSURANCE_PROJECTION_MATERIALIZATION_INPUT_INVALID = "ASSURANCE_PROJECTION_MATERIALIZATION_INPUT_INVALID"
ASSURANCE_PROJECTION_STORAGE_PATH_INVALID = "ASSURANCE_PROJECTION_STORAGE_PATH_INVALID"
ASSURANCE_CHANGE_EVENT_ID_COLLISION = "ASSURANCE_CHANGE_EVENT_ID_COLLISION"
ASSURANCE_PROJECTION_REEVALUATION_NOT_DUE = "ASSURANCE_PROJECTION_REEVALUATION_NOT_DUE"

LATEST_INDEX_SCHEMA_PATH = ROOT / "schemas/openva/assurance-projection-latest-index.schema.json"
LATEST_PROJECTION_INDEX_REL = "maintenance/assurance-projections/latest-index.json"
LATEST_PROJECTION_ROOT_REL = "maintenance/assurance-projections/latest"
CHANGE_EVENT_ROOT_REL = "data/vendors"
OPENVA_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


class AssuranceProjectionMaterializationError(AssuranceProjectionError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectionMaterializationPlan:
    mode: ProjectionMaterializationMode
    projection: Mapping[str, Any]
    previous_projection: Mapping[str, Any] | None
    events: tuple[Mapping[str, Any], ...]
    projection_changed: bool
    write_projection: bool
    write_events: bool
    update_latest_index: bool


@dataclass(frozen=True, slots=True)
class ProjectionMaterializationResult:
    mode: ProjectionMaterializationMode
    assurance_id: str
    projection: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    projection_written: bool
    event_ids_written: tuple[str, ...]
    event_ids_already_present: tuple[str, ...]
    latest_index_updated: bool
    semantic_no_op: bool
    writes_applied: bool


@dataclass(frozen=True, slots=True)
class AssuranceReevaluationCandidate:
    assurance_id: str
    due_at: str
    projection_ref: str
    input_digest: str
    policy: Mapping[str, str]


def require_slug(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not OPENVA_SLUG_RE.fullmatch(value):
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_STORAGE_PATH_INVALID,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be an OpenVA slug.",
        )
    return value


def safe_repo_relative_path(relative_path: str) -> PurePosixPath:
    path = PurePosixPath(str(relative_path).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_STORAGE_PATH_INVALID,
            instance_path="/path",
            message="Repository artifact paths must be relative and must not contain traversal.",
        )
    return path


def resolve_repo_path(repository_root: Path, relative_path: str) -> Path:
    rel = safe_repo_relative_path(relative_path)
    root = repository_root.resolve()
    resolved = (root / Path(*rel.parts)).resolve()
    if root != resolved and root not in resolved.parents:
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_STORAGE_PATH_INVALID,
            instance_path="/path",
            message="Repository artifact path escapes the repository root.",
        )
    return resolved


def latest_projection_relative_path(assurance_id: str) -> str:
    slug = require_slug(assurance_id, field_name="assurance_id")
    shard = slug[:2]
    return f"{LATEST_PROJECTION_ROOT_REL}/{shard}/{slug}.json"


def change_event_relative_path(vendor_id: str, change_event_id: str) -> str:
    vendor_slug = require_slug(vendor_id, field_name="vendor_id")
    event_slug = require_slug(change_event_id, field_name="change_event_id")
    return f"{CHANGE_EVENT_ROOT_REL}/{vendor_slug}/assurance_changes/{event_slug}.yaml"


def latest_index_relative_path() -> str:
    return LATEST_PROJECTION_INDEX_REL


def projection_without_projected_at(projection: Mapping[str, Any]) -> dict[str, Any]:
    material = json_material(projection)
    if isinstance(material, dict):
        material.pop("projected_at", None)
    return material


def projections_persistently_equivalent(
    previous_projection: Mapping[str, Any] | None,
    projection: Mapping[str, Any],
) -> bool:
    return previous_projection is not None and projection_without_projected_at(previous_projection) == projection_without_projected_at(projection)


def latest_index_entry(projection: Mapping[str, Any], projection_ref: str) -> dict[str, Any]:
    return {
        "assurance_id": str(projection["assurance_id"]),
        "vendor_id": str(projection["vendor_id"]),
        "projection_profile": str(projection["projection_profile"]),
        "projection_ref": projection_ref,
        "policy": json_material(projection["policy"]),
        "input_digest": str(projection["input_digest"]),
        "effective_at": str(projection["effective_at"]),
        "knowledge_cutoff": str(projection["knowledge_cutoff"]),
        "next_reevaluation_at": projection.get("next_reevaluation_at"),
    }


def latest_index_document(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted((json_material(entry) for entry in entries), key=lambda entry: str(entry["assurance_id"]))
    return {
        "schema_version": "0.1.0",
        "report_type": "assurance_projection_latest_index",
        "projection_profile": PROJECTION_PROFILE,
        "count": len(ordered),
        "entries": ordered,
    }


def upsert_latest_index_entry(
    latest_index: Mapping[str, Any] | None,
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    existing_entries = list((latest_index or {}).get("entries", []))
    assurance_id = str(projection["assurance_id"])
    replacement = latest_index_entry(projection, latest_projection_relative_path(assurance_id))
    entries = [
        json_material(entry)
        for entry in existing_entries
        if isinstance(entry, Mapping) and entry.get("assurance_id") != assurance_id
    ]
    entries.append(replacement)
    return latest_index_document(entries)


def plan_due_assurance_reevaluations(
    latest_index: Mapping[str, Any],
    as_of: datetime | str,
) -> tuple[AssuranceReevaluationCandidate, ...]:
    as_of_utc = normalize_aware_datetime(as_of, field_name="as_of")
    candidates: list[AssuranceReevaluationCandidate] = []
    for entry in latest_index.get("entries", []):
        if not isinstance(entry, Mapping):
            continue
        due_raw = entry.get("next_reevaluation_at")
        if not isinstance(due_raw, str):
            continue
        due_at = normalize_aware_datetime(due_raw, field_name="next_reevaluation_at")
        if due_at > as_of_utc:
            continue
        candidates.append(
            AssuranceReevaluationCandidate(
                assurance_id=str(entry["assurance_id"]),
                due_at=format_utc_datetime(due_at) or due_raw,
                projection_ref=str(entry["projection_ref"]),
                input_digest=str(entry["input_digest"]),
                policy=json_material(entry["policy"]),
            )
        )
    return tuple(sorted(candidates, key=lambda candidate: (candidate.due_at, candidate.assurance_id)))


def validate_as_of_is_aware(as_of: datetime | str) -> None:
    try:
        normalize_aware_datetime(as_of, field_name="as_of")
    except AssuranceProjectionError as exc:
        if exc.code == ASSURANCE_PROJECTION_DATETIME_NAIVE:
            raise
        raise


def display_repo_path(path: Path, repository_root: Path) -> str:
    return relative_repo_path(path, repository_root)
