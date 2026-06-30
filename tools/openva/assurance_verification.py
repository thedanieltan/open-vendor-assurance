from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any

from tools.openva.assurance_projection import format_utc_datetime
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
ASSURANCE_VERIFICATION_FRESHNESS_DATETIME_NAIVE = "ASSURANCE_VERIFICATION_FRESHNESS_DATETIME_NAIVE"
ASSURANCE_VERIFICATION_FRESHNESS_POLICY_INVALID = "ASSURANCE_VERIFICATION_FRESHNESS_POLICY_INVALID"
ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID = "ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID"
ASSURANCE_VERIFICATION_FRESHNESS_OUTPUT_INVALID = "ASSURANCE_VERIFICATION_FRESHNESS_OUTPUT_INVALID"
ASSURANCE_EVIDENCE_SET_DATETIME_NAIVE = "ASSURANCE_EVIDENCE_SET_DATETIME_NAIVE"
ASSURANCE_EVIDENCE_SET_POLICY_INVALID = "ASSURANCE_EVIDENCE_SET_POLICY_INVALID"
ASSURANCE_EVIDENCE_SET_REQUIREMENT_MISSING = "ASSURANCE_EVIDENCE_SET_REQUIREMENT_MISSING"
ASSURANCE_EVIDENCE_SET_INPUT_INVALID = "ASSURANCE_EVIDENCE_SET_INPUT_INVALID"
ASSURANCE_EVIDENCE_SET_OUTPUT_INVALID = "ASSURANCE_EVIDENCE_SET_OUTPUT_INVALID"

VERIFICATION_POLICY_SCHEMA_PATH = ROOT / "schemas/openva/assurance-verification-policy.schema.json"
VERIFICATION_STATE_SCHEMA_PATH = ROOT / "schemas/openva/assurance-verification-state.schema.json"
VERIFICATION_FRESHNESS_POLICY_SCHEMA_PATH = (
    ROOT / "schemas/openva/assurance-verification-freshness-policy.schema.json"
)
VERIFICATION_FRESHNESS_SCHEMA_PATH = ROOT / "schemas/openva/assurance-verification-freshness.schema.json"
EVIDENCE_SET_POLICY_SCHEMA_PATH = ROOT / "schemas/openva/assurance-evidence-set-policy.schema.json"
EVIDENCE_SET_SCHEMA_PATH = ROOT / "schemas/openva/assurance-evidence-set.schema.json"


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


@dataclass(frozen=True, slots=True)
class VerificationFreshnessPolicyIdentity:
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
class AssuranceVerificationFreshnessPolicy:
    data: Mapping[str, Any]
    policy_id: str
    policy_version: str
    current_max_age_seconds: int
    stale_min_age_seconds: int
    aggregation: str
    effective_before_basis: str


@dataclass(frozen=True, slots=True)
class VerificationFreshnessResult:
    freshness: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EvidenceSetPolicyIdentity:
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
class AssuranceEvidenceSetPolicy:
    data: Mapping[str, Any]
    policy_id: str
    policy_version: str
    outcome_class_by_outcome: Mapping[str, str]
    dimension_by_field: Mapping[str, str]
    requirements_by_class: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class EvidenceSetStateResult:
    state: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ClassifiedEvidence:
    dimension: str
    outcome_class: str
    authority_tier: str
    observation: Mapping[str, Any]


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


def normalize_freshness_datetime(value: datetime | str, *, field_name: str) -> datetime:
    try:
        return normalize_verification_datetime(value, field_name=field_name)
    except AssuranceVerificationError as exc:
        if exc.code == ASSURANCE_VERIFICATION_DATETIME_NAIVE:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_FRESHNESS_DATETIME_NAIVE,
                instance_path=exc.instance_path,
                message=exc.args[0],
                related_ids=exc.related_ids,
            ) from exc
        raise


def normalize_evidence_set_datetime(value: datetime | str, *, field_name: str) -> datetime:
    try:
        return normalize_verification_datetime(value, field_name=field_name)
    except AssuranceVerificationError as exc:
        if exc.code == ASSURANCE_VERIFICATION_DATETIME_NAIVE:
            raise AssuranceVerificationError(
                code=ASSURANCE_EVIDENCE_SET_DATETIME_NAIVE,
                instance_path=exc.instance_path,
                message=exc.args[0],
                related_ids=exc.related_ids,
            ) from exc
        raise


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


def validate_verification_result_input(state: Mapping[str, Any]) -> None:
    validator = build_openva_validator(VERIFICATION_STATE_SCHEMA_PATH)
    material = json_material(state)
    errors = sorted(validator.iter_errors(material), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceVerificationError(
        code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Verification state input is invalid: {error.message}",
    )


def validate_verification_freshness_policy(policy: Mapping[str, Any]) -> None:
    validator = build_openva_validator(VERIFICATION_FRESHNESS_POLICY_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(policy), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceVerificationError(
        code=ASSURANCE_VERIFICATION_FRESHNESS_POLICY_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Verification freshness policy is invalid: {error.message}",
    )


def build_assurance_verification_freshness_policy(
    policy: Mapping[str, Any],
) -> AssuranceVerificationFreshnessPolicy:
    validate_verification_freshness_policy(policy)
    thresholds = policy["thresholds"]
    current_max_age_seconds = thresholds["current_max_age_seconds"]
    stale_min_age_seconds = thresholds["stale_min_age_seconds"]
    if current_max_age_seconds >= stale_min_age_seconds:
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_FRESHNESS_POLICY_INVALID,
            instance_path="/thresholds",
            message="Current freshness threshold must be lower than stale threshold.",
        )

    basis = policy["basis"]
    return AssuranceVerificationFreshnessPolicy(
        data=MappingProxyType(json_material(policy)),
        policy_id=policy["policy_id"],
        policy_version=policy["policy_version"],
        current_max_age_seconds=current_max_age_seconds,
        stale_min_age_seconds=stale_min_age_seconds,
        aggregation=basis["aggregation"],
        effective_before_basis=policy["effective_before_basis"],
    )


def verification_freshness_policy_identity(
    policy: AssuranceVerificationFreshnessPolicy | Mapping[str, Any],
) -> tuple[AssuranceVerificationFreshnessPolicy, VerificationFreshnessPolicyIdentity]:
    freshness_policy = (
        policy
        if isinstance(policy, AssuranceVerificationFreshnessPolicy)
        else build_assurance_verification_freshness_policy(policy)
    )
    policy_material = json_material(freshness_policy.data)
    digest = sha256_bytes(canonical_json(policy_material))
    return freshness_policy, VerificationFreshnessPolicyIdentity(
        id=freshness_policy.policy_id,
        version=freshness_policy.policy_version,
        digest=digest,
    )


def validate_verification_freshness_output(freshness: Mapping[str, Any]) -> None:
    validator = build_openva_validator(VERIFICATION_FRESHNESS_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(freshness), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceVerificationError(
        code=ASSURANCE_VERIFICATION_FRESHNESS_OUTPUT_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Verification freshness output is invalid: {error.message}",
    )


def validate_evidence_set_policy(policy: Mapping[str, Any]) -> None:
    validator = build_openva_validator(EVIDENCE_SET_POLICY_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(policy), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceVerificationError(
        code=ASSURANCE_EVIDENCE_SET_POLICY_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Evidence-set policy is invalid: {error.message}",
    )


def build_assurance_evidence_set_policy(policy: Mapping[str, Any]) -> AssuranceEvidenceSetPolicy:
    validate_evidence_set_policy(policy)
    outcome_class_by_outcome: dict[str, str] = {}
    eligible = policy["eligible_observation_outcomes"]
    for outcome_class, outcomes in eligible.items():
        for outcome in outcomes:
            if outcome in outcome_class_by_outcome:
                raise AssuranceVerificationError(
                    code=ASSURANCE_EVIDENCE_SET_POLICY_INVALID,
                    instance_path="/eligible_observation_outcomes",
                    message=f"Evidence outcome {outcome!r} appears in multiple outcome classes.",
                    related_ids=(outcome,),
                )
            outcome_class_by_outcome[outcome] = outcome_class

    requirements_by_class: dict[str, tuple[str, ...]] = {}
    for assurance_class, dimensions in policy["requirements_by_assurance_class"].items():
        if not dimensions:
            raise AssuranceVerificationError(
                code=ASSURANCE_EVIDENCE_SET_POLICY_INVALID,
                instance_path="/requirements_by_assurance_class",
                message=f"Assurance class {assurance_class!r} has no evidence requirements.",
                related_ids=(assurance_class,),
            )
        requirements_by_class[assurance_class] = tuple(sorted(dimensions))

    return AssuranceEvidenceSetPolicy(
        data=MappingProxyType(json_material(policy)),
        policy_id=policy["policy_id"],
        policy_version=policy["policy_version"],
        outcome_class_by_outcome=MappingProxyType(outcome_class_by_outcome),
        dimension_by_field=MappingProxyType(dict(policy["dimension_mapping"])),
        requirements_by_class=MappingProxyType(requirements_by_class),
    )


def evidence_set_policy_identity(
    policy: AssuranceEvidenceSetPolicy | Mapping[str, Any],
) -> tuple[AssuranceEvidenceSetPolicy, EvidenceSetPolicyIdentity]:
    evidence_policy = (
        policy if isinstance(policy, AssuranceEvidenceSetPolicy) else build_assurance_evidence_set_policy(policy)
    )
    policy_material = json_material(evidence_policy.data)
    digest = sha256_bytes(canonical_json(policy_material))
    return evidence_policy, EvidenceSetPolicyIdentity(
        id=evidence_policy.policy_id,
        version=evidence_policy.policy_version,
        digest=digest,
    )


def validate_evidence_set_output(state: Mapping[str, Any]) -> None:
    validator = build_openva_validator(EVIDENCE_SET_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(state), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    raise AssuranceVerificationError(
        code=ASSURANCE_EVIDENCE_SET_OUTPUT_INVALID,
        instance_path=validation_instance_path(error),
        message=f"Evidence-set output is invalid: {error.message}",
    )


def observation_applicable_to_effective_at(
    observation: Mapping[str, Any],
    *,
    effective_at: datetime,
) -> bool:
    observed_fields = observation.get("observed_fields")
    if not isinstance(observed_fields, Mapping):
        return True

    effective_date = effective_at.date()
    valid_from = parse_observed_date(observed_fields.get("stated_valid_from"))
    valid_until = parse_observed_date(observed_fields.get("stated_valid_until"))
    if valid_from is not None or valid_until is not None:
        if valid_from is not None and effective_date < valid_from:
            return False
        return not (valid_until is not None and effective_date > valid_until)

    as_of_date = parse_observed_date(observed_fields.get("stated_as_of_date"))
    if as_of_date is not None:
        return effective_date == as_of_date

    reporting_period = observed_fields.get("stated_reporting_period")
    if isinstance(reporting_period, Mapping):
        start = parse_observed_date(reporting_period.get("start"))
        end = parse_observed_date(reporting_period.get("end"))
        if start is not None and effective_date < start:
            return False
        return not (end is not None and effective_date > end)

    return True


def target_observations(
    observations: Iterable[Mapping[str, Any]],
    *,
    assurance_id: str,
    effective_at: datetime,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        observation
        for observation in observations
        if observation.get("assurance_id") == assurance_id
        and observation_applicable_to_effective_at(observation, effective_at=effective_at)
    )


def outcome_for_observation(observation: Mapping[str, Any]) -> str:
    evaluation = observation.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_INPUT_INVALID,
            instance_path="/evaluation",
            message="Assurance observation must define an evaluation object.",
        )
    outcome = evaluation.get("verification_outcome")
    if not isinstance(outcome, str):
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_INPUT_INVALID,
            instance_path="/evaluation/verification_outcome",
            message="Assurance observation must define string evaluation.verification_outcome.",
        )
    return outcome


def top_authority_observations(
    observations: Iterable[Mapping[str, Any]],
    *,
    policy: AssuranceVerificationPolicy,
) -> tuple[tuple[str, str, Mapping[str, Any]], ...]:
    classified: list[tuple[str, str, Mapping[str, Any]]] = []
    for observation in observations:
        outcome = outcome_for_observation(observation)
        outcome_class = policy.outcome_class_by_outcome.get(outcome)
        if outcome_class is None:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_INPUT_INVALID,
                instance_path="/evaluation/verification_outcome",
                message=f"Verification outcome {outcome!r} is not recognized by the supplied policy.",
                related_ids=(outcome,),
            )
        if outcome_class == "ignored":
            continue
        authority_tier = policy.authority_tier_by_outcome.get(outcome)
        if authority_tier is None:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_POLICY_INVALID,
                instance_path="/authority_tiers",
                message=f"Verification outcome {outcome!r} has no authority tier.",
                related_ids=(outcome,),
            )
        classified.append((authority_tier, outcome_class, observation))

    for tier_name in policy.authority_order:
        tier_observations = tuple(item for item in classified if item[0] == tier_name)
        if tier_observations:
            return tuple(
                sorted(
                    tier_observations,
                    key=lambda item: require_string(item[2], "assurance_observation_id"),
                )
            )
    return ()


def state_from_top_authority(
    top_observations: tuple[tuple[str, str, Mapping[str, Any]], ...],
) -> tuple[str, str, tuple[str, ...]]:
    if not top_observations:
        return (
            "no_conclusion",
            "no_admitted_verification_observation",
            (),
        )

    outcome_classes = {outcome_class for _, outcome_class, _ in top_observations}
    observation_ids = tuple(
        sorted(require_string(observation, "assurance_observation_id") for _, _, observation in top_observations)
    )
    if "inconclusive" in outcome_classes:
        return (
            "inconclusive",
            "decisive_observation_inconclusive",
            observation_ids,
        )
    if outcome_classes == {"support"}:
        return (
            "confirmed",
            "decisive_observations_support",
            observation_ids,
        )
    if outcome_classes == {"contradict"}:
        return (
            "contradicted",
            "decisive_observations_contradict",
            observation_ids,
        )
    if outcome_classes == {"support", "contradict"}:
        return (
            "inconclusive",
            "decisive_observations_conflict",
            observation_ids,
        )
    raise AssuranceVerificationError(
        code=ASSURANCE_VERIFICATION_INPUT_INVALID,
        instance_path="/assurance_observations",
        message="Verification observations did not map to a supported verification state.",
    )


def verification_input_digest(
    *,
    assurance_record: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    policy_identity: VerificationPolicyIdentity,
    effective_at: datetime,
    knowledge_cutoff: datetime,
) -> str:
    manifest = {
        "assurance_id": require_string(assurance_record, "assurance_id"),
        "effective_at": format_utc_datetime(effective_at),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff),
        "policy": policy_identity.as_mapping(),
        "assurance_record": json_material(assurance_record),
        "assurance_observations": [
            json_material(observation)
            for observation in sorted(
                observations,
                key=lambda observation: require_string(observation, "assurance_observation_id"),
            )
        ],
    }
    return sha256_bytes(canonical_json(manifest))


def verification_freshness_input_digest(
    *,
    assurance_record: Mapping[str, Any],
    decisive_observations: Iterable[Mapping[str, Any]],
    verification_result: Mapping[str, Any],
    policy_identity: VerificationFreshnessPolicyIdentity,
    effective_at: datetime,
    knowledge_cutoff: datetime,
) -> str:
    manifest = {
        "assurance_id": require_string(assurance_record, "assurance_id"),
        "effective_at": format_utc_datetime(effective_at),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff),
        "policy": policy_identity.as_mapping(),
        "assurance_record": json_material(assurance_record),
        "verification_result": json_material(verification_result),
        "decisive_assurance_observations": [
            json_material(observation)
            for observation in sorted(
                decisive_observations,
                key=lambda observation: require_string(observation, "assurance_observation_id"),
            )
        ],
    }
    return sha256_bytes(canonical_json(manifest))


def evidence_set_input_digest(
    *,
    assurance_record: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    verification_policy_identity_value: VerificationPolicyIdentity,
    evidence_policy_identity_value: EvidenceSetPolicyIdentity,
    effective_at: datetime,
    knowledge_cutoff: datetime,
) -> str:
    manifest = {
        "assurance_id": require_string(assurance_record, "assurance_id"),
        "effective_at": format_utc_datetime(effective_at),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff),
        "verification_policy": verification_policy_identity_value.as_mapping(),
        "evidence_set_policy": evidence_policy_identity_value.as_mapping(),
        "assurance_record": json_material(assurance_record),
        "assurance_observations": [
            json_material(observation)
            for observation in sorted(
                observations,
                key=lambda observation: require_string(observation, "assurance_observation_id"),
            )
        ],
    }
    return sha256_bytes(canonical_json(manifest))


def evidence_dimensions_for_observation(
    observation: Mapping[str, Any],
    *,
    policy: AssuranceEvidenceSetPolicy,
) -> tuple[str, ...]:
    observed_fields = observation.get("observed_fields")
    if not isinstance(observed_fields, Mapping):
        return ()

    dimensions: set[str] = set()
    for field_name, dimension in policy.dimension_by_field.items():
        value = observed_fields.get(field_name)
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        dimensions.add(dimension)
    return tuple(sorted(dimensions))


def classify_evidence_observations(
    *,
    observations: Iterable[Mapping[str, Any]],
    verification_policy: AssuranceVerificationPolicy,
    evidence_policy: AssuranceEvidenceSetPolicy,
) -> tuple[ClassifiedEvidence, ...]:
    classified: list[ClassifiedEvidence] = []
    for observation in observations:
        outcome = outcome_for_observation(observation)
        outcome_class = evidence_policy.outcome_class_by_outcome.get(outcome)
        if outcome_class is None:
            raise AssuranceVerificationError(
                code=ASSURANCE_EVIDENCE_SET_INPUT_INVALID,
                instance_path="/evaluation/verification_outcome",
                message=f"Evidence outcome {outcome!r} is not recognized by the supplied policy.",
                related_ids=(outcome,),
            )
        if outcome_class == "ignored":
            continue

        dimensions = evidence_dimensions_for_observation(observation, policy=evidence_policy)
        if not dimensions:
            raise AssuranceVerificationError(
                code=ASSURANCE_EVIDENCE_SET_INPUT_INVALID,
                instance_path="/observed_fields",
                message="Eligible evidence observation does not map to an evidence dimension.",
                related_ids=(require_string(observation, "assurance_observation_id"),),
            )

        authority_tier = verification_policy.authority_tier_by_outcome.get(outcome)
        if authority_tier is None:
            raise AssuranceVerificationError(
                code=ASSURANCE_EVIDENCE_SET_POLICY_INVALID,
                instance_path="/authority_tiers",
                message=f"Evidence outcome {outcome!r} has no verification authority tier.",
                related_ids=(outcome,),
            )
        for dimension in dimensions:
            classified.append(
                ClassifiedEvidence(
                    dimension=dimension,
                    outcome_class=outcome_class,
                    authority_tier=authority_tier,
                    observation=observation,
                )
            )
    return tuple(
        sorted(
            classified,
            key=lambda item: (
                item.dimension,
                verification_policy.authority_order.index(item.authority_tier),
                require_string(item.observation, "assurance_observation_id"),
                item.outcome_class,
            ),
        )
    )


def top_authority_evidence_by_dimension(
    classified: Iterable[ClassifiedEvidence],
    *,
    verification_policy: AssuranceVerificationPolicy,
) -> dict[str, tuple[ClassifiedEvidence, ...]]:
    grouped: dict[str, list[ClassifiedEvidence]] = {}
    for item in classified:
        grouped.setdefault(item.dimension, []).append(item)

    result: dict[str, tuple[ClassifiedEvidence, ...]] = {}
    for dimension, items in grouped.items():
        for tier_name in verification_policy.authority_order:
            top_items = [item for item in items if item.authority_tier == tier_name]
            if top_items:
                result[dimension] = tuple(
                    sorted(
                        top_items,
                        key=lambda item: require_string(item.observation, "assurance_observation_id"),
                    )
                )
                break
    return result


def observed_at_for_freshness(observation: Mapping[str, Any]) -> datetime:
    observed_at = observation.get("observed_at")
    if not isinstance(observed_at, str):
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
            instance_path="/observed_at",
            message="Decisive assurance observation has no usable observed_at timestamp.",
        )
    try:
        return normalize_freshness_datetime(observed_at, field_name="observed_at")
    except AssuranceVerificationError as exc:
        if exc.code == ASSURANCE_VERIFICATION_FRESHNESS_DATETIME_NAIVE:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
                instance_path="/observed_at",
                message="Decisive assurance observation has no usable observed_at timestamp.",
                related_ids=exc.related_ids,
            ) from exc
        raise


def decisive_observations_for_freshness(
    *,
    assurance_record: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    verification_result: Mapping[str, Any],
    knowledge_cutoff: datetime,
) -> tuple[Mapping[str, Any], ...]:
    validate_verification_result_input(verification_result)
    target_id = require_string(assurance_record, "assurance_id")
    target_vendor_id = require_string(assurance_record, "vendor_id")
    if verification_result["assurance_id"] != target_id or verification_result["vendor_id"] != target_vendor_id:
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
            instance_path="/verification_result",
            message="Verification result does not match the target assurance.",
            related_ids=(verification_result["assurance_id"], target_id),
        )

    caused_by = verification_result["caused_by"]
    decisive_ids = tuple(sorted(caused_by["assurance_observation_ids"]))
    if not decisive_ids:
        return ()

    by_id: dict[str, Mapping[str, Any]] = {}
    for observation in observations:
        observation_id = require_string(observation, "assurance_observation_id")
        by_id[observation_id] = observation

    decisive: list[Mapping[str, Any]] = []
    for observation_id in decisive_ids:
        observation = by_id.get(observation_id)
        if observation is None:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
                instance_path="/caused_by/assurance_observation_ids",
                message=f"Decisive assurance observation {observation_id!r} was not supplied.",
                related_ids=(observation_id,),
            )
        if observation.get("assurance_id") != target_id:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
                instance_path="/assurance_id",
                message="Decisive assurance observation does not reference the target assurance.",
                related_ids=(observation_id, target_id),
            )
        if observation.get("vendor_id") != target_vendor_id:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
                instance_path="/vendor_id",
                message="Decisive assurance observation vendor does not match the target assurance.",
                related_ids=(observation_id, target_vendor_id),
            )
        if observation_recorded_at(observation) > knowledge_cutoff:
            raise AssuranceVerificationError(
                code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
                instance_path="/recorded_at",
                message="Decisive assurance observation is not known at the supplied knowledge cutoff.",
                related_ids=(observation_id,),
            )
        decisive.append(observation)

    diagnostics = observation_semantic_diagnostics(
        assurance_record=assurance_record,
        observations=decisive,
    )
    if diagnostics:
        raise VerificationInputInvalidError(diagnostics)
    return tuple(sorted(decisive, key=lambda observation: require_string(observation, "assurance_observation_id")))


def project_verification_state(
    assurance_record: Mapping[str, Any],
    assurance_observations: Iterable[Mapping[str, Any]],
    policy: AssuranceVerificationPolicy | Mapping[str, Any],
    effective_at: datetime | str,
    knowledge_cutoff: datetime | str,
) -> VerificationStateResult:
    effective_at_utc = normalize_verification_datetime(effective_at, field_name="effective_at")
    knowledge_cutoff_utc = normalize_verification_datetime(knowledge_cutoff, field_name="knowledge_cutoff")
    verification_policy, policy_identity = verification_policy_identity(policy)

    ensure_target_known_at_cutoff(assurance_record, knowledge_cutoff=knowledge_cutoff_utc)
    admitted = admitted_observations(assurance_observations, knowledge_cutoff=knowledge_cutoff_utc)
    diagnostics = observation_semantic_diagnostics(
        assurance_record=assurance_record,
        observations=admitted,
    )
    if diagnostics:
        raise VerificationInputInvalidError(diagnostics)

    target_id = require_string(assurance_record, "assurance_id")
    relevant = target_observations(
        admitted,
        assurance_id=target_id,
        effective_at=effective_at_utc,
    )
    top_observations = top_authority_observations(relevant, policy=verification_policy)
    value, reason_code, decisive_observation_ids = state_from_top_authority(top_observations)
    state = {
        "schema_version": "0.1.0",
        "assurance_id": target_id,
        "vendor_id": require_string(assurance_record, "vendor_id"),
        "effective_at": format_utc_datetime(effective_at_utc),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff_utc),
        "policy": policy_identity.as_mapping(),
        "input_digest": verification_input_digest(
            assurance_record=assurance_record,
            observations=relevant,
            policy_identity=policy_identity,
            effective_at=effective_at_utc,
            knowledge_cutoff=knowledge_cutoff_utc,
        ),
        "value": value,
        "determination": "determined",
        "reason_codes": [reason_code],
        "caused_by": {
            "assurance_ids": [target_id],
            "assurance_observation_ids": list(decisive_observation_ids),
            "source_observation_ids": [],
        },
        "advisory_boundary": "non_advisory",
    }
    validate_verification_output(state)
    return VerificationStateResult(state=MappingProxyType(state))


def project_verification_freshness(
    assurance_record: Mapping[str, Any],
    assurance_observations: Iterable[Mapping[str, Any]],
    verification_result: Mapping[str, Any],
    policy: AssuranceVerificationFreshnessPolicy | Mapping[str, Any],
    effective_at: datetime | str,
    knowledge_cutoff: datetime | str,
) -> VerificationFreshnessResult:
    effective_at_utc = normalize_freshness_datetime(effective_at, field_name="effective_at")
    knowledge_cutoff_utc = normalize_freshness_datetime(knowledge_cutoff, field_name="knowledge_cutoff")
    freshness_policy, policy_identity = verification_freshness_policy_identity(policy)

    ensure_target_known_at_cutoff(assurance_record, knowledge_cutoff=knowledge_cutoff_utc)
    validate_verification_result_input(verification_result)
    verification_effective_at = normalize_freshness_datetime(
        verification_result["effective_at"],
        field_name="effective_at",
    )
    verification_knowledge_cutoff = normalize_freshness_datetime(
        verification_result["knowledge_cutoff"],
        field_name="knowledge_cutoff",
    )
    if verification_effective_at != effective_at_utc or verification_knowledge_cutoff != knowledge_cutoff_utc:
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
            instance_path="/verification_result",
            message="Verification result effective_at and knowledge_cutoff must match freshness inputs.",
        )

    observations = tuple(assurance_observations)
    decisive_observations = decisive_observations_for_freshness(
        assurance_record=assurance_record,
        observations=observations,
        verification_result=verification_result,
        knowledge_cutoff=knowledge_cutoff_utc,
    )
    target_id = require_string(assurance_record, "assurance_id")
    if not decisive_observations:
        freshness = {
            "schema_version": "0.1.0",
            "assurance_id": target_id,
            "vendor_id": require_string(assurance_record, "vendor_id"),
            "effective_at": format_utc_datetime(effective_at_utc),
            "knowledge_cutoff": format_utc_datetime(knowledge_cutoff_utc),
            "policy": policy_identity.as_mapping(),
            "input_digest": verification_freshness_input_digest(
                assurance_record=assurance_record,
                decisive_observations=(),
                verification_result=verification_result,
                policy_identity=policy_identity,
                effective_at=effective_at_utc,
                knowledge_cutoff=knowledge_cutoff_utc,
            ),
            "value": "no_basis",
            "determination": "determined",
            "reason_codes": ["no_decisive_verification_observation"],
            "basis_observed_at": None,
            "age_seconds": None,
            "next_reevaluation_at": None,
            "caused_by": {
                "assurance_ids": [target_id],
                "assurance_observation_ids": [],
                "source_observation_ids": [],
            },
            "advisory_boundary": "non_advisory",
        }
        validate_verification_freshness_output(freshness)
        return VerificationFreshnessResult(freshness=MappingProxyType(freshness))

    if freshness_policy.aggregation != "oldest_decisive_observed_at":
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_FRESHNESS_POLICY_INVALID,
            instance_path="/basis/aggregation",
            message="Unsupported verification freshness basis aggregation.",
            related_ids=(freshness_policy.aggregation,),
        )

    basis_observed_at = min(observed_at_for_freshness(observation) for observation in decisive_observations)
    if effective_at_utc < basis_observed_at:
        raise AssuranceVerificationError(
            code=ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID,
            instance_path="/effective_at",
            message="Freshness effective_at cannot precede the decisive observation basis.",
        )

    age_seconds = int((effective_at_utc - basis_observed_at).total_seconds())
    current_boundary = basis_observed_at + timedelta(seconds=freshness_policy.current_max_age_seconds)
    stale_boundary = basis_observed_at + timedelta(seconds=freshness_policy.stale_min_age_seconds)
    if age_seconds < freshness_policy.current_max_age_seconds:
        value = "current"
        reason_code = "decisive_basis_within_current_threshold"
        next_reevaluation_at = current_boundary
    elif age_seconds < freshness_policy.stale_min_age_seconds:
        value = "aging"
        reason_code = "decisive_basis_within_aging_threshold"
        next_reevaluation_at = stale_boundary
    else:
        value = "stale"
        reason_code = "decisive_basis_exceeds_stale_threshold"
        next_reevaluation_at = None

    decisive_observation_ids = tuple(
        sorted(require_string(observation, "assurance_observation_id") for observation in decisive_observations)
    )
    freshness = {
        "schema_version": "0.1.0",
        "assurance_id": target_id,
        "vendor_id": require_string(assurance_record, "vendor_id"),
        "effective_at": format_utc_datetime(effective_at_utc),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff_utc),
        "policy": policy_identity.as_mapping(),
        "input_digest": verification_freshness_input_digest(
            assurance_record=assurance_record,
            decisive_observations=decisive_observations,
            verification_result=verification_result,
            policy_identity=policy_identity,
            effective_at=effective_at_utc,
            knowledge_cutoff=knowledge_cutoff_utc,
        ),
        "value": value,
        "determination": "determined",
        "reason_codes": [reason_code],
        "basis_observed_at": format_utc_datetime(basis_observed_at),
        "age_seconds": age_seconds,
        "next_reevaluation_at": (
            format_utc_datetime(next_reevaluation_at) if next_reevaluation_at is not None else None
        ),
        "caused_by": {
            "assurance_ids": [target_id],
            "assurance_observation_ids": list(decisive_observation_ids),
            "source_observation_ids": [],
        },
        "advisory_boundary": "non_advisory",
    }
    validate_verification_freshness_output(freshness)
    return VerificationFreshnessResult(freshness=MappingProxyType(freshness))


def project_evidence_set_state(
    assurance_record: Mapping[str, Any],
    assurance_observations: Iterable[Mapping[str, Any]],
    verification_policy: AssuranceVerificationPolicy | Mapping[str, Any],
    evidence_set_policy: AssuranceEvidenceSetPolicy | Mapping[str, Any],
    effective_at: datetime | str,
    knowledge_cutoff: datetime | str,
) -> EvidenceSetStateResult:
    effective_at_utc = normalize_evidence_set_datetime(effective_at, field_name="effective_at")
    knowledge_cutoff_utc = normalize_evidence_set_datetime(knowledge_cutoff, field_name="knowledge_cutoff")
    verification_policy_value, verification_policy_identity_value = verification_policy_identity(verification_policy)
    evidence_policy_value, evidence_policy_identity_value = evidence_set_policy_identity(evidence_set_policy)

    ensure_target_known_at_cutoff(assurance_record, knowledge_cutoff=knowledge_cutoff_utc)
    target_id = require_string(assurance_record, "assurance_id")
    target_vendor_id = require_string(assurance_record, "vendor_id")
    assurance_class = require_string(assurance_record, "assurance_class")
    required_dimensions = evidence_policy_value.requirements_by_class.get(assurance_class)
    if required_dimensions is None:
        raise AssuranceVerificationError(
            code=ASSURANCE_EVIDENCE_SET_REQUIREMENT_MISSING,
            instance_path="/assurance_class",
            message=f"No evidence-set requirement rule exists for assurance class {assurance_class!r}.",
            related_ids=(assurance_class,),
        )

    admitted = admitted_observations(assurance_observations, knowledge_cutoff=knowledge_cutoff_utc)
    diagnostics = observation_semantic_diagnostics(
        assurance_record=assurance_record,
        observations=admitted,
    )
    if diagnostics:
        raise VerificationInputInvalidError(diagnostics)

    relevant = tuple(
        observation
        for observation in admitted
        if observation.get("assurance_id") == target_id
        and observation.get("vendor_id") == target_vendor_id
        and observation_applicable_to_effective_at(observation, effective_at=effective_at_utc)
    )
    classified = classify_evidence_observations(
        observations=relevant,
        verification_policy=verification_policy_value,
        evidence_policy=evidence_policy_value,
    )
    top_by_dimension = top_authority_evidence_by_dimension(
        classified,
        verification_policy=verification_policy_value,
    )

    satisfied_dimensions: set[str] = set()
    conflicted_dimensions: set[str] = set()
    material_observation_ids: set[str] = set()
    for dimension, top_items in top_by_dimension.items():
        outcome_classes = {item.outcome_class for item in top_items}
        if "creates_conflict" in outcome_classes:
            conflicted_dimensions.add(dimension)
        if "satisfies_presence" in outcome_classes and dimension not in conflicted_dimensions:
            satisfied_dimensions.add(dimension)
        for item in top_items:
            material_observation_ids.add(require_string(item.observation, "assurance_observation_id"))

    required_set = set(required_dimensions)
    missing_dimensions = required_set - satisfied_dimensions
    if not classified:
        value = "no_evidence"
        reason_code = "no_admitted_evidence"
        material_observation_ids = set()
    elif conflicted_dimensions:
        value = "conflicted"
        reason_code = "evidence_conflict_detected"
    elif missing_dimensions:
        value = "incomplete"
        reason_code = "required_evidence_missing"
    else:
        value = "complete"
        reason_code = "required_evidence_complete"

    state = {
        "schema_version": "0.1.0",
        "assurance_id": target_id,
        "vendor_id": target_vendor_id,
        "effective_at": format_utc_datetime(effective_at_utc),
        "knowledge_cutoff": format_utc_datetime(knowledge_cutoff_utc),
        "policy": evidence_policy_identity_value.as_mapping(),
        "input_digest": evidence_set_input_digest(
            assurance_record=assurance_record,
            observations=relevant,
            verification_policy_identity_value=verification_policy_identity_value,
            evidence_policy_identity_value=evidence_policy_identity_value,
            effective_at=effective_at_utc,
            knowledge_cutoff=knowledge_cutoff_utc,
        ),
        "value": value,
        "determination": "determined",
        "reason_codes": [reason_code],
        "required_dimensions": sorted(required_set),
        "satisfied_dimensions": sorted(satisfied_dimensions),
        "missing_dimensions": sorted(missing_dimensions),
        "conflicted_dimensions": sorted(conflicted_dimensions),
        "caused_by": {
            "assurance_ids": [target_id],
            "assurance_observation_ids": sorted(material_observation_ids),
            "source_observation_ids": [],
        },
        "advisory_boundary": "non_advisory",
    }
    validate_evidence_set_output(state)
    return EvidenceSetStateResult(state=MappingProxyType(state))
