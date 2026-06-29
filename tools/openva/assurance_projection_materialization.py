from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml

from tools.openva.assurance_projection import (
    ASSURANCE_PROJECTION_DATETIME_NAIVE,
    PROJECTION_PROFILE,
    AssuranceProjectionError,
    diff_assurance_projections,
    format_utc_datetime,
    json_material,
    normalize_aware_datetime,
    project_assurance,
    validate_change_event_output,
    validate_projection_for_diff,
)
from tools.openva.pack import canonical_json
from tools.openva.paths import relative_repo_path
from tools.openva.schema_registry import ROOT, build_openva_validator

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


def validate_latest_index(latest_index: Mapping[str, Any]) -> None:
    validator = build_openva_validator(LATEST_INDEX_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(latest_index), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_INDEX_INVALID,
            instance_path="/" + "/".join(str(part) for part in error.path) if error.path else "",
            message=f"Latest projection index is invalid: {error.message}",
        )
    entries = latest_index.get("entries", [])
    assurance_ids = [entry.get("assurance_id") for entry in entries if isinstance(entry, Mapping)]
    if len(assurance_ids) != len(set(assurance_ids)):
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_INDEX_INVALID,
            instance_path="/entries",
            message="Latest projection index contains duplicate assurance_id entries.",
        )
    if latest_index.get("count") != len(entries):
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_INDEX_INVALID,
            instance_path="/count",
            message="Latest projection index count must match entries length.",
        )


def validate_projection_artifact(projection: Mapping[str, Any], *, code: str) -> None:
    try:
        validate_projection_for_diff(projection, field_name="projection")
    except AssuranceProjectionError as exc:
        raise AssuranceProjectionMaterializationError(
            code=code,
            instance_path=exc.instance_path,
            message=str(exc),
            related_ids=exc.related_ids,
        ) from exc


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_LATEST_INVALID,
            instance_path="",
            message=f"{display_repo_path(path, ROOT)} must contain a JSON object.",
        )
    return data


def load_yaml_object(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_MATERIALIZATION_INPUT_INVALID,
            instance_path="",
            message=f"{display_repo_path(path, ROOT)} must contain a YAML object.",
        )
    return data


def load_latest_projection(
    repository_root: Path,
    assurance_id: str,
) -> dict[str, Any] | None:
    path = resolve_repo_path(repository_root, latest_projection_relative_path(assurance_id))
    if not path.exists():
        return None
    projection = load_json_object(path)
    validate_projection_artifact(projection, code=ASSURANCE_PROJECTION_LATEST_INVALID)
    return projection


def load_latest_index(repository_root: Path) -> dict[str, Any]:
    path = resolve_repo_path(repository_root, latest_index_relative_path())
    if not path.exists():
        return latest_index_document([])
    latest_index = load_json_object(path)
    validate_latest_index(latest_index)
    return latest_index


def validate_scheduled_reevaluation_guard(
    request: Mapping[str, Any],
    previous_projection: Mapping[str, Any] | None,
) -> None:
    if previous_projection is None:
        return
    due_raw = previous_projection.get("next_reevaluation_at")
    if not isinstance(due_raw, str):
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_REEVALUATION_NOT_DUE,
            instance_path="/next_reevaluation_at",
            message="Scheduled reevaluation requires a due latest projection boundary.",
        )
    effective_at = normalize_aware_datetime(str(request["effective_at"]), field_name="effective_at")
    due_at = normalize_aware_datetime(due_raw, field_name="next_reevaluation_at")
    if effective_at < due_at:
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_REEVALUATION_NOT_DUE,
            instance_path="/effective_at",
            message="Scheduled reevaluation effective_at is before the due boundary.",
        )


def plan_assurance_projection_materialization(
    request: Mapping[str, Any],
    repository: Mapping[str, Any],
    policy: Mapping[str, Any],
    projected_at: datetime | str,
    detected_at: datetime | str,
    previous_projection: Mapping[str, Any] | None,
    mode: ProjectionMaterializationMode,
) -> ProjectionMaterializationPlan:
    if mode not in {"current", "rebuild", "scheduled_reevaluation", "historical"}:
        raise AssuranceProjectionMaterializationError(
            code=ASSURANCE_PROJECTION_MATERIALIZATION_INPUT_INVALID,
            instance_path="/mode",
            message=f"Unknown projection materialization mode: {mode!r}.",
        )
    if mode == "scheduled_reevaluation":
        validate_scheduled_reevaluation_guard(request, previous_projection)

    projection = project_assurance(request, repository, policy, projected_at)
    if mode == "historical":
        return ProjectionMaterializationPlan(
            mode=mode,
            projection=projection,
            previous_projection=None,
            events=(),
            projection_changed=False,
            write_projection=False,
            write_events=False,
            update_latest_index=False,
        )

    if projections_persistently_equivalent(previous_projection, projection):
        return ProjectionMaterializationPlan(
            mode=mode,
            projection=projection,
            previous_projection=previous_projection,
            events=(),
            projection_changed=False,
            write_projection=False,
            write_events=False,
            update_latest_index=False,
        )

    events = tuple(diff_assurance_projections(previous_projection, projection, detected_at))
    return ProjectionMaterializationPlan(
        mode=mode,
        projection=projection,
        previous_projection=previous_projection,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=bool(events),
        update_latest_index=True,
    )


def validate_materialization_plan(plan: ProjectionMaterializationPlan) -> None:
    validate_projection_artifact(plan.projection, code=ASSURANCE_PROJECTION_MATERIALIZATION_INPUT_INVALID)
    if plan.previous_projection is not None:
        validate_projection_artifact(
            plan.previous_projection,
            code=ASSURANCE_PROJECTION_MATERIALIZATION_INPUT_INVALID,
        )
    for event in plan.events:
        try:
            validate_change_event_output(event)
        except AssuranceProjectionError as exc:
            raise AssuranceProjectionMaterializationError(
                code=ASSURANCE_PROJECTION_MATERIALIZATION_INPUT_INVALID,
                instance_path=exc.instance_path,
                message=str(exc),
                related_ids=exc.related_ids,
            ) from exc


def canonical_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return canonical_json(json_material(left)) == canonical_json(json_material(right))


def json_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(json_material(document), indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def yaml_bytes(document: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(json_material(document), sort_keys=False, allow_unicode=True).encode("utf-8")


def atomic_write_bytes(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        temp_path.write_bytes(content)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return True


def validate_destination_path(repository_root: Path, relative_path: str) -> Path:
    return resolve_repo_path(repository_root, relative_path)


def validate_event_collisions(
    repository_root: Path,
    events: tuple[Mapping[str, Any], ...],
) -> tuple[tuple[str, Path], ...]:
    destinations: list[tuple[str, Path]] = []
    for event in events:
        event_id = str(event["change_event_id"])
        path = validate_destination_path(
            repository_root,
            change_event_relative_path(str(event["vendor_id"]), event_id),
        )
        if path.exists():
            existing = load_yaml_object(path)
            if not canonical_equal(existing, event):
                raise AssuranceProjectionMaterializationError(
                    code=ASSURANCE_CHANGE_EVENT_ID_COLLISION,
                    instance_path="/change_event_id",
                    message=f"Existing change event {event_id!r} has different content.",
                    related_ids=(event_id,),
                )
        destinations.append((event_id, path))
    return tuple(destinations)


def apply_assurance_projection_materialization(
    plan: ProjectionMaterializationPlan,
    repository_root: Path,
) -> ProjectionMaterializationResult:
    validate_materialization_plan(plan)
    assurance_id = str(plan.projection["assurance_id"])
    if plan.mode == "historical" or (not plan.write_projection and not plan.write_events and not plan.update_latest_index):
        return ProjectionMaterializationResult(
            mode=plan.mode,
            assurance_id=assurance_id,
            projection=plan.projection,
            events=plan.events,
            projection_written=False,
            event_ids_written=(),
            event_ids_already_present=(),
            latest_index_updated=False,
            semantic_no_op=not plan.write_projection and not plan.events,
            writes_applied=False,
        )

    projection_path = validate_destination_path(
        repository_root,
        latest_projection_relative_path(assurance_id),
    )
    latest_index_path = validate_destination_path(repository_root, latest_index_relative_path())
    event_destinations = validate_event_collisions(repository_root, plan.events)
    existing_index = load_latest_index(repository_root)
    updated_index = upsert_latest_index_entry(existing_index, plan.projection)
    validate_latest_index(updated_index)

    event_ids_written: list[str] = []
    event_ids_already_present: list[str] = []
    projection_written = False
    latest_index_updated = False

    if plan.mode != "historical" and plan.write_events:
        for event_id, path in event_destinations:
            if path.exists():
                event_ids_already_present.append(event_id)
                continue
            atomic_write_bytes(path, yaml_bytes(next(event for event in plan.events if event["change_event_id"] == event_id)))
            event_ids_written.append(event_id)

    if plan.mode != "historical" and plan.write_projection:
        projection_written = atomic_write_bytes(projection_path, json_bytes(plan.projection))

    if plan.mode != "historical" and plan.update_latest_index:
        latest_index_updated = atomic_write_bytes(latest_index_path, json_bytes(updated_index))

    return ProjectionMaterializationResult(
        mode=plan.mode,
        assurance_id=assurance_id,
        projection=plan.projection,
        events=plan.events,
        projection_written=projection_written,
        event_ids_written=tuple(event_ids_written),
        event_ids_already_present=tuple(event_ids_already_present),
        latest_index_updated=latest_index_updated,
        semantic_no_op=not plan.write_projection and not plan.events,
        writes_applied=bool(projection_written or event_ids_written or latest_index_updated),
    )


def materialize_assurance_projection(
    request: Mapping[str, Any],
    repository: Mapping[str, Any],
    policy: Mapping[str, Any],
    projected_at: datetime | str,
    detected_at: datetime | str,
    repository_root: Path,
    mode: ProjectionMaterializationMode,
) -> ProjectionMaterializationResult:
    assurance_id = str(request["assurance_id"])
    previous_projection = None if mode == "historical" else load_latest_projection(repository_root, assurance_id)
    plan = plan_assurance_projection_materialization(
        request,
        repository,
        policy,
        projected_at,
        detected_at,
        previous_projection,
        mode,
    )
    if mode == "historical":
        return ProjectionMaterializationResult(
            mode=plan.mode,
            assurance_id=assurance_id,
            projection=plan.projection,
            events=(),
            projection_written=False,
            event_ids_written=(),
            event_ids_already_present=(),
            latest_index_updated=False,
            semantic_no_op=True,
            writes_applied=False,
        )
    return apply_assurance_projection_materialization(plan, repository_root)
