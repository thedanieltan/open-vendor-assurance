from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from typing import Any

from tools.openva.assurance_projection_policy import AssuranceProjectionPolicy
from tools.openva.assurance_projection_policy import build_assurance_projection_policy
from tools.openva.assurance_validation import ASSURANCE
from tools.openva.assurance_validation import SOURCE
from tools.openva.assurance_validation import VENDOR
from tools.openva.assurance_validation import RepositoryRecord
from tools.openva.assurance_validation import RepositorySnapshot
from tools.openva.assurance_validation import SupersessionEdge
from tools.openva.assurance_validation import ValidationDiagnostic
from tools.openva.assurance_validation import _admissible_supersession_edges
from tools.openva.assurance_validation import validate_assurance_repository
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator

ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF = "ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF"
ASSURANCE_PROJECTION_DATETIME_NAIVE = "ASSURANCE_PROJECTION_DATETIME_NAIVE"
ASSURANCE_PROJECTION_POLICY_INVALID = "ASSURANCE_PROJECTION_POLICY_INVALID"
ASSURANCE_PROJECTION_CLASS_RULE_MISSING = "ASSURANCE_PROJECTION_CLASS_RULE_MISSING"
ASSURANCE_PROJECTION_INPUT_INVALID = "ASSURANCE_PROJECTION_INPUT_INVALID"
ASSURANCE_PROJECTION_REQUEST_INVALID = "ASSURANCE_PROJECTION_REQUEST_INVALID"
ASSURANCE_PROJECTION_POLICY_MISMATCH = "ASSURANCE_PROJECTION_POLICY_MISMATCH"
ASSURANCE_TARGET_UNKNOWN = "ASSURANCE_TARGET_UNKNOWN"
ASSURANCE_PROJECTION_OUTPUT_INVALID = "ASSURANCE_PROJECTION_OUTPUT_INVALID"
PROJECTION_PROFILE = "openva.assurance-lifecycle.v1"
IMPLEMENTED_AXES = ("instrument_state", "supersession_state")
PROJECTION_REQUEST_SCHEMA_PATH = ROOT / "schemas/openva/assurance-projection-request.schema.json"
PROJECTION_SCHEMA_PATH = ROOT / "schemas/openva/assurance-projection.schema.json"


class AssuranceProjectionError(Exception):
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


class ProjectionInputInvalidError(AssuranceProjectionError):
    def __init__(self, diagnostics: tuple[ValidationDiagnostic, ...]) -> None:
        super().__init__(
            code=ASSURANCE_PROJECTION_INPUT_INVALID,
            message="Projection input failed assurance semantic validation.",
        )
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class ProjectionPolicyIdentity:
    id: str
    version: str
    digest: str

    def as_mapping(self) -> dict[str, str]:
        return {
            "id": self.id,
            "version": self.version,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class InstrumentStateResult:
    axis: Mapping[str, Any]
    next_reevaluation_at: datetime | None


@dataclass(frozen=True, slots=True)
class SupersessionStateResult:
    axis: Mapping[str, Any]


def normalize_aware_datetime(value: datetime | str, *, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AssuranceProjectionError(
                code=ASSURANCE_PROJECTION_DATETIME_NAIVE,
                instance_path=f"/{field_name}",
                message=f"{field_name} must be a timezone-aware date-time.",
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_DATETIME_NAIVE,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be a timezone-aware date-time.",
        )

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_DATETIME_NAIVE,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be timezone-aware.",
        )
    return parsed.astimezone(UTC)


def parse_source_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be an ISO date.",
        ) from exc


def start_of_utc_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def end_exclusive_after_inclusive_date(value: date) -> datetime:
    return start_of_utc_day(value + timedelta(days=1))


def format_utc_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def json_material(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_material(nested) for key, nested in value.items()}
    if isinstance(value, tuple | list):
        return [json_material(nested) for nested in value]
    return value


def validation_instance_path(error: Any) -> str:
    return "/" + "/".join(str(part) for part in error.path) if error.path else ""


def validate_projection_request(request: Mapping[str, Any]) -> None:
    validator = build_openva_validator(PROJECTION_REQUEST_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(request), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceProjectionError(
        code=ASSURANCE_PROJECTION_REQUEST_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Projection request is invalid: {error.message}",
    )


def projection_policy_identity(
    policy: AssuranceProjectionPolicy | Mapping[str, Any],
) -> tuple[AssuranceProjectionPolicy, ProjectionPolicyIdentity]:
    projection_policy = coerce_projection_policy(policy)
    policy_material = json_material(projection_policy.data)
    digest = sha256_bytes(canonical_json(policy_material))
    return projection_policy, ProjectionPolicyIdentity(
        id=projection_policy.policy_id,
        version=projection_policy.policy_version,
        digest=digest,
    )


def verify_request_policy_identity(
    request: Mapping[str, Any],
    policy_identity: ProjectionPolicyIdentity,
) -> None:
    policy_reference = request.get("policy")
    if not isinstance(policy_reference, Mapping):
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_REQUEST_INVALID,
            instance_path="/policy",
            message="Projection request policy reference must be an object.",
        )
    expected = policy_identity.as_mapping()
    for key, expected_value in expected.items():
        if policy_reference.get(key) == expected_value:
            continue
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_MISMATCH,
            instance_path=f"/policy/{key}",
            message="Projection request policy identity does not match supplied policy.",
            related_ids=(str(policy_reference.get(key)), expected_value),
        )


def projection_datetimes(
    request: Mapping[str, Any],
    projected_at: datetime | str,
) -> tuple[datetime, datetime, datetime]:
    effective_at = normalize_aware_datetime(request["effective_at"], field_name="effective_at")
    knowledge_cutoff = normalize_aware_datetime(request["knowledge_cutoff"], field_name="knowledge_cutoff")
    projected_at_utc = normalize_aware_datetime(projected_at, field_name="projected_at")
    return effective_at, knowledge_cutoff, projected_at_utc


def repository_collection(
    repository: Mapping[str, Any],
    collection_name: str,
) -> tuple[Mapping[str, Any], ...]:
    collection = repository.get(collection_name, ())
    if isinstance(collection, Mapping):
        values = collection.values()
    elif isinstance(collection, list | tuple):
        values = collection
    else:
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_INPUT_INVALID,
            instance_path=f"/repository/{collection_name}",
            message=f"Repository collection {collection_name!r} must be a mapping or list.",
        )

    records: list[Mapping[str, Any]] = []
    for record in values:
        if not isinstance(record, Mapping):
            raise AssuranceProjectionError(
                code=ASSURANCE_PROJECTION_INPUT_INVALID,
                instance_path=f"/repository/{collection_name}",
                message=f"Repository collection {collection_name!r} contains a non-object record.",
            )
        records.append(record)
    return tuple(records)


def repository_assurance_records(repository: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    return repository_collection(repository, "assurances")


def repository_record_id(record: Mapping[str, Any], id_field: str) -> str:
    value = record.get(id_field)
    if not isinstance(value, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_INPUT_INVALID,
            instance_path=f"/{id_field}",
            message=f"Repository record must define string {id_field}.",
        )
    return value


def sort_records_by_id(records: Iterable[Mapping[str, Any]], id_field: str) -> list[dict[str, Any]]:
    return [
        json_material(record)
        for record in sorted(records, key=lambda record: repository_record_id(record, id_field))
    ]


def admitted_repository_records_for_manifest(
    repository: Mapping[str, Any],
    *,
    knowledge_cutoff: datetime,
) -> dict[str, list[dict[str, Any]]]:
    admitted_assurances = [
        record
        for record in repository_assurance_records(repository)
        if assurance_recorded_at(
            record,
            field_name=f"assurances/{repository_record_id(record, 'assurance_id')}/recorded_at",
        )
        <= knowledge_cutoff
    ]
    return {
        "vendors": sort_records_by_id(repository_collection(repository, "vendors"), "vendor_id"),
        "sources": sort_records_by_id(repository_collection(repository, "sources"), "source_id"),
        "assurances": sort_records_by_id(admitted_assurances, "assurance_id"),
    }


def projection_input_manifest(
    *,
    request: Mapping[str, Any],
    repository: Mapping[str, Any],
    policy_identity: ProjectionPolicyIdentity,
    effective_at: datetime,
    knowledge_cutoff: datetime,
) -> dict[str, Any]:
    return {
        "projection_profile": PROJECTION_PROFILE,
        "target_assurance_id": request["assurance_id"],
        "effective_at": format_utc_datetime(effective_at),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff),
        "policy": policy_identity.as_mapping(),
        "repository": admitted_repository_records_for_manifest(
            repository,
            knowledge_cutoff=knowledge_cutoff,
        ),
    }


def projection_input_digest(input_manifest: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(json_material(input_manifest)))


def empty_instrument_axis(*, assurance_id: str, temporal_model: str) -> dict[str, Any]:
    return {
        "determination": "determined",
        "value": None,
        "temporal_model": temporal_model,
        "reason_codes": [],
        "caused_by": {
            "assurance_ids": [assurance_id],
            "assurance_observation_ids": [],
            "source_observation_ids": [],
        },
        "stated_valid_from": None,
        "stated_valid_until": None,
        "interval_start_at": None,
        "interval_end_exclusive_at": None,
        "stated_as_of_date": None,
        "as_of_at": None,
        "stated_reporting_period_start": None,
        "stated_reporting_period_end": None,
        "reporting_period_start_at": None,
        "reporting_period_end_exclusive_at": None,
        "stated_effective_from_claimed": None,
        "stated_effective_until_claimed": None,
        "claimed_interval_start_at": None,
        "claimed_interval_end_exclusive_at": None,
    }


def ensure_target_known_at_cutoff(
    assurance_record: Mapping[str, Any],
    *,
    knowledge_cutoff: datetime,
) -> None:
    assurance_id = assurance_record.get("assurance_id")
    recorded_at_raw = assurance_record.get("recorded_at")
    if not isinstance(recorded_at_raw, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
            instance_path="/recorded_at",
            message="Assurance record has no usable recorded_at timestamp.",
            related_ids=(str(assurance_id),) if isinstance(assurance_id, str) else (),
        )
    recorded_at = normalize_aware_datetime(recorded_at_raw, field_name="recorded_at")
    if recorded_at > knowledge_cutoff:
        raise AssuranceProjectionError(
            code=ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
            instance_path="/recorded_at",
            message="Assurance record is not known at the supplied knowledge cutoff.",
            related_ids=(assurance_id,) if isinstance(assurance_id, str) else (),
        )


def assurance_id_for(assurance_record: Mapping[str, Any]) -> str:
    return require_string(assurance_record, "assurance_id")


def assurance_recorded_at(
    assurance_record: Mapping[str, Any],
    *,
    field_name: str = "recorded_at",
) -> datetime:
    recorded_at = assurance_record.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
            instance_path="/recorded_at",
            message="Assurance record has no usable recorded_at timestamp.",
            related_ids=(
                str(assurance_record.get("assurance_id")),
            )
            if isinstance(assurance_record.get("assurance_id"), str)
            else (),
        )
    return normalize_aware_datetime(recorded_at, field_name=field_name)


def admitted_assurance_records(
    target_record: Mapping[str, Any],
    assurance_records: Iterable[Mapping[str, Any]],
    *,
    knowledge_cutoff: datetime,
) -> tuple[Mapping[str, Any], ...]:
    target_id = assurance_id_for(target_record)
    records_by_id: dict[str, Mapping[str, Any]] = {}
    for record in assurance_records:
        record_id = assurance_id_for(record)
        records_by_id[record_id] = record
    records_by_id[target_id] = target_record

    ensure_target_known_at_cutoff(target_record, knowledge_cutoff=knowledge_cutoff)
    admitted = [
        record
        for record_id, record in sorted(records_by_id.items())
        if assurance_recorded_at(record, field_name=f"assurance_records/{record_id}/recorded_at")
        <= knowledge_cutoff
    ]
    return tuple(admitted)


def build_projection_repository_snapshot(
    assurance_records: Iterable[Mapping[str, Any]],
) -> RepositorySnapshot:
    assurance_repo_records: dict[str, RepositoryRecord] = {}
    vendor_ids: set[str] = set()
    source_payloads: dict[str, Mapping[str, Any]] = {}
    for record in assurance_records:
        repo_record = RepositoryRecord.from_raw(spec=ASSURANCE, payload=record)
        assurance_repo_records[repo_record.record_id] = repo_record
        vendor_id = require_string(record, "vendor_id")
        vendor_ids.add(vendor_id)

        evidence = record.get("evidence")
        if isinstance(evidence, Mapping):
            source_ids = evidence.get("source_ids")
            if isinstance(source_ids, list | tuple):
                for source_id in source_ids:
                    if isinstance(source_id, str) and source_id not in source_payloads:
                        source_payloads[source_id] = {
                            "source_id": source_id,
                            "vendor_id": vendor_id,
                        }

    vendor_records = {
        vendor_id: RepositoryRecord.from_raw(spec=VENDOR, payload={"vendor_id": vendor_id})
        for vendor_id in sorted(vendor_ids)
    }
    source_records = {
        source_id: RepositoryRecord.from_raw(spec=SOURCE, payload=payload)
        for source_id, payload in sorted(source_payloads.items())
    }
    return RepositorySnapshot(
        vendors=MappingProxyType(vendor_records),
        sources=MappingProxyType(source_records),
        source_observations=MappingProxyType({}),
        assurances=MappingProxyType(dict(sorted(assurance_repo_records.items()))),
        assurance_observations=MappingProxyType({}),
        assurance_change_events=MappingProxyType({}),
    )


def admitted_supersession_edges_or_raise(
    repository: RepositorySnapshot,
) -> tuple[SupersessionEdge, ...]:
    diagnostics = validate_assurance_repository(repository)
    if diagnostics:
        raise ProjectionInputInvalidError(diagnostics)
    return _admissible_supersession_edges(repository)


def temporal_model_for_record(
    assurance_record: Mapping[str, Any],
    policy: AssuranceProjectionPolicy,
) -> str:
    assurance_class = assurance_record.get("assurance_class")
    if not isinstance(assurance_class, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path="/assurance_class",
            message="Assurance record must define assurance_class.",
        )
    try:
        return policy.temporal_model_for(assurance_class)
    except Exception as exc:
        code = getattr(exc, "code", ASSURANCE_PROJECTION_POLICY_INVALID)
        instance_path = getattr(exc, "instance_path", "")
        related_ids = getattr(exc, "related_ids", ())
        raise AssuranceProjectionError(
            code=code,
            instance_path=instance_path,
            message=str(exc),
            related_ids=tuple(related_ids),
        ) from exc


def project_instrument_state(
    assurance_record: Mapping[str, Any],
    policy: AssuranceProjectionPolicy | Mapping[str, Any],
    effective_at: datetime | str,
    knowledge_cutoff: datetime | str,
) -> InstrumentStateResult:
    projection_policy = coerce_projection_policy(policy)
    effective_at_utc = normalize_aware_datetime(effective_at, field_name="effective_at")
    knowledge_cutoff_utc = normalize_aware_datetime(knowledge_cutoff, field_name="knowledge_cutoff")
    ensure_target_known_at_cutoff(assurance_record, knowledge_cutoff=knowledge_cutoff_utc)

    assurance_class = assurance_record.get("assurance_class")
    temporal_model = temporal_model_for_record(assurance_record, projection_policy)
    if assurance_class == "accredited_certification":
        return project_certification(assurance_record, temporal_model, effective_at_utc)
    if assurance_class == "attestation_report":
        return project_attestation(assurance_record, temporal_model, effective_at_utc)
    if assurance_class == "regulatory_assertion":
        return project_regulatory_assertion(assurance_record, temporal_model, effective_at_utc)
    if assurance_class == "contractual_capability":
        return project_contractual_capability(assurance_record, temporal_model, effective_at_utc)
    raise AssuranceProjectionError(
        code=ASSURANCE_PROJECTION_POLICY_INVALID,
        instance_path="/assurance_class",
        message=f"Unsupported assurance_class {assurance_class!r}.",
    )


def project_supersession_state(
    assurance_record: Mapping[str, Any],
    assurance_records: Iterable[Mapping[str, Any]],
    policy: AssuranceProjectionPolicy | Mapping[str, Any],
    knowledge_cutoff: datetime | str,
) -> SupersessionStateResult:
    projection_policy = coerce_projection_policy(policy)
    try:
        projection_policy.require_explicit_supersession_policy()
    except Exception as exc:
        code = getattr(exc, "code", ASSURANCE_PROJECTION_POLICY_INVALID)
        instance_path = getattr(exc, "instance_path", "")
        related_ids = getattr(exc, "related_ids", ())
        raise AssuranceProjectionError(
            code=code,
            instance_path=instance_path,
            message=str(exc),
            related_ids=tuple(related_ids),
        ) from exc

    knowledge_cutoff_utc = normalize_aware_datetime(knowledge_cutoff, field_name="knowledge_cutoff")
    target_id = assurance_id_for(assurance_record)
    admitted_records = admitted_assurance_records(
        assurance_record,
        assurance_records,
        knowledge_cutoff=knowledge_cutoff_utc,
    )
    repository = build_projection_repository_snapshot(admitted_records)
    admitted_edges = admitted_supersession_edges_or_raise(repository)

    predecessor_ids = sorted(
        edge.predecessor_id for edge in admitted_edges if edge.successor_id == target_id
    )
    successor_ids = sorted(
        edge.successor_id for edge in admitted_edges if edge.predecessor_id == target_id
    )
    predecessor_id = predecessor_ids[0] if predecessor_ids else None

    if predecessor_id is None and not successor_ids:
        return finish_supersession_axis(
            target_id=target_id,
            predecessor_id=None,
            successor_ids=(),
            topology="standalone",
            value="current",
            reason_code="no_explicit_successor_admitted",
        )
    if predecessor_id is None:
        return finish_supersession_axis(
            target_id=target_id,
            predecessor_id=None,
            successor_ids=successor_ids,
            topology="chain_root",
            value="superseded",
            reason_code="explicit_successor_admitted",
        )
    if successor_ids:
        return finish_supersession_axis(
            target_id=target_id,
            predecessor_id=predecessor_id,
            successor_ids=successor_ids,
            topology="chain_intermediate",
            value="superseded",
            reason_code="explicit_successor_admitted",
        )
    return finish_supersession_axis(
        target_id=target_id,
        predecessor_id=predecessor_id,
        successor_ids=(),
        topology="chain_tip",
        value="current",
        reason_code="no_explicit_successor_admitted",
    )


def coerce_projection_policy(
    policy: AssuranceProjectionPolicy | Mapping[str, Any],
) -> AssuranceProjectionPolicy:
    if isinstance(policy, AssuranceProjectionPolicy):
        return policy
    if isinstance(policy, Mapping):
        try:
            return build_assurance_projection_policy(policy)
        except Exception as exc:
            code = getattr(exc, "code", ASSURANCE_PROJECTION_POLICY_INVALID)
            instance_path = getattr(exc, "instance_path", "")
            related_ids = getattr(exc, "related_ids", ())
            raise AssuranceProjectionError(
                code=code,
                instance_path=instance_path,
                message=str(exc),
                related_ids=tuple(related_ids),
            ) from exc
    raise AssuranceProjectionError(
        code=ASSURANCE_PROJECTION_POLICY_INVALID,
        message="Projection policy must be a mapping or AssuranceProjectionPolicy.",
    )


def project_certification(
    assurance_record: Mapping[str, Any],
    temporal_model: str,
    effective_at: datetime,
) -> InstrumentStateResult:
    assurance_id = require_string(assurance_record, "assurance_id")
    temporal_scope = require_mapping(assurance_record, "temporal_scope")
    valid_from = require_date_string(temporal_scope, "valid_from", "/temporal_scope/valid_from")
    valid_until = require_date_string(temporal_scope, "valid_until", "/temporal_scope/valid_until")
    interval_start = start_of_utc_day(parse_source_date(valid_from, field_name="temporal_scope/valid_from"))
    interval_end = end_exclusive_after_inclusive_date(
        parse_source_date(valid_until, field_name="temporal_scope/valid_until")
    )

    axis = empty_instrument_axis(assurance_id=assurance_id, temporal_model=temporal_model)
    axis["stated_valid_from"] = valid_from
    axis["stated_valid_until"] = valid_until
    axis["interval_start_at"] = format_utc_datetime(interval_start)
    axis["interval_end_exclusive_at"] = format_utc_datetime(interval_end)
    if effective_at < interval_start:
        return finish_axis(axis, "not_yet_effective", "effective_at_before_valid_from", interval_start)
    if effective_at < interval_end:
        return finish_axis(axis, "effective", "effective_at_within_stated_interval", interval_end)
    return finish_axis(axis, "expired", "stated_valid_until_passed", None)


def project_attestation(
    assurance_record: Mapping[str, Any],
    temporal_model: str,
    effective_at: datetime,
) -> InstrumentStateResult:
    assurance_id = require_string(assurance_record, "assurance_id")
    temporal_scope = require_mapping(assurance_record, "temporal_scope")
    axis = empty_instrument_axis(assurance_id=assurance_id, temporal_model=temporal_model)

    as_of_date = temporal_scope.get("as_of_date")
    if isinstance(as_of_date, str):
        as_of_at = start_of_utc_day(parse_source_date(as_of_date, field_name="temporal_scope/as_of_date"))
        axis["stated_as_of_date"] = as_of_date
        axis["as_of_at"] = format_utc_datetime(as_of_at)
        if effective_at < as_of_at:
            return finish_axis(axis, "not_yet_effective", "effective_at_before_valid_from", as_of_at)
        return finish_axis(axis, "historical", "point_in_time_scope", None)

    reporting_period = temporal_scope.get("reporting_period")
    if isinstance(reporting_period, Mapping):
        start = require_date_string(reporting_period, "start", "/temporal_scope/reporting_period/start")
        end = require_date_string(reporting_period, "end", "/temporal_scope/reporting_period/end")
        period_start = start_of_utc_day(parse_source_date(start, field_name="temporal_scope/reporting_period/start"))
        period_end = end_exclusive_after_inclusive_date(
            parse_source_date(end, field_name="temporal_scope/reporting_period/end")
        )
        axis["stated_reporting_period_start"] = start
        axis["stated_reporting_period_end"] = end
        axis["reporting_period_start_at"] = format_utc_datetime(period_start)
        axis["reporting_period_end_exclusive_at"] = format_utc_datetime(period_end)
        if effective_at < period_end:
            return finish_axis(axis, "not_yet_effective", "reporting_period_scope", period_end)
        return finish_axis(axis, "historical", "reporting_period_scope", None)

    raise AssuranceProjectionError(
        code=ASSURANCE_PROJECTION_POLICY_INVALID,
        instance_path="/temporal_scope",
        message="Attestation report must define as_of_date or reporting_period.",
    )


def project_regulatory_assertion(
    assurance_record: Mapping[str, Any],
    temporal_model: str,
    effective_at: datetime,
) -> InstrumentStateResult:
    assurance_id = require_string(assurance_record, "assurance_id")
    temporal_scope = require_mapping(assurance_record, "temporal_scope")
    axis = empty_instrument_axis(assurance_id=assurance_id, temporal_model=temporal_model)

    claimed_as_of = temporal_scope.get("claimed_as_of")
    if isinstance(claimed_as_of, str):
        as_of_at = start_of_utc_day(parse_source_date(claimed_as_of, field_name="temporal_scope/claimed_as_of"))
        axis["stated_as_of_date"] = claimed_as_of
        axis["as_of_at"] = format_utc_datetime(as_of_at)
        if effective_at < as_of_at:
            return finish_axis(axis, "not_yet_effective", "effective_at_before_valid_from", as_of_at)
        return finish_axis(axis, "historical", "point_in_time_scope", None)

    effective_from = temporal_scope.get("effective_from_claimed")
    if isinstance(effective_from, str):
        claimed_start = start_of_utc_day(
            parse_source_date(effective_from, field_name="temporal_scope/effective_from_claimed")
        )
        axis["stated_effective_from_claimed"] = effective_from
        axis["claimed_interval_start_at"] = format_utc_datetime(claimed_start)
        if effective_at < claimed_start:
            return finish_axis(axis, "not_yet_effective", "effective_at_before_valid_from", claimed_start)
        return finish_axis(axis, "temporally_indeterminate", "no_stated_end_date", None)

    return finish_axis(axis, "temporally_indeterminate", "no_usable_dates", None)


def project_contractual_capability(
    assurance_record: Mapping[str, Any],
    temporal_model: str,
    effective_at: datetime,
) -> InstrumentStateResult:
    assurance_id = require_string(assurance_record, "assurance_id")
    temporal_scope = require_mapping(assurance_record, "temporal_scope")
    axis = empty_instrument_axis(assurance_id=assurance_id, temporal_model=temporal_model)

    effective_from = temporal_scope.get("effective_from_claimed")
    effective_until = temporal_scope.get("effective_until_claimed")
    start = (
        start_of_utc_day(parse_source_date(effective_from, field_name="temporal_scope/effective_from_claimed"))
        if isinstance(effective_from, str)
        else None
    )
    end = (
        end_exclusive_after_inclusive_date(
            parse_source_date(effective_until, field_name="temporal_scope/effective_until_claimed")
        )
        if isinstance(effective_until, str)
        else None
    )
    axis["stated_effective_from_claimed"] = effective_from if isinstance(effective_from, str) else None
    axis["stated_effective_until_claimed"] = effective_until if isinstance(effective_until, str) else None
    axis["claimed_interval_start_at"] = format_utc_datetime(start)
    axis["claimed_interval_end_exclusive_at"] = format_utc_datetime(end)

    if start is not None and end is not None:
        if effective_at < start:
            return finish_axis(axis, "not_yet_effective", "effective_at_before_valid_from", start)
        if effective_at < end:
            return finish_axis(axis, "effective", "effective_at_within_stated_interval", end)
        return finish_axis(axis, "expired", "stated_valid_until_passed", None)
    if start is not None:
        if effective_at < start:
            return finish_axis(axis, "not_yet_effective", "effective_at_before_valid_from", start)
        return finish_axis(axis, "temporally_indeterminate", "no_stated_end_date", None)
    if end is not None:
        if effective_at < end:
            return finish_axis(axis, "temporally_indeterminate", "no_usable_dates", end)
        return finish_axis(axis, "expired", "stated_valid_until_passed", None)
    return finish_axis(axis, "temporally_indeterminate", "no_usable_dates", None)


def finish_axis(
    axis: dict[str, Any],
    value: str,
    reason_code: str,
    next_reevaluation_at: datetime | None,
) -> InstrumentStateResult:
    axis["determination"] = "determined"
    axis["value"] = value
    axis["reason_codes"] = [reason_code]
    return InstrumentStateResult(axis=axis, next_reevaluation_at=next_reevaluation_at)


def finish_supersession_axis(
    *,
    target_id: str,
    predecessor_id: str | None,
    successor_ids: Iterable[str],
    topology: str,
    value: str,
    reason_code: str,
) -> SupersessionStateResult:
    successor_list = sorted(successor_ids)
    causal_ids = [target_id]
    if predecessor_id is not None:
        causal_ids.append(predecessor_id)
    causal_ids.extend(successor_list)
    causal_ids = list(dict.fromkeys(causal_ids))
    return SupersessionStateResult(
        axis={
            "determination": "determined",
            "value": value,
            "topology": topology,
            "predecessor_assurance_id": predecessor_id,
            "successor_assurance_ids": successor_list,
            "reason_codes": [reason_code],
            "caused_by": {
                "assurance_ids": causal_ids,
                "assurance_observation_ids": [],
                "source_observation_ids": [],
            },
        }
    )


def require_mapping(record: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    value = record.get(field_name)
    if not isinstance(value, Mapping):
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be an object.",
        )
    return value


def require_string(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be a string.",
        )
    return value


def require_date_string(record: Mapping[str, Any], field_name: str, instance_path: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path=instance_path,
            message=f"{field_name} must be a date string.",
        )
    parse_source_date(value, field_name=instance_path.strip("/"))
    return value
