from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any

from tools.openva.assurance_projection import json_material
from tools.openva.assurance_projection import validation_instance_path
from tools.openva.assurance_validation import ASSURANCE
from tools.openva.assurance_validation import ASSURANCE_OBSERVATION
from tools.openva.assurance_validation import RepositoryRecord
from tools.openva.assurance_validation import RepositorySnapshot
from tools.openva.assurance_validation import ValidationDiagnostic
from tools.openva.assurance_validation import validate_assurance_observation_semantics
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator

ASSURANCE_VERIFICATION_DATETIME_NAIVE = "ASSURANCE_VERIFICATION_DATETIME_NAIVE"
ASSURANCE_VERIFICATION_POLICY_INVALID = "ASSURANCE_VERIFICATION_POLICY_INVALID"
ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF = "ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF"
ASSURANCE_VERIFICATION_INPUT_INVALID = "ASSURANCE_VERIFICATION_INPUT_INVALID"
ASSURANCE_VERIFICATION_OUTPUT_INVALID = "ASSURANCE_VERIFICATION_OUTPUT_INVALID"

VERIFICATION_POLICY_SCHEMA_PATH = ROOT / "schemas/openva/assurance-verification-policy.schema.json"
VERIFICATION_STATE_SCHEMA_PATH = ROOT / "schemas/openva/assurance-verification-state.schema.json"


class AssuranceVerificationError(Exception):
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


class VerificationInputInvalidError(AssuranceVerificationError):
    def __init__(self, diagnostics: tuple[ValidationDiagnostic, ...]) -> None:
        super().__init__(
            code=ASSURANCE_VERIFICATION_INPUT_INVALID,
            message="Verification input failed assurance-observation semantic validation.",
        )
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class VerificationPolicyIdentity:
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
class AssuranceVerificationPolicy:
    data: Mapping[str, Any]
    policy_id: str
    policy_version: str
    outcome_class_by_outcome: Mapping[str, str]
    authority_tier_by_outcome: Mapping[str, str]
    authority_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerificationStateResult:
    state: Mapping[str, Any]


def normalize_verification_datetime(value: datetime | str, *, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_DATETIME_NAIVE,
                instance_path=f"/{field_name}",
                message=f"{field_name} must be a timezone-aware date-time.",
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_DATETIME_NAIVE,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be a timezone-aware date-time.",
        )

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_DATETIME_NAIVE,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be timezone-aware.",
        )
    return parsed.astimezone(UTC)


def require_string(mapping: Mapping[str, Any], field_name: str) -> str:
    value = mapping.get(field_name)
    if not isinstance(value, str):
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_INPUT_INVALID,
            instance_path=f"/{field_name}",
            message=f"Verification input must define string {field_name}.",
        )
    return value


def parse_observed_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_INPUT_INVALID,
            instance_path="/observed_fields",
            message="Observed date fields must contain ISO date strings.",
        ) from exc


def assurance_recorded_at(assurance_record: Mapping[str, Any]) -> datetime:
    recorded_at = assurance_record.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF,
            instance_path="/recorded_at",
            message="Assurance record has no usable recorded_at timestamp.",
        )
    return normalize_verification_datetime(recorded_at, field_name="recorded_at")


def observation_recorded_at(observation: Mapping[str, Any]) -> datetime:
    recorded_at = observation.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_INPUT_INVALID,
            instance_path="/recorded_at",
            message="Assurance observation has no usable recorded_at timestamp.",
        )
    return normalize_verification_datetime(recorded_at, field_name="recorded_at")


def ensure_target_known_at_cutoff(
    assurance_record: Mapping[str, Any],
    *,
    knowledge_cutoff: datetime,
) -> None:
    if assurance_recorded_at(assurance_record) <= knowledge_cutoff:
        return
    assurance_id = assurance_record.get("assurance_id")
    raise AssuranceVerificationError(
        code=ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF,
        instance_path="/recorded_at",
        message="Assurance record is not known at the supplied knowledge cutoff.",
        related_ids=(assurance_id,) if isinstance(assurance_id, str) else (),
    )


def validate_verification_policy(policy: Mapping[str, Any]) -> None:
    validator = build_openva_validator(VERIFICATION_POLICY_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(policy), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceVerificationError(
        code=ASSURANCE_VERIFICATION_POLICY_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Verification policy is invalid: {error.message}",
    )


def build_assurance_verification_policy(policy: Mapping[str, Any]) -> AssuranceVerificationPolicy:
    validate_verification_policy(policy)
    outcome_class_by_outcome: dict[str, str] = {}
    eligible = policy["eligible_observation_outcomes"]
    for outcome_class, outcomes in eligible.items():
        for outcome in outcomes:
            if outcome in outcome_class_by_outcome:
                raise AssuranceVerificationError(
                    code=ASSURANCE_VERIFICATION_POLICY_INVALID,
                    instance_path="/eligible_observation_outcomes",
                    message=f"Verification outcome {outcome!r} appears in multiple outcome classes.",
                    related_ids=(outcome,),
                )
            outcome_class_by_outcome[outcome] = outcome_class

    authority_tier_by_outcome: dict[str, str] = {}
    authority_order: list[str] = []
    for tier in policy["authority_tiers"]:
        tier_name = tier["tier"]
        authority_order.append(tier_name)
        for outcome in tier["outcomes"]:
            if outcome in authority_tier_by_outcome:
                raise AssuranceVerificationError(
                    code=ASSURANCE_VERIFICATION_POLICY_INVALID,
                    instance_path="/authority_tiers",
                    message=f"Verification outcome {outcome!r} appears in multiple authority tiers.",
                    related_ids=(outcome,),
                )
            if outcome not in outcome_class_by_outcome:
                raise AssuranceVerificationError(
                    code=ASSURANCE_VERIFICATION_POLICY_INVALID,
                    instance_path="/authority_tiers",
                    message=f"Authority tier outcome {outcome!r} has no outcome-class mapping.",
                    related_ids=(outcome,),
                )
            authority_tier_by_outcome[outcome] = tier_name

    return AssuranceVerificationPolicy(
        data=MappingProxyType(json_material(policy)),
        policy_id=policy["policy_id"],
        policy_version=policy["policy_version"],
        outcome_class_by_outcome=MappingProxyType(outcome_class_by_outcome),
        authority_tier_by_outcome=MappingProxyType(authority_tier_by_outcome),
        authority_order=tuple(authority_order),
    )


def verification_policy_identity(
    policy: AssuranceVerificationPolicy | Mapping[str, Any],
) -> tuple[AssuranceVerificationPolicy, VerificationPolicyIdentity]:
    verification_policy = (
        policy if isinstance(policy, AssuranceVerificationPolicy) else build_assurance_verification_policy(policy)
    )
    policy_material = json_material(verification_policy.data)
    digest = sha256_bytes(canonical_json(policy_material))
    return verification_policy, VerificationPolicyIdentity(
        id=verification_policy.policy_id,
        version=verification_policy.policy_version,
        digest=digest,
    )


def admitted_observations(
    observations: Iterable[Mapping[str, Any]],
    *,
    knowledge_cutoff: datetime,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        sorted(
            (
                observation
                for observation in observations
                if observation_recorded_at(observation) <= knowledge_cutoff
            ),
            key=lambda observation: require_string(observation, "assurance_observation_id"),
        )
    )


def observation_semantic_diagnostics(
    *,
    assurance_record: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
) -> tuple[ValidationDiagnostic, ...]:
    target_id = require_string(assurance_record, "assurance_id")
    target_vendor_id = require_string(assurance_record, "vendor_id")
    repository = RepositorySnapshot(
        vendors=MappingProxyType({}),
        sources=MappingProxyType({}),
        source_observations=MappingProxyType({}),
        assurances=MappingProxyType(
            {
                target_id: RepositoryRecord.from_raw(
                    spec=ASSURANCE,
                    payload=assurance_record,
                )
            }
        ),
        assurance_observations=MappingProxyType({}),
        assurance_change_events=MappingProxyType({}),
    )

    diagnostics: list[ValidationDiagnostic] = []
    for observation in observations:
        observation_assurance_id = observation.get("assurance_id")
        observation_vendor_id = observation.get("vendor_id")
        if observation_assurance_id != target_id and observation_vendor_id != target_vendor_id:
            continue
        record = RepositoryRecord.from_raw(spec=ASSURANCE_OBSERVATION, payload=observation)
        diagnostics.extend(validate_assurance_observation_semantics(record, repository))
    return tuple(
        sorted(
            diagnostics,
            key=lambda diagnostic: (
                diagnostic.record_path or "",
                diagnostic.instance_path,
                diagnostic.code,
                diagnostic.record_kind,
                diagnostic.record_id,
                diagnostic.related_ids,
            ),
        )
    )


def validate_verification_output(state: Mapping[str, Any]) -> None:
    validator = build_openva_validator(VERIFICATION_STATE_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(state), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceVerificationError(
        code=ASSURANCE_VERIFICATION_OUTPUT_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Verification state output is invalid: {error.message}",
    )
