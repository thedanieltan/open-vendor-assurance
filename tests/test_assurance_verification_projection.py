from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_DATETIME_NAIVE
from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_POLICY_INVALID
from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF
from tools.openva.assurance_verification import AssuranceVerificationError
from tools.openva.assurance_verification import VerificationInputInvalidError
from tools.openva.assurance_verification import project_verification_state
from tools.openva.schema_registry import ROOT, build_openva_validator

VERIFICATION_ROOT = ROOT / "tests/fixtures/assurance/verification"
CONTRACT_ROOT = VERIFICATION_ROOT / "contracts"
POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
STATE_SCHEMA = ROOT / "schemas/openva/assurance-verification-state.schema.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policy() -> dict[str, Any]:
    policy = load_yaml(POLICY_PATH)
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


def project_case(case_name: str):
    expectation, assurance, observations = load_contract_case(case_name)
    return project_verification_state(
        assurance,
        observations,
        load_policy(),
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )


def assert_state_matches_expectation(actual: MappingLike, expected: dict[str, Any]) -> None:
    for field_name in (
        "schema_version",
        "assurance_id",
        "vendor_id",
        "effective_at",
        "knowledge_cutoff",
        "policy",
        "value",
        "determination",
        "reason_codes",
        "caused_by",
        "advisory_boundary",
    ):
        assert actual[field_name] == expected[field_name]
    assert isinstance(actual["input_digest"], str)
    build_openva_validator(STATE_SCHEMA).validate(dict(actual))


MappingLike = dict[str, Any]


@pytest.mark.parametrize(
    "case_name",
    [
        "no-observations",
        "one-supporting-observation",
        "one-contradicting-observation",
        "one-inconclusive-observation",
        "equal-authority-support",
        "equal-authority-conflict",
        "higher-authority-support-over-lower-contradiction",
        "higher-authority-contradiction-over-lower-support",
        "future-recorded-observation-excluded",
        "source-health-failure-does-not-affect-verification",
    ],
)
def test_verification_projection_matches_contract_fixture(case_name: str) -> None:
    expectation = load_json(CONTRACT_ROOT / case_name / "expectations.json")
    result = project_case(case_name)

    assert_state_matches_expectation(result.state, expectation["expected_state"])


def test_observation_recorded_exactly_at_cutoff_is_admitted() -> None:
    expectation, assurance, observations = load_contract_case("one-supporting-observation")
    observations[0]["recorded_at"] = "2026-06-30T00:00:00Z"

    result = project_verification_state(
        assurance,
        observations,
        load_policy(),
        expectation["request"]["effective_at"],
        "2026-06-30T00:00:00Z",
    )

    assert result.state["value"] == "confirmed"
    assert result.state["caused_by"]["assurance_observation_ids"] == ["supporting-observation"]


def test_target_recorded_after_cutoff_is_rejected() -> None:
    expectation, assurance, observations = load_contract_case("one-supporting-observation")
    assurance["recorded_at"] = "2026-07-01T00:00:00Z"

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_state(
            assurance,
            observations,
            load_policy(),
            expectation["request"]["effective_at"],
            expectation["request"]["knowledge_cutoff"],
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_TARGET_NOT_KNOWN_AT_CUTOFF


def test_unrelated_observations_are_excluded() -> None:
    expectation, assurance, _ = load_contract_case("no-observations")
    unrelated = {
        "schema_version": "0.1.1",
        "assurance_observation_id": "beta-conflict",
        "assurance_id": "beta-assurance",
        "vendor_id": "beta",
        "observed_at": "2026-01-20T00:00:00Z",
        "recorded_at": "2026-01-20T00:00:00Z",
        "source_observation_ids": ["beta-source-observation"],
        "evaluation": {
            "claim_presence": "present",
            "verification_outcome": "evidence_conflict",
            "reason_codes": ["conflicting_authoritative_evidence"],
        },
        "policy": {"id": "assurance-observation", "version": "0.1.0"},
        "advisory_boundary": "non_advisory",
    }

    result = project_verification_state(
        assurance,
        [unrelated],
        load_policy(),
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )

    assert result.state["value"] == "no_conclusion"
    assert result.state["caused_by"]["assurance_observation_ids"] == []


def test_effective_time_applicability_excludes_out_of_scope_observation() -> None:
    expectation, assurance, observations = load_contract_case("one-supporting-observation")
    observations[0]["observed_fields"] = {
        "stated_valid_from": "2026-01-01",
        "stated_valid_until": "2026-01-31",
    }

    result = project_verification_state(
        assurance,
        observations,
        load_policy(),
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )

    assert result.state["value"] == "no_conclusion"
    assert result.state["caused_by"]["assurance_observation_ids"] == []


def test_numeric_offset_datetimes_are_equivalent_to_utc() -> None:
    expectation, assurance, observations = load_contract_case("one-supporting-observation")

    utc_result = project_verification_state(
        assurance,
        observations,
        load_policy(),
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )
    offset_result = project_verification_state(
        assurance,
        observations,
        load_policy(),
        "2026-06-30T08:00:00+08:00",
        "2026-06-30T08:00:00+08:00",
    )

    assert dict(utc_result.state) == dict(offset_result.state)


@pytest.mark.parametrize(
    "effective_at,knowledge_cutoff",
    [
        ("2026-06-30T00:00:00", "2026-06-30T00:00:00Z"),
        ("2026-06-30T00:00:00Z", "2026-06-30T00:00:00"),
    ],
)
def test_naive_datetimes_are_rejected(effective_at: str, knowledge_cutoff: str) -> None:
    _, assurance, observations = load_contract_case("one-supporting-observation")

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_state(
            assurance,
            observations,
            load_policy(),
            effective_at,
            knowledge_cutoff,
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_DATETIME_NAIVE


def test_malformed_policy_is_rejected() -> None:
    expectation, assurance, observations = load_contract_case("one-supporting-observation")
    policy = load_policy()
    del policy["authority_tiers"]

    with pytest.raises(AssuranceVerificationError) as exc_info:
        project_verification_state(
            assurance,
            observations,
            policy,
            expectation["request"]["effective_at"],
            expectation["request"]["knowledge_cutoff"],
        )

    assert exc_info.value.code == ASSURANCE_VERIFICATION_POLICY_INVALID


def test_unknown_assurance_reference_fails_closed() -> None:
    expectation, assurance, _ = load_contract_case("no-observations")
    observation = load_yaml(
        VERIFICATION_ROOT
        / "semantic/invalid/unknown-assurance-reference/repository/assurance_observations/unknown-assurance-observation.yaml"
    )

    with pytest.raises(VerificationInputInvalidError) as exc_info:
        project_verification_state(
            assurance,
            [observation],
            load_policy(),
            expectation["request"]["effective_at"],
            expectation["request"]["knowledge_cutoff"],
        )

    assert [diagnostic.code for diagnostic in exc_info.value.diagnostics] == [
        "ASSURANCE_OBSERVATION_ASSURANCE_UNKNOWN"
    ]


def test_vendor_mismatch_fails_closed() -> None:
    expectation, assurance, _ = load_contract_case("no-observations")
    observation = load_yaml(
        VERIFICATION_ROOT
        / "semantic/invalid/observation-vendor-mismatch/repository/assurance_observations/mismatched-vendor-observation.yaml"
    )

    with pytest.raises(VerificationInputInvalidError) as exc_info:
        project_verification_state(
            assurance,
            [observation],
            load_policy(),
            expectation["request"]["effective_at"],
            expectation["request"]["knowledge_cutoff"],
        )

    assert [diagnostic.code for diagnostic in exc_info.value.diagnostics] == [
        "ASSURANCE_OBSERVATION_VENDOR_MISMATCH"
    ]


def test_input_order_does_not_change_result() -> None:
    expectation, assurance, observations = load_contract_case("equal-authority-support")

    result_a = project_verification_state(
        assurance,
        observations,
        load_policy(),
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )
    result_b = project_verification_state(
        assurance,
        list(reversed(observations)),
        load_policy(),
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )

    assert dict(result_a.state) == dict(result_b.state)


def test_inputs_are_not_mutated_and_repeated_calls_are_equal() -> None:
    expectation, assurance, observations = load_contract_case("one-supporting-observation")
    assurance_before = deepcopy(assurance)
    observations_before = deepcopy(observations)
    policy = load_policy()
    policy_before = deepcopy(policy)

    result_a = project_verification_state(
        assurance,
        observations,
        policy,
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )
    result_b = project_verification_state(
        assurance,
        observations,
        policy,
        expectation["request"]["effective_at"],
        expectation["request"]["knowledge_cutoff"],
    )

    assert assurance == assurance_before
    assert observations == observations_before
    assert policy == policy_before
    assert dict(result_a.state) == dict(result_b.state)
