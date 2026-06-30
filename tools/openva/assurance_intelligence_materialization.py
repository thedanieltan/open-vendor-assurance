from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from tools.openva.assurance_intelligence import (
    INTELLIGENCE_PROFILE,
    AssuranceIntelligenceError,
    diff_assurance_intelligence_projections,
    project_assurance_intelligence,
    validate_intelligence_output,
)
from tools.openva.assurance_projection import AssuranceProjectionError
from tools.openva.assurance_projection import format_utc_datetime
from tools.openva.assurance_projection import json_material
from tools.openva.assurance_projection import normalize_aware_datetime
from tools.openva.assurance_projection_materialization import (
    AssuranceProjectionMaterializationError,
    atomic_write_bytes,
    json_bytes,
    load_json_object,
    require_slug,
    resolve_repo_path,
    validate_destination_path,
    validate_event_collisions,
    yaml_bytes,
)
from tools.openva.schema_registry import ROOT, build_openva_validator

IntelligenceMaterializationMode = Literal[
    "current",
    "rebuild",
    "scheduled_reevaluation",
    "historical",
]

ASSURANCE_INTELLIGENCE_MATERIALIZATION_INPUT_INVALID = "ASSURANCE_INTELLIGENCE_MATERIALIZATION_INPUT_INVALID"
ASSURANCE_INTELLIGENCE_LATEST_INVALID = "ASSURANCE_INTELLIGENCE_LATEST_INVALID"
ASSURANCE_INTELLIGENCE_INDEX_INVALID = "ASSURANCE_INTELLIGENCE_INDEX_INVALID"
ASSURANCE_INTELLIGENCE_REEVALUATION_NOT_DUE = "ASSURANCE_INTELLIGENCE_REEVALUATION_NOT_DUE"

INTELLIGENCE_LATEST_INDEX_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-latest-index.schema.json"
INTELLIGENCE_LATEST_INDEX_REL = "maintenance/assurance-intelligence/latest-index.json"
INTELLIGENCE_LATEST_ROOT_REL = "maintenance/assurance-intelligence/latest"


class AssuranceIntelligenceMaterializationError(AssuranceProjectionMaterializationError):
    pass


@dataclass(frozen=True, slots=True)
class IntelligenceMaterializationPlan:
    mode: IntelligenceMaterializationMode
    projection: Mapping[str, Any]
    previous_projection: Mapping[str, Any] | None
    events: tuple[Mapping[str, Any], ...]
    projection_changed: bool
    write_projection: bool
    write_events: bool
    update_latest_index: bool


@dataclass(frozen=True, slots=True)
class IntelligenceMaterializationResult:
    mode: IntelligenceMaterializationMode
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
class AssuranceIntelligenceReevaluationCandidate:
    assurance_id: str
    due_at: str
    projection_ref: str
    input_digest: str
    policies: Mapping[str, Mapping[str, str]]


def latest_intelligence_projection_relative_path(assurance_id: str) -> str:
    slug = require_slug(assurance_id, field_name="assurance_id")
    return f"{INTELLIGENCE_LATEST_ROOT_REL}/{slug[:2]}/{slug}.json"


def latest_intelligence_index_relative_path() -> str:
    return INTELLIGENCE_LATEST_INDEX_REL


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
        "policies": json_material(projection["policies"]),
        "input_digest": str(projection["input_digest"]),
        "effective_at": str(projection["effective_at"]),
        "knowledge_cutoff": str(projection["knowledge_cutoff"]),
        "next_reevaluation_at": projection.get("next_reevaluation_at"),
    }


def latest_index_document(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted((json_material(entry) for entry in entries), key=lambda entry: str(entry["assurance_id"]))
    return {
        "schema_version": "0.1.0",
        "report_type": "assurance_intelligence_latest_index",
        "projection_profile": INTELLIGENCE_PROFILE,
        "count": len(ordered),
        "entries": ordered,
    }


def upsert_latest_index_entry(
    latest_index: Mapping[str, Any] | None,
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    assurance_id = str(projection["assurance_id"])
    replacement = latest_index_entry(
        projection,
        latest_intelligence_projection_relative_path(assurance_id),
    )
    entries = [
        json_material(entry)
        for entry in list((latest_index or {}).get("entries", []))
        if isinstance(entry, Mapping) and entry.get("assurance_id") != assurance_id
    ]
    entries.append(replacement)
    return latest_index_document(entries)


def validate_latest_index(latest_index: Mapping[str, Any]) -> None:
    validator = build_openva_validator(INTELLIGENCE_LATEST_INDEX_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(latest_index), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        raise AssuranceIntelligenceMaterializationError(
            code=ASSURANCE_INTELLIGENCE_INDEX_INVALID,
            instance_path="/" + "/".join(str(part) for part in error.path) if error.path else "",
            message=f"Latest intelligence index is invalid: {error.message}",
        )
    entries = latest_index.get("entries", [])
    assurance_ids = [entry.get("assurance_id") for entry in entries if isinstance(entry, Mapping)]
    if len(assurance_ids) != len(set(assurance_ids)):
        raise AssuranceIntelligenceMaterializationError(
            code=ASSURANCE_INTELLIGENCE_INDEX_INVALID,
            instance_path="/entries",
            message="Latest intelligence index contains duplicate assurance_id entries.",
        )
    if latest_index.get("count") != len(entries):
        raise AssuranceIntelligenceMaterializationError(
            code=ASSURANCE_INTELLIGENCE_INDEX_INVALID,
            instance_path="/count",
            message="Latest intelligence index count must match entries length.",
        )


def validate_projection_artifact(projection: Mapping[str, Any], *, code: str) -> None:
    try:
        validate_intelligence_output(projection)
    except AssuranceIntelligenceError as exc:
        raise AssuranceIntelligenceMaterializationError(
            code=code,
            instance_path=exc.instance_path,
            message=str(exc),
            related_ids=exc.related_ids,
        ) from exc


def load_latest_intelligence_projection(
    repository_root: Path,
    assurance_id: str,
) -> dict[str, Any] | None:
    path = resolve_repo_path(repository_root, latest_intelligence_projection_relative_path(assurance_id))
    if not path.exists():
        return None
    projection = load_json_object(path)
    validate_projection_artifact(projection, code=ASSURANCE_INTELLIGENCE_LATEST_INVALID)
    return projection


def load_latest_intelligence_index(repository_root: Path) -> dict[str, Any]:
    path = resolve_repo_path(repository_root, latest_intelligence_index_relative_path())
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
        raise AssuranceIntelligenceMaterializationError(
            code=ASSURANCE_INTELLIGENCE_REEVALUATION_NOT_DUE,
            instance_path="/next_reevaluation_at",
            message="Scheduled intelligence reevaluation requires a due latest projection boundary.",
        )
    effective_at = normalize_aware_datetime(str(request["effective_at"]), field_name="effective_at")
    due_at = normalize_aware_datetime(due_raw, field_name="next_reevaluation_at")
    if effective_at < due_at:
        raise AssuranceIntelligenceMaterializationError(
            code=ASSURANCE_INTELLIGENCE_REEVALUATION_NOT_DUE,
            instance_path="/effective_at",
            message="Scheduled intelligence reevaluation effective_at is before the due boundary.",
        )


def plan_due_assurance_intelligence_reevaluations(
    latest_index: Mapping[str, Any],
    as_of: datetime | str,
) -> tuple[AssuranceIntelligenceReevaluationCandidate, ...]:
    as_of_utc = normalize_aware_datetime(as_of, field_name="as_of")
    candidates: list[AssuranceIntelligenceReevaluationCandidate] = []
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
            AssuranceIntelligenceReevaluationCandidate(
                assurance_id=str(entry["assurance_id"]),
                due_at=format_utc_datetime(due_at) or due_raw,
                projection_ref=str(entry["projection_ref"]),
                input_digest=str(entry["input_digest"]),
                policies=json_material(entry["policies"]),
            )
        )
    return tuple(sorted(candidates, key=lambda candidate: (candidate.due_at, candidate.assurance_id)))


def plan_assurance_intelligence_materialization(
    request: Mapping[str, Any],
    repository: Mapping[str, Any],
    lifecycle_policy: Mapping[str, Any],
    verification_policy: Mapping[str, Any],
    freshness_policy: Mapping[str, Any],
    evidence_set_policy: Mapping[str, Any],
    projected_at: datetime | str,
    detected_at: datetime | str,
    previous_projection: Mapping[str, Any] | None,
    mode: IntelligenceMaterializationMode,
) -> IntelligenceMaterializationPlan:
    if mode not in {"current", "rebuild", "scheduled_reevaluation", "historical"}:
        raise AssuranceIntelligenceMaterializationError(
            code=ASSURANCE_INTELLIGENCE_MATERIALIZATION_INPUT_INVALID,
            instance_path="/mode",
            message=f"Unknown intelligence materialization mode: {mode!r}.",
        )
    if mode == "scheduled_reevaluation":
        validate_scheduled_reevaluation_guard(request, previous_projection)

    projection = project_assurance_intelligence(
        request,
        repository,
        lifecycle_policy,
        verification_policy,
        freshness_policy,
        evidence_set_policy,
        projected_at,
    )
    if mode == "historical":
        return IntelligenceMaterializationPlan(
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
        return IntelligenceMaterializationPlan(
            mode=mode,
            projection=projection,
            previous_projection=previous_projection,
            events=(),
            projection_changed=False,
            write_projection=False,
            write_events=False,
            update_latest_index=False,
        )

    events = tuple(diff_assurance_intelligence_projections(previous_projection, projection, detected_at))
    return IntelligenceMaterializationPlan(
        mode=mode,
        projection=projection,
        previous_projection=previous_projection,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=bool(events),
        update_latest_index=True,
    )


def validate_materialization_plan(plan: IntelligenceMaterializationPlan) -> None:
    validate_projection_artifact(
        plan.projection,
        code=ASSURANCE_INTELLIGENCE_MATERIALIZATION_INPUT_INVALID,
    )
    if plan.previous_projection is not None:
        validate_projection_artifact(
            plan.previous_projection,
            code=ASSURANCE_INTELLIGENCE_MATERIALIZATION_INPUT_INVALID,
        )
    for event in plan.events:
        # Event construction validates schema during diffing; keep this bounded
        # validation here for externally constructed plans.
        from tools.openva.assurance_projection import validate_change_event_output

        try:
            validate_change_event_output(event)
        except AssuranceProjectionError as exc:
            raise AssuranceIntelligenceMaterializationError(
                code=ASSURANCE_INTELLIGENCE_MATERIALIZATION_INPUT_INVALID,
                instance_path=exc.instance_path,
                message=str(exc),
                related_ids=exc.related_ids,
            ) from exc


def apply_assurance_intelligence_materialization(
    plan: IntelligenceMaterializationPlan,
    repository_root: Path,
) -> IntelligenceMaterializationResult:
    validate_materialization_plan(plan)
    assurance_id = str(plan.projection["assurance_id"])
    if plan.mode == "historical" or (not plan.write_projection and not plan.write_events and not plan.update_latest_index):
        return IntelligenceMaterializationResult(
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
        latest_intelligence_projection_relative_path(assurance_id),
    )
    latest_index_path = validate_destination_path(repository_root, latest_intelligence_index_relative_path())
    event_destinations = validate_event_collisions(repository_root, plan.events)
    existing_index = load_latest_intelligence_index(repository_root)
    updated_index = upsert_latest_index_entry(existing_index, plan.projection)
    validate_latest_index(updated_index)

    event_ids_written: list[str] = []
    event_ids_already_present: list[str] = []
    projection_written = False
    latest_index_updated = False

    if plan.write_events:
        for event_id, path in event_destinations:
            if path.exists():
                event_ids_already_present.append(event_id)
                continue
            event = next(event for event in plan.events if event["change_event_id"] == event_id)
            atomic_write_bytes(path, yaml_bytes(event))
            event_ids_written.append(event_id)

    if plan.write_projection:
        projection_written = atomic_write_bytes(projection_path, json_bytes(plan.projection))

    if plan.update_latest_index:
        latest_index_updated = atomic_write_bytes(latest_index_path, json_bytes(updated_index))

    return IntelligenceMaterializationResult(
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


def materialize_assurance_intelligence(
    request: Mapping[str, Any],
    repository: Mapping[str, Any],
    lifecycle_policy: Mapping[str, Any],
    verification_policy: Mapping[str, Any],
    freshness_policy: Mapping[str, Any],
    evidence_set_policy: Mapping[str, Any],
    projected_at: datetime | str,
    detected_at: datetime | str,
    repository_root: Path,
    mode: IntelligenceMaterializationMode,
) -> IntelligenceMaterializationResult:
    assurance_id = str(request["assurance_id"])
    previous_projection = None if mode == "historical" else load_latest_intelligence_projection(repository_root, assurance_id)
    plan = plan_assurance_intelligence_materialization(
        request,
        repository,
        lifecycle_policy,
        verification_policy,
        freshness_policy,
        evidence_set_policy,
        projected_at,
        detected_at,
        previous_projection,
        mode,
    )
    if mode == "historical":
        return IntelligenceMaterializationResult(
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
    return apply_assurance_intelligence_materialization(plan, repository_root)
