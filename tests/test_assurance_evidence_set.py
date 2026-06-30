from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from tools.openva.assurance_projection import json_material
from tools.openva.assurance_verification import ASSURANCE_EVIDENCE_SET_DATETIME_NAIVE
from tools.openva.assurance_verification import ASSURANCE_EVIDENCE_SET_INPUT_INVALID
from tools.openva.assurance_verification import ASSURANCE_EVIDENCE_SET_POLICY_INVALID
from tools.openva.assurance_verification import ASSURANCE_EVIDENCE_SET_REQUIREMENT_MISSING
from tools.openva.assurance_verification import AssuranceEvidenceSetPolicy
from tools.openva.assurance_verification import AssuranceVerificationError
from tools.openva.assurance_verification import VerificationInputInvalidError
from tools.openva.assurance_verification import project_evidence_set_state
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator

CASE_ROOT = ROOT / "tests/fixtures/assurance/verification/contracts/one-supporting-observation"
VERIFICATION_POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
EVIDENCE_POLICY_PATH = ROOT / "config/assurance-evidence-set-policy.yaml"
EVIDENCE_SCHEMA_PATH = ROOT / "schemas/openva/assurance-evidence-set.schema.json"
EVIDENCE_POLICY_SCHEMA_PATH = ROOT / "schemas/openva/assurance-evidence-set-policy.schema.json"

COMPLETE_FIELDS = {
    "stated_valid_from": "2026-01-10",
    "stated_valid_until": "2027-01-09",
    "stated_identifier": "ACME-ISO-2026",
    "stated_issuer_name": "Example Certification Body",
    "stated_scope_description": "Acme cloud service ISMS",
}

REQUIRED_CERTIFICATION_DIMENSIONS = [
    "instrument_identifier",
    "issuer_identity",
    "scope_description",
    "validity_end",
    "validity_start",
]


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policies() -> tuple[dict[str, Any], dict[str, Any]]:
    verification_policy = load_yaml(VERIFICATION_POLICY_PATH)
    evidence_policy = load_yaml(EVIDENCE_POLICY_PATH)
    assert isinstance(verification_policy, dict)
    assert isinstance(evidence_policy, dict)
    return verification_policy, evidence_policy


def load_base_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    assurance = load_yaml(next((CASE_ROOT / "repository/assurances").glob("*.yaml")))
    observation = load_yaml(next((CASE_ROOT / "repository/assurance_observations").glob("*.yaml")))
    assert isinstance(assurance, dict)
    assert isinstance(observation, dict)
    return assurance, observation


def complete_observation(**overrides: Any) -> dict[str, Any]:
    _, observation = load_base_inputs()
    observation = deepcopy(observation)
    observation["observed_fields"] = deepcopy(COMPLETE_FIELDS)
    for key, value in overrides.items():
        observation[key] = value
    return observation


def evaluate(
    observations: list[dict[str, Any]],
    *,
    assurance: dict[str, Any] | None = None,
    effective_at: str = "2026-06-30T00:00:00Z",
    knowledge_cutoff: str = "2026-06-30T00:00:00Z",
    verification_policy: dict[str, Any] | None = None,
    evidence_policy: Any = None,
):
    base_assurance, _ = load_base_inputs()
    verification_policy_value, evidence_policy_value = load_policies()
    result = project_evidence_set_state(
        deepcopy(assurance or base_assurance),
        deepcopy(observations),
        deepcopy(verification_policy or verification_policy_value),
        evidence_policy if evidence_policy is not None else deepcopy(evidence_policy_value),
        effective_at,
        knowledge_cutoff,
    )
    build_openva_validator(EVIDENCE_SCHEMA_PATH).validate(json_material(result.state))
    return result


def assert_state(
    actual: dict[str, Any],
    *,
    value: str,
    reason: str,
    satisfied: list[str],
    missing: list[str],
    conflicted: list[str],
    observation_ids: list[str],
) -> None:
    assert actual["value"] == value
    assert actual["determination"] == "determined"
    assert actual["reason_codes"] == [reason]
    assert actual["required_dimensions"] == REQUIRED_CERTIFICATION_DIMENSIONS
    assert actual["satisfied_dimensions"] == satisfied
    assert actual["missing_dimensions"] == missing
    assert actual["conflicted_dimensions"] == conflicted
    assert actual["caused_by"]["assurance_ids"] == ["acme-iso-2026"]
    assert actual["caused_by"]["assurance_observation_ids"] == observation_ids
    assert actual["caused_by"]["source_observation_ids"] == []
    assert actual["policy"]["id"] == "openva-assurance-evidence-set-policy"
    assert isinstance(actual["input_digest"], str)


def test_evidence_set_policy_validates_and_digest_is_canonical() -> None:
    _, evidence_policy = load_policies()

    build_openva_validator(EVIDENCE_POLICY_SCHEMA_PATH).validate(evidence_policy)
    assert sha256_bytes(canonical_json(evidence_policy)) == (
        "sha256:07fc07edb700bcd7d6497c4e09ab44c8a1303d9d4b79d9ce3ec3edf893667f3f"
    )


def test_no_evidence() -> None:
    result = evaluate([])

    assert_state(
        dict(result.state),
        value="no_evidence",
        reason="no_admitted_evidence",
        satisfied=[],
        missing=REQUIRED_CERTIFICATION_DIMENSIONS,
        conflicted=[],
        observation_ids=[],
    )


def test_one_incomplete_dimension() -> None:
    observation = complete_observation(observed_fields={"stated_valid_from": "2026-01-10"})

    result = evaluate([observation])

    assert_state(
        dict(result.state),
        value="incomplete",
        reason="required_evidence_missing",
        satisfied=["validity_start"],
        missing=[
            "instrument_identifier",
            "issuer_identity",
            "scope_description",
            "validity_end",
        ],
        conflicted=[],
        observation_ids=["supporting-observation"],
    )


def test_multiple_missing_dimensions() -> None:
    observation = complete_observation(
        observed_fields={
            "stated_valid_from": "2026-01-10",
            "stated_valid_until": "2027-01-09",
        }
    )

    result = evaluate([observation])

    assert result.state["value"] == "incomplete"
    assert result.state["satisfied_dimensions"] == ["validity_end", "validity_start"]
    assert result.state["missing_dimensions"] == [
        "instrument_identifier",
        "issuer_identity",
        "scope_description",
    ]


def test_complete_evidence_set_and_exact_required_dimensions() -> None:
    result = evaluate([complete_observation()])

    assert_state(
        dict(result.state),
        value="complete",
        reason="required_evidence_complete",
        satisfied=REQUIRED_CERTIFICATION_DIMENSIONS,
        missing=[],
        conflicted=[],
        observation_ids=["supporting-observation"],
    )


def test_unresolved_conflict() -> None:
    conflict = complete_observation()
    conflict["evaluation"]["verification_outcome"] = "evidence_conflict"

    result = evaluate([conflict])

    assert result.state["value"] == "conflicted"
    assert result.state["reason_codes"] == ["evidence_conflict_detected"]
    assert result.state["conflicted_dimensions"] == REQUIRED_CERTIFICATION_DIMENSIONS


def test_conflict_precedence_over_incompleteness() -> None:
    conflict = complete_observation(
        observed_fields={"stated_scope_description": "Different observed scope"}
    )
    conflict["evaluation"]["verification_outcome"] = "evidence_conflict"

    result = evaluate([conflict])

    assert result.state["value"] == "conflicted"
    assert result.state["missing_dimensions"] == REQUIRED_CERTIFICATION_DIMENSIONS
    assert result.state["conflicted_dimensions"] == ["scope_description"]


def test_lower_authority_contradiction_does_not_override_higher_support() -> None:
    authoritative = complete_observation(assurance_observation_id="authoritative-support")
    lower = complete_observation(assurance_observation_id="lower-conflict")
    lower["evaluation"]["verification_outcome"] = "evidence_conflict"

    result = evaluate([lower, authoritative])

    assert result.state["value"] == "complete"
    assert result.state["conflicted_dimensions"] == []
    assert result.state["caused_by"]["assurance_observation_ids"] == ["authoritative-support"]


def test_equal_authority_conflict() -> None:
    support = complete_observation(assurance_observation_id="support")
    support["evaluation"]["verification_outcome"] = "evidence_consistent"
    conflict = complete_observation(assurance_observation_id="conflict")
    conflict["evaluation"]["verification_outcome"] = "evidence_conflict"

    result = evaluate([conflict, support])

    assert result.state["value"] == "conflicted"
    assert result.state["caused_by"]["assurance_observation_ids"] == ["conflict", "support"]


def test_ineligible_observations_are_ignored() -> None:
    observation = complete_observation()
    observation["evaluation"]["verification_outcome"] = "not_evaluated"

    result = evaluate([observation])

    assert result.state["value"] == "no_evidence"
    assert result.state["caused_by"]["assurance_observation_ids"] == []


def test_future_recorded_observations_are_excluded() -> None:
    observation = complete_observation(recorded_at="2026-07-01T00:00:00Z")

    result = evaluate([observation])

    assert result.state["value"] == "no_evidence"


def test_observation_recorded_exactly_at_cutoff_is_admitted() -> None:
    observation = complete_observation(recorded_at="2026-06-30T00:00:00Z")

    result = evaluate([observation])

    assert result.state["value"] == "complete"


def test_effective_time_filtering() -> None:
    observation = complete_observation()
    observation["observed_fields"]["stated_valid_until"] = "2026-01-31"

    result = evaluate([observation])

    assert result.state["value"] == "no_evidence"


def test_missing_assurance_policy_rule_fails_closed() -> None:
    _, evidence_policy = load_policies()
    bad_policy = AssuranceEvidenceSetPolicy(
        data=MappingProxyType(evidence_policy),
        policy_id=evidence_policy["policy_id"],
        policy_version=evidence_policy["policy_version"],
        outcome_class_by_outcome=MappingProxyType(
            {
                "authoritative_status_confirmed": "satisfies_presence",
                "evidence_conflict": "creates_conflict",
                "not_evaluated": "ignored",
            }
        ),
        dimension_by_field=MappingProxyType(dict(evidence_policy["dimension_mapping"])),
        requirements_by_class=MappingProxyType({}),
    )

    with pytest.raises(AssuranceVerificationError) as exc_info:
        evaluate([complete_observation()], evidence_policy=bad_policy)

    assert exc_info.value.code == ASSURANCE_EVIDENCE_SET_REQUIREMENT_MISSING


def test_unknown_assurance_reference_fails_closed() -> None:
    observation = complete_observation(assurance_id="ghost-assurance")

    with pytest.raises(VerificationInputInvalidError) as exc_info:
        evaluate([observation])

    assert [diagnostic.code for diagnostic in exc_info.value.diagnostics] == [
        "ASSURANCE_OBSERVATION_ASSURANCE_UNKNOWN"
    ]


def test_vendor_mismatch_fails_closed() -> None:
    observation = complete_observation(vendor_id="beta")

    with pytest.raises(VerificationInputInvalidError) as exc_info:
        evaluate([observation])

    assert [diagnostic.code for diagnostic in exc_info.value.diagnostics] == [
        "ASSURANCE_OBSERVATION_VENDOR_MISMATCH"
    ]


def test_eligible_observation_without_dimension_mapping_fails_closed() -> None:
    observation = complete_observation()
    observation["observed_fields"] = {}

    with pytest.raises(AssuranceVerificationError) as exc_info:
        evaluate([observation])

    assert exc_info.value.code == ASSURANCE_EVIDENCE_SET_INPUT_INVALID


def test_malformed_policy_is_rejected() -> None:
    _, evidence_policy = load_policies()
    del evidence_policy["dimension_mapping"]

    with pytest.raises(AssuranceVerificationError) as exc_info:
        evaluate([complete_observation()], evidence_policy=evidence_policy)

    assert exc_info.value.code == ASSURANCE_EVIDENCE_SET_POLICY_INVALID


def test_numeric_offset_inputs_are_equivalent_to_utc() -> None:
    observation = complete_observation()

    utc_result = evaluate(
        [deepcopy(observation)],
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )
    offset_result = evaluate(
        [deepcopy(observation)],
        effective_at="2026-06-30T08:00:00+08:00",
        knowledge_cutoff="2026-06-30T08:00:00+08:00",
    )

    assert dict(utc_result.state) == dict(offset_result.state)


@pytest.mark.parametrize(
    ("effective_at", "knowledge_cutoff"),
    [
        ("2026-06-30T00:00:00", "2026-06-30T00:00:00Z"),
        ("2026-06-30T00:00:00Z", "2026-06-30T00:00:00"),
    ],
)
def test_naive_datetimes_are_rejected(effective_at: str, knowledge_cutoff: str) -> None:
    with pytest.raises(AssuranceVerificationError) as exc_info:
        evaluate(
            [complete_observation()],
            effective_at=effective_at,
            knowledge_cutoff=knowledge_cutoff,
        )

    assert exc_info.value.code == ASSURANCE_EVIDENCE_SET_DATETIME_NAIVE


def test_input_immutability_and_determinism() -> None:
    observations = [
        complete_observation(assurance_observation_id="b-observation"),
        complete_observation(assurance_observation_id="a-observation"),
    ]
    assurance, _ = load_base_inputs()
    verification_policy, evidence_policy = load_policies()
    original_observations = deepcopy(observations)
    original_assurance = deepcopy(assurance)
    original_verification_policy = deepcopy(verification_policy)
    original_evidence_policy = deepcopy(evidence_policy)

    first = evaluate(
        observations,
        assurance=assurance,
        verification_policy=verification_policy,
        evidence_policy=evidence_policy,
    )
    second = evaluate(
        list(reversed(observations)),
        assurance=assurance,
        verification_policy=verification_policy,
        evidence_policy=evidence_policy,
    )

    assert observations == original_observations
    assert assurance == original_assurance
    assert verification_policy == original_verification_policy
    assert evidence_policy == original_evidence_policy
    assert dict(first.state) == dict(second.state)
