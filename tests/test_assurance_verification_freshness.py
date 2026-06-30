from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva.assurance_projection import json_material
from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_FRESHNESS_DATETIME_NAIVE
from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID
from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_FRESHNESS_POLICY_INVALID
from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF
from tools.openva.assurance_verification import AssuranceVerificationError
from tools.openva.assurance_verification import project_verification_freshness
from tools.openva.assurance_verification import project_verification_state
from tools.openva.schema_registry import ROOT, build_openva_validator

VERIFICATION_ROOT = ROOT / "tests/fixtures/assurance/verification"
CONTRACT_ROOT = VERIFICATION_ROOT / "contracts"
VERIFICATION_POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
FRESHNESS_POLICY_PATH = ROOT / "config/assurance-verification-freshness-policy.yaml"
FRESHNESS_SCHEMA = ROOT / "schemas/openva/assurance-verification-freshness.schema.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_verification_policy() -> dict[str, Any]:
    policy = load_yaml(VERIFICATION_POLICY_PATH)
    assert isinstance(policy, dict)
    return policy


def load_freshness_policy() -> dict[str, Any]:
    policy = load_yaml(FRESHNESS_POLICY_PATH)
    assert isinstance(policy, dict)
    return policy


def repository_records(repository_root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "assurances": {},
        "assurance_observations": {},
    }
    id_fields = {
        "assurances": "assurance_id",
        "assurance_observations": "assurance_observation_id",
    }
    for directory_name, id_field in id_fields.items():
        directory = repository_root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            assert isinstance(record, dict)
            records[directory_name][record[id_field]] = record
    return records


def load_contract_case(case_name: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    case_root = CONTRACT_ROOT / case_name
    expectation = load_json(case_root / "expectations.json")
    records = repository_records(case_root / "repository")
    assurance = records["assurances"][expectation["request"]["assurance_id"]]
    observations = list(records["assurance_observations"].values())
    return expectation, assurance, observations


def project_state_for_inputs(
    assurance: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    effective_at: str,
    knowledge_cutoff: str,
):
    return project_verification_state(
        assurance,
        observations,
        load_verification_policy(),
        effective_at,
        knowledge_cutoff,
    )


def project_freshness_for_inputs(
    assurance: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    effective_at: str,
    knowledge_cutoff: str,
):
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at=effective_at,
        knowledge_cutoff=knowledge_cutoff,
    )
    result = project_verification_freshness(
        assurance,
        observations,
        verification.state,
        load_freshness_policy(),
        effective_at,
        knowledge_cutoff,
    )
    build_openva_validator(FRESHNESS_SCHEMA).validate(json_material(result.freshness))
    return result, verification


def load_support_case() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _, assurance, observations = load_contract_case("one-supporting-observation")
    return deepcopy(assurance), deepcopy(observations)


def set_single_observation_times(
    observations: list[dict[str, Any]],
    *,
    observed_at: str,
    recorded_at: str | None = None,
) -> None:
    observations[0]["observed_at"] = observed_at
    observations[0]["recorded_at"] = recorded_at or observed_at


def assert_freshness(
    actual: dict[str, Any],
    *,
    value: str,
    reason: str,
    basis_observed_at: str | None,
    age_seconds: int | None,
    next_reevaluation_at: str | None,
    observation_ids: list[str],
) -> None:
    assert actual["value"] == value
    assert actual["determination"] == "determined"
    assert actual["reason_codes"] == [reason]
    assert actual["basis_observed_at"] == basis_observed_at
    assert actual["age_seconds"] == age_seconds
    assert actual["next_reevaluation_at"] == next_reevaluation_at
    assert actual["caused_by"]["assurance_ids"] == ["acme-iso-2026"]
    assert actual["caused_by"]["assurance_observation_ids"] == observation_ids
    assert actual["caused_by"]["source_observation_ids"] == []
    assert isinstance(actual["input_digest"], str)
    assert actual["policy"]["id"] == "openva-assurance-verification-freshness-policy"


def test_no_verification_basis_projects_no_basis() -> None:
    expectation, assurance, observations = load_contract_case("no-observations")

    result, _ = project_freshness_for_inputs(
        deepcopy(assurance),
        deepcopy(observations),
        effective_at=expectation["request"]["effective_at"],
        knowledge_cutoff=expectation["request"]["knowledge_cutoff"],
    )

    assert_freshness(
        dict(result.freshness),
        value="no_basis",
        reason="no_decisive_verification_observation",
        basis_observed_at=None,
        age_seconds=None,
        next_reevaluation_at=None,
        observation_ids=[],
    )


def test_current_basis() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(observations, observed_at="2026-06-01T00:00:00Z")

    result, _ = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    assert_freshness(
        dict(result.freshness),
        value="current",
        reason="decisive_basis_within_current_threshold",
        basis_observed_at="2026-06-01T00:00:00Z",
        age_seconds=2505600,
        next_reevaluation_at="2026-08-30T00:00:00Z",
        observation_ids=["supporting-observation"],
    )


def test_exact_current_to_aging_boundary() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(observations, observed_at="2026-01-01T00:00:00Z")

    result, _ = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-04-01T00:00:00Z",
        knowledge_cutoff="2026-04-01T00:00:00Z",
    )

    assert_freshness(
        dict(result.freshness),
        value="aging",
        reason="decisive_basis_within_aging_threshold",
        basis_observed_at="2026-01-01T00:00:00Z",
        age_seconds=7776000,
        next_reevaluation_at="2026-06-30T00:00:00Z",
        observation_ids=["supporting-observation"],
    )


def test_aging_basis() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(observations, observed_at="2026-01-01T00:00:00Z")

    result, _ = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-05-01T00:00:00Z",
        knowledge_cutoff="2026-05-01T00:00:00Z",
    )

    assert result.freshness["value"] == "aging"
    assert result.freshness["reason_codes"] == ["decisive_basis_within_aging_threshold"]
    assert result.freshness["next_reevaluation_at"] == "2026-06-30T00:00:00Z"


def test_exact_aging_to_stale_boundary() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(observations, observed_at="2026-01-01T00:00:00Z")

    result, _ = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    assert_freshness(
        dict(result.freshness),
        value="stale",
        reason="decisive_basis_exceeds_stale_threshold",
        basis_observed_at="2026-01-01T00:00:00Z",
        age_seconds=15552000,
        next_reevaluation_at=None,
        observation_ids=["supporting-observation"],
    )


def test_stale_basis() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(observations, observed_at="2026-01-01T00:00:00Z")

    result, _ = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-07-01T00:00:00Z",
        knowledge_cutoff="2026-07-01T00:00:00Z",
    )

    assert result.freshness["value"] == "stale"
    assert result.freshness["next_reevaluation_at"] is None


def test_multiple_decisive_observations_use_oldest_basis() -> None:
    _, assurance, observations = load_contract_case("equal-authority-support")
    observations = deepcopy(observations)
    for observation in observations:
        if observation["assurance_observation_id"] == "support-a":
            observation["observed_at"] = "2026-02-01T00:00:00Z"
        else:
            observation["observed_at"] = "2026-01-01T00:00:00Z"

    result, verification = project_freshness_for_inputs(
        deepcopy(assurance),
        observations,
        effective_at="2026-04-02T00:00:00Z",
        knowledge_cutoff="2026-04-02T00:00:00Z",
    )

    assert verification.state["caused_by"]["assurance_observation_ids"] == ["support-a", "support-b"]
    assert result.freshness["basis_observed_at"] == "2026-01-01T00:00:00Z"
    assert result.freshness["caused_by"]["assurance_observation_ids"] == ["support-a", "support-b"]
    assert result.freshness["value"] == "aging"


def test_lower_authority_observations_are_ignored_for_freshness() -> None:
    _, assurance, observations = load_contract_case("higher-authority-support-over-lower-contradiction")
    observations = deepcopy(observations)
    for observation in observations:
        if observation["assurance_observation_id"] == "authoritative-support":
            observation["observed_at"] = "2026-06-01T00:00:00Z"
        else:
            observation["observed_at"] = "2025-01-01T00:00:00Z"

    result, verification = project_freshness_for_inputs(
        deepcopy(assurance),
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    assert verification.state["caused_by"]["assurance_observation_ids"] == ["authoritative-support"]
    assert result.freshness["basis_observed_at"] == "2026-06-01T00:00:00Z"
    assert result.freshness["value"] == "current"


def test_future_recorded_observation_excluded_from_verification_basis() -> None:
    expectation, assurance, observations = load_contract_case("future-recorded-observation-excluded")

    result, verification = project_freshness_for_inputs(
        deepcopy(assurance),
        deepcopy(observations),
        effective_at=expectation["request"]["effective_at"],
        knowledge_cutoff=expectation["request"]["knowledge_cutoff"],
    )

    assert verification.state["value"] == "no_conclusion"
    assert result.freshness["value"] == "no_basis"
    assert result.freshness["caused_by"]["assurance_observation_ids"] == []


def test_decisive_observation_recorded_exactly_at_cutoff_is_admitted() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(
        observations,
        observed_at="2026-06-01T00:00:00Z",
        recorded_at="2026-06-30T00:00:00Z",
    )

    result, _ = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    assert result.freshness["value"] == "current"
    assert result.freshness["caused_by"]["assurance_observation_ids"] == ["supporting-observation"]


def test_decisive_observation_missing_from_supplied_collection_is_rejected() -> None:
    assurance, observations = load_support_case()
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_freshness(
            assurance,
            [],
            verification.state,
            load_freshness_policy(),
            "2026-06-30T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID


def test_verification_result_with_unrelated_observation_id_is_rejected() -> None:
    assurance, observations = load_support_case()
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )
    mutated_result = deepcopy(json_material(verification.state))
    mutated_result["caused_by"]["assurance_observation_ids"] = ["beta-observation"]
    unrelated = deepcopy(observations[0])
    unrelated["assurance_observation_id"] = "beta-observation"
    unrelated["assurance_id"] = "beta-assurance"

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_freshness(
            assurance,
            [unrelated],
            mutated_result,
            load_freshness_policy(),
            "2026-06-30T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID


def test_decisive_future_recorded_observation_is_rejected() -> None:
    assurance, observations = load_support_case()
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )
    observations[0]["recorded_at"] = "2026-07-01T00:00:00Z"

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_freshness(
            assurance,
            observations,
            verification.state,
            load_freshness_policy(),
            "2026-06-30T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID


def test_numeric_offset_inputs_are_equivalent_to_utc() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(observations, observed_at="2026-06-01T00:00:00Z")

    utc_result, _ = project_freshness_for_inputs(
        deepcopy(assurance),
        deepcopy(observations),
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )
    offset_result, _ = project_freshness_for_inputs(
        deepcopy(assurance),
        deepcopy(observations),
        effective_at="2026-06-30T08:00:00+08:00",
        knowledge_cutoff="2026-06-30T08:00:00+08:00",
    )

    assert dict(utc_result.freshness) == dict(offset_result.freshness)


@pytest.mark.parametrize(
    ("effective_at", "knowledge_cutoff"),
    [
        ("2026-06-30T00:00:00", "2026-06-30T00:00:00Z"),
        ("2026-06-30T00:00:00Z", "2026-06-30T00:00:00"),
    ],
)
def test_naive_datetimes_are_rejected(effective_at: str, knowledge_cutoff: str) -> None:
    assurance, observations = load_support_case()
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_freshness(
            assurance,
            observations,
            verification.state,
            load_freshness_policy(),
            effective_at,
            knowledge_cutoff,
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_FRESHNESS_DATETIME_NAIVE


def test_effective_time_before_basis_is_rejected_by_policy() -> None:
    assurance, observations = load_support_case()
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at="2026-01-19T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_freshness(
            assurance,
            observations,
            verification.state,
            load_freshness_policy(),
            "2026-01-19T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_FRESHNESS_INPUT_INVALID


def test_malformed_policy_is_rejected() -> None:
    assurance, observations = load_support_case()
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )
    policy = load_freshness_policy()
    del policy["thresholds"]

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_freshness(
            assurance,
            observations,
            verification.state,
            policy,
            "2026-06-30T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_FRESHNESS_POLICY_INVALID


def test_target_recorded_after_cutoff_is_rejected() -> None:
    assurance, observations = load_support_case()
    verification = project_state_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )
    assurance["recorded_at"] = "2026-07-01T00:00:00Z"

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_freshness(
            assurance,
            observations,
            verification.state,
            load_freshness_policy(),
            "2026-06-30T00:00:00Z",
            "2026-06-30T00:00:00Z",
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF


def test_effective_time_applicability_can_remove_basis() -> None:
    assurance, observations = load_support_case()
    observations[0]["observed_fields"] = {
        "stated_valid_from": "2026-01-01",
        "stated_valid_until": "2026-01-31",
    }

    result, verification = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )

    assert verification.state["value"] == "no_conclusion"
    assert result.freshness["value"] == "no_basis"


def test_inputs_are_immutable_and_results_are_deterministic() -> None:
    assurance, observations = load_support_case()
    set_single_observation_times(observations, observed_at="2026-06-01T00:00:00Z")
    original_assurance = deepcopy(assurance)
    original_observations = deepcopy(observations)
    policy = load_freshness_policy()
    original_policy = deepcopy(policy)

    first, verification = project_freshness_for_inputs(
        assurance,
        observations,
        effective_at="2026-06-30T00:00:00Z",
        knowledge_cutoff="2026-06-30T00:00:00Z",
    )
    second = project_verification_freshness(
        assurance,
        list(reversed(observations)),
        verification.state,
        policy,
        "2026-06-30T00:00:00Z",
        "2026-06-30T00:00:00Z",
    )

    assert assurance == original_assurance
    assert observations == original_observations
    assert policy == original_policy
    assert dict(first.freshness) == dict(second.freshness)
