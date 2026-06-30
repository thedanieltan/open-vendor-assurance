from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from tools.openva.assurance_projection import AssuranceProjectionError
from tools.openva.assurance_projection import ASSURANCE_CHANGE_EVENT_REASON_AMBIGUOUS
from tools.openva.assurance_projection import ASSURANCE_CHANGE_EVENT_TIME_INVALID
from tools.openva.assurance_projection import admitted_repository_records_for_manifest
from tools.openva.assurance_projection import axis_state_value
from tools.openva.assurance_projection import change_event_id_for_manifest
from tools.openva.assurance_projection import event_caused_by
from tools.openva.assurance_projection import format_utc_datetime
from tools.openva.assurance_projection import json_material
from tools.openva.assurance_projection import normalize_aware_datetime
from tools.openva.assurance_projection import projection_axis
from tools.openva.assurance_projection import project_assurance
from tools.openva.assurance_projection import projection_policy_identity
from tools.openva.assurance_projection import require_string
from tools.openva.assurance_projection import resolve_target_assurance
from tools.openva.assurance_projection import singular_axis_reason
from tools.openva.assurance_projection import validate_change_event_output
from tools.openva.assurance_projection import validation_instance_path
from tools.openva.assurance_verification import evidence_set_policy_identity
from tools.openva.assurance_verification import project_evidence_set_state
from tools.openva.assurance_verification import project_verification_freshness
from tools.openva.assurance_verification import project_verification_state
from tools.openva.assurance_verification import verification_freshness_policy_identity
from tools.openva.assurance_verification import verification_policy_identity
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator

ASSURANCE_INTELLIGENCE_REQUEST_INVALID = "ASSURANCE_INTELLIGENCE_REQUEST_INVALID"
ASSURANCE_INTELLIGENCE_POLICY_MISMATCH = "ASSURANCE_INTELLIGENCE_POLICY_MISMATCH"
ASSURANCE_INTELLIGENCE_TARGET_UNKNOWN = "ASSURANCE_INTELLIGENCE_TARGET_UNKNOWN"
ASSURANCE_INTELLIGENCE_OUTPUT_INVALID = "ASSURANCE_INTELLIGENCE_OUTPUT_INVALID"
ASSURANCE_INTELLIGENCE_DIFF_INPUT_INVALID = "ASSURANCE_INTELLIGENCE_DIFF_INPUT_INVALID"
ASSURANCE_INTELLIGENCE_DIFF_INCOMPATIBLE = "ASSURANCE_INTELLIGENCE_DIFF_INCOMPATIBLE"
ASSURANCE_INTELLIGENCE_DIFF_NON_MONOTONIC = "ASSURANCE_INTELLIGENCE_DIFF_NON_MONOTONIC"

INTELLIGENCE_PROFILE = "openva.assurance-intelligence.v1"
INTELLIGENCE_AXES = (
    "instrument_state",
    "supersession_state",
    "verification_state",
    "verification_freshness",
    "evidence_set_state",
)
INTELLIGENCE_REQUEST_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-request.schema.json"
INTELLIGENCE_PROJECTION_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-projection.schema.json"
CHANGE_TYPE_BY_INTELLIGENCE_AXIS = {
    "instrument_state": "instrument_state_changed",
    "supersession_state": "assurance_superseded",
    "verification_state": "verification_state_changed",
    "verification_freshness": "verification_freshness_changed",
    "evidence_set_state": "evidence_set_changed",
}
POLICY_BY_INTELLIGENCE_AXIS = {
    "instrument_state": "lifecycle",
    "supersession_state": "lifecycle",
    "verification_state": "verification",
    "verification_freshness": "verification_freshness",
    "evidence_set_state": "evidence_set",
}
DIFF_COMPATIBILITY_FIELDS = (
    "schema_version",
    "projection_profile",
    "implemented_axes",
    "assurance_id",
    "vendor_id",
    "advisory_boundary",
)


class AssuranceIntelligenceError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        instance_path: str = "",
        related_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.instance_path = instance_path
        self.related_ids = related_ids


def validate_intelligence_request(request: Mapping[str, Any]) -> None:
    validator = build_openva_validator(INTELLIGENCE_REQUEST_SCHEMA_PATH)
    errors = [
        error
        for error in validator.iter_errors(request)
        if not (
            error.validator == "format"
            and list(error.path) in (["effective_at"], ["knowledge_cutoff"])
        )
    ]
    errors = sorted(errors, key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceIntelligenceError(
        code=ASSURANCE_INTELLIGENCE_REQUEST_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Assurance intelligence request is invalid: {error.message}",
    )


def validate_intelligence_output(projection: Mapping[str, Any]) -> None:
    validator = build_openva_validator(INTELLIGENCE_PROJECTION_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(json_material(projection)), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceIntelligenceError(
        code=ASSURANCE_INTELLIGENCE_OUTPUT_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Assurance intelligence projection is invalid: {error.message}",
    )


def validate_intelligence_projection_for_diff(
    projection: Mapping[str, Any],
    *,
    field_name: str,
) -> None:
    validator = build_openva_validator(INTELLIGENCE_PROJECTION_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(json_material(projection)), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceIntelligenceError(
        code=ASSURANCE_INTELLIGENCE_DIFF_INPUT_INVALID,
        instance_path=f"/{field_name}{validation_instance_path(error)}",
        message=f"{field_name} intelligence projection is invalid: {error.message}",
    )


def validate_intelligence_diff_compatibility(
    previous_projection: Mapping[str, Any],
    new_projection: Mapping[str, Any],
) -> None:
    for field_name in DIFF_COMPATIBILITY_FIELDS:
        if previous_projection.get(field_name) == new_projection.get(field_name):
            continue
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_DIFF_INCOMPATIBLE,
            instance_path=f"/{field_name}",
            message=f"Intelligence projection field {field_name!r} is incompatible.",
            related_ids=(str(previous_projection.get(field_name)), str(new_projection.get(field_name))),
        )


def validate_intelligence_forward_order(
    previous_projection: Mapping[str, Any],
    new_projection: Mapping[str, Any],
) -> None:
    for field_name in ("effective_at", "knowledge_cutoff"):
        previous_value = normalize_aware_datetime(
            require_string(previous_projection, field_name),
            field_name=field_name,
        )
        new_value = normalize_aware_datetime(
            require_string(new_projection, field_name),
            field_name=field_name,
        )
        if new_value >= previous_value:
            continue
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_DIFF_NON_MONOTONIC,
            instance_path=f"/{field_name}",
            message=f"New intelligence projection {field_name} must be greater than or equal to the previous value.",
        )


def validate_intelligence_diff_inputs(
    previous_projection: Mapping[str, Any] | None,
    new_projection: Mapping[str, Any],
    detected_at: datetime | str,
) -> datetime:
    validate_intelligence_projection_for_diff(new_projection, field_name="new_projection")
    if previous_projection is not None:
        validate_intelligence_projection_for_diff(previous_projection, field_name="previous_projection")
        validate_intelligence_diff_compatibility(previous_projection, new_projection)
        validate_intelligence_forward_order(previous_projection, new_projection)

    detected_at_utc = normalize_aware_datetime(detected_at, field_name="detected_at")
    knowledge_cutoff = normalize_aware_datetime(
        require_string(new_projection, "knowledge_cutoff"),
        field_name="knowledge_cutoff",
    )
    if detected_at_utc < knowledge_cutoff:
        raise AssuranceProjectionError(
            code=ASSURANCE_CHANGE_EVENT_TIME_INVALID,
            instance_path="/detected_at",
            message="detected_at must be greater than or equal to the new projection knowledge_cutoff.",
        )
    return detected_at_utc


def verify_policy_identity(
    *,
    request: Mapping[str, Any],
    policy_name: str,
    identity: Mapping[str, str],
) -> None:
    policies = request.get("policies")
    if not isinstance(policies, Mapping):
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_REQUEST_INVALID,
            instance_path="/policies",
            message="Assurance intelligence request policies must be an object.",
        )
    request_identity = policies.get(policy_name)
    if not isinstance(request_identity, Mapping):
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_REQUEST_INVALID,
            instance_path=f"/policies/{policy_name}",
            message=f"Assurance intelligence request must define {policy_name!r} policy identity.",
        )
    for key, expected_value in identity.items():
        if request_identity.get(key) == expected_value:
            continue
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_POLICY_MISMATCH,
            instance_path=f"/policies/{policy_name}/{key}",
            message="Assurance intelligence policy identity does not match supplied policy.",
            related_ids=(str(request_identity.get(key)), expected_value),
        )


def intelligence_datetimes(
    request: Mapping[str, Any],
    projected_at: datetime | str,
) -> tuple[datetime, datetime, datetime]:
    try:
        return (
            normalize_aware_datetime(request["effective_at"], field_name="effective_at"),
            normalize_aware_datetime(request["knowledge_cutoff"], field_name="knowledge_cutoff"),
            normalize_aware_datetime(projected_at, field_name="projected_at"),
        )
    except KeyError as exc:
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_REQUEST_INVALID,
            instance_path=f"/{exc.args[0]}",
            message=f"Assurance intelligence request missing {exc.args[0]!r}.",
        ) from exc


def repository_collection(repository: Mapping[str, Any], name: str) -> tuple[Mapping[str, Any], ...]:
    collection = repository.get(name)
    if collection is None:
        return ()
    if isinstance(collection, Mapping):
        values = collection.values()
    elif isinstance(collection, list | tuple):
        values = collection
    else:
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_REQUEST_INVALID,
            instance_path=f"/repository/{name}",
            message=f"Repository collection {name!r} must be a mapping or list.",
        )
    records: list[Mapping[str, Any]] = []
    for record in values:
        if not isinstance(record, Mapping):
            raise AssuranceIntelligenceError(
                code=ASSURANCE_INTELLIGENCE_REQUEST_INVALID,
                instance_path=f"/repository/{name}",
                message=f"Repository collection {name!r} contains a non-object record.",
            )
        records.append(record)
    return tuple(records)


def observation_recorded_at(observation: Mapping[str, Any]) -> datetime:
    recorded_at = observation.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_REQUEST_INVALID,
            instance_path="/recorded_at",
            message="Assurance observation has no usable recorded_at timestamp.",
        )
    return normalize_aware_datetime(recorded_at, field_name="recorded_at")


def admitted_assurance_observations(
    repository: Mapping[str, Any],
    *,
    knowledge_cutoff: datetime,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        sorted(
            (
                observation
                for observation in repository_collection(repository, "assurance_observations")
                if observation_recorded_at(observation) <= knowledge_cutoff
            ),
            key=lambda observation: require_string(observation, "assurance_observation_id"),
        )
    )


def intelligence_policy_identities(
    *,
    lifecycle_policy: Mapping[str, Any],
    verification_policy: Mapping[str, Any],
    freshness_policy: Mapping[str, Any],
    evidence_set_policy: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    _, lifecycle_identity = projection_policy_identity(lifecycle_policy)
    _, verification_identity = verification_policy_identity(verification_policy)
    _, freshness_identity = verification_freshness_policy_identity(freshness_policy)
    _, evidence_identity = evidence_set_policy_identity(evidence_set_policy)
    return (
        lifecycle_identity.as_mapping(),
        verification_identity.as_mapping(),
        freshness_identity.as_mapping(),
        evidence_identity.as_mapping(),
    )


def intelligence_input_manifest(
    *,
    request: Mapping[str, Any],
    target: Mapping[str, Any],
    repository: Mapping[str, Any],
    policies: Mapping[str, Mapping[str, str]],
    effective_at: datetime,
    knowledge_cutoff: datetime,
) -> dict[str, Any]:
    assurance_id = require_string(target, "assurance_id")
    admitted_observations = [
        json_material(observation)
        for observation in admitted_assurance_observations(
            repository,
            knowledge_cutoff=knowledge_cutoff,
        )
    ]
    return {
        "projection_profile": INTELLIGENCE_PROFILE,
        "assurance_id": assurance_id,
        "effective_at": format_utc_datetime(effective_at),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff),
        "policies": json_material(policies),
        "target_vendor_id": require_string(target, "vendor_id"),
        "repository": {
            **admitted_repository_records_for_manifest(
                repository,
                knowledge_cutoff=knowledge_cutoff,
            ),
            "assurance_observations": admitted_observations,
        },
        "request_assurance_id": request["assurance_id"],
    }


def intelligence_input_digest(manifest: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(json_material(manifest)))


def earliest_reevaluation(*boundaries: str | None) -> str | None:
    non_null = [normalize_aware_datetime(value, field_name="next_reevaluation_at") for value in boundaries if value]
    if not non_null:
        return None
    return format_utc_datetime(min(non_null))


def intelligence_event_policy_ref(
    projection: Mapping[str, Any],
    *,
    axis_name: str,
) -> dict[str, str]:
    policies = projection.get("policies")
    if not isinstance(policies, Mapping):
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_DIFF_INPUT_INVALID,
            instance_path="/policies",
            message="Intelligence projection policies must be an object.",
        )
    policy_name = POLICY_BY_INTELLIGENCE_AXIS[axis_name]
    policy = policies.get(policy_name)
    if not isinstance(policy, Mapping):
        raise AssuranceIntelligenceError(
            code=ASSURANCE_INTELLIGENCE_DIFF_INPUT_INVALID,
            instance_path=f"/policies/{policy_name}",
            message=f"Intelligence projection policy {policy_name!r} must be an object.",
        )
    return {
        "id": require_string(policy, "id"),
        "version": require_string(policy, "version"),
    }


def intelligence_event_identity_manifest(
    event: Mapping[str, Any],
    *,
    new_projection: Mapping[str, Any],
    axis_name: str,
) -> dict[str, Any]:
    policies = new_projection["policies"]
    policy_name = POLICY_BY_INTELLIGENCE_AXIS[axis_name]
    return {
        "schema_version": event["schema_version"],
        "projection_profile": new_projection["projection_profile"],
        "axis": axis_name,
        "assurance_id": event["assurance_id"],
        "vendor_id": event["vendor_id"],
        "change_type": event["change_type"],
        "transition": json_material(event["transition"]),
        "effective_at": event["effective_at"],
        "knowledge_cutoff": event["knowledge_cutoff"],
        "input_digest": event["input_digest"],
        "policy": json_material(policies[policy_name]),
        "advisory_boundary": event["advisory_boundary"],
        "reason_code": event["reason_code"],
        "caused_by": json_material(event["caused_by"]),
    }


def build_intelligence_change_event(
    *,
    axis_name: str,
    previous_axis: Mapping[str, Any] | None,
    new_axis: Mapping[str, Any],
    new_projection: Mapping[str, Any],
    detected_at: datetime,
) -> dict[str, Any]:
    from_value = None if previous_axis is None else axis_state_value(previous_axis, axis_name=axis_name)
    to_value = axis_state_value(new_axis, axis_name=axis_name)
    event = {
        "schema_version": "0.1.0",
        "change_event_id": "temporary-change-event-id",
        "assurance_id": require_string(new_projection, "assurance_id"),
        "vendor_id": require_string(new_projection, "vendor_id"),
        "detected_at": format_utc_datetime(detected_at),
        "effective_at": require_string(new_projection, "effective_at"),
        "knowledge_cutoff": require_string(new_projection, "knowledge_cutoff"),
        "input_digest": require_string(new_projection, "input_digest"),
        "change_type": CHANGE_TYPE_BY_INTELLIGENCE_AXIS[axis_name],
        "transition": {
            "axis": axis_name,
            "from": from_value,
            "to": to_value,
        },
        "reason_code": singular_axis_reason(new_axis, axis_name=axis_name),
        "caused_by": event_caused_by(new_axis, axis_name=axis_name),
        "policy": intelligence_event_policy_ref(new_projection, axis_name=axis_name),
        "advisory_boundary": require_string(new_projection, "advisory_boundary"),
    }
    manifest = intelligence_event_identity_manifest(
        event,
        new_projection=new_projection,
        axis_name=axis_name,
    )
    event["change_event_id"] = change_event_id_for_manifest(manifest)
    return event


def diff_assurance_intelligence_projections(
    previous_projection: Mapping[str, Any] | None,
    new_projection: Mapping[str, Any],
    detected_at: datetime | str,
) -> tuple[Mapping[str, Any], ...]:
    detected_at_utc = validate_intelligence_diff_inputs(previous_projection, new_projection, detected_at)
    events: list[dict[str, Any]] = []
    for axis_name in INTELLIGENCE_AXES:
        new_axis = projection_axis(new_projection, axis_name)
        previous_axis = None if previous_projection is None else projection_axis(previous_projection, axis_name)
        if previous_axis is not None and axis_state_value(previous_axis, axis_name=axis_name) == axis_state_value(
            new_axis,
            axis_name=axis_name,
        ):
            continue
        events.append(
            build_intelligence_change_event(
                axis_name=axis_name,
                previous_axis=previous_axis,
                new_axis=new_axis,
                new_projection=new_projection,
                detected_at=detected_at_utc,
            )
        )

    for event in events:
        try:
            validate_change_event_output(event)
        except AssuranceProjectionError as exc:
            if exc.code == ASSURANCE_CHANGE_EVENT_REASON_AMBIGUOUS:
                raise
            raise
    return tuple(events)


def lifecycle_request_from_intelligence(
    request: Mapping[str, Any],
    *,
    lifecycle_policy_identity: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "assurance_id": request["assurance_id"],
        "effective_at": request["effective_at"],
        "knowledge_cutoff": request["knowledge_cutoff"],
        "policy": dict(lifecycle_policy_identity),
    }


def project_assurance_intelligence(
    request: Mapping[str, Any],
    repository: Mapping[str, Any],
    lifecycle_policy: Mapping[str, Any],
    verification_policy: Mapping[str, Any],
    freshness_policy: Mapping[str, Any],
    evidence_set_policy: Mapping[str, Any],
    projected_at: datetime | str,
) -> Mapping[str, Any]:
    validate_intelligence_request(request)
    effective_at, knowledge_cutoff, projected_at_utc = intelligence_datetimes(request, projected_at)

    lifecycle_identity, verification_identity, freshness_identity, evidence_identity = intelligence_policy_identities(
        lifecycle_policy=lifecycle_policy,
        verification_policy=verification_policy,
        freshness_policy=freshness_policy,
        evidence_set_policy=evidence_set_policy,
    )
    policy_identities = {
        "lifecycle": lifecycle_identity,
        "verification": verification_identity,
        "verification_freshness": freshness_identity,
        "evidence_set": evidence_identity,
    }
    for policy_name, identity in policy_identities.items():
        verify_policy_identity(request=request, policy_name=policy_name, identity=identity)

    try:
        target = resolve_target_assurance(repository, require_string(request, "assurance_id"))
    except AssuranceProjectionError as exc:
        if exc.code == "ASSURANCE_TARGET_UNKNOWN":
            raise AssuranceIntelligenceError(
                code=ASSURANCE_INTELLIGENCE_TARGET_UNKNOWN,
                instance_path=exc.instance_path,
                message=str(exc),
                related_ids=exc.related_ids,
            ) from exc
        raise

    lifecycle_projection = project_assurance(
        lifecycle_request_from_intelligence(request, lifecycle_policy_identity=lifecycle_identity),
        repository,
        lifecycle_policy,
        projected_at_utc,
    )
    admitted_observations = admitted_assurance_observations(repository, knowledge_cutoff=knowledge_cutoff)
    verification = project_verification_state(
        target,
        admitted_observations,
        verification_policy,
        effective_at,
        knowledge_cutoff,
    )
    freshness = project_verification_freshness(
        target,
        admitted_observations,
        verification.state,
        freshness_policy,
        effective_at,
        knowledge_cutoff,
    )
    evidence_set = project_evidence_set_state(
        target,
        admitted_observations,
        verification_policy,
        evidence_set_policy,
        effective_at,
        knowledge_cutoff,
    )

    input_manifest = intelligence_input_manifest(
        request=request,
        target=target,
        repository=repository,
        policies=policy_identities,
        effective_at=effective_at,
        knowledge_cutoff=knowledge_cutoff,
    )
    projection = {
        "schema_version": "0.1.0",
        "projection_profile": INTELLIGENCE_PROFILE,
        "implemented_axes": list(INTELLIGENCE_AXES),
        "assurance_id": request["assurance_id"],
        "vendor_id": require_string(target, "vendor_id"),
        "effective_at": format_utc_datetime(effective_at),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff),
        "projected_at": format_utc_datetime(projected_at_utc),
        "policies": policy_identities,
        "input_digest": intelligence_input_digest(input_manifest),
        "next_reevaluation_at": earliest_reevaluation(
            lifecycle_projection["next_reevaluation_at"],
            freshness.freshness["next_reevaluation_at"],
        ),
        "axes": {
            "instrument_state": lifecycle_projection["axes"]["instrument_state"],
            "supersession_state": lifecycle_projection["axes"]["supersession_state"],
            "verification_state": dict(verification.state),
            "verification_freshness": dict(freshness.freshness),
            "evidence_set_state": dict(evidence_set.state),
        },
        "advisory_boundary": "non_advisory",
    }
    validate_intelligence_output(projection)
    return projection
