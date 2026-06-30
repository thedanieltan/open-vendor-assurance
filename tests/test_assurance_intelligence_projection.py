from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva.assurance_intelligence import ASSURANCE_INTELLIGENCE_POLICY_MISMATCH
from tools.openva.assurance_intelligence import INTELLIGENCE_AXES
from tools.openva.assurance_intelligence import INTELLIGENCE_PROFILE
from tools.openva.assurance_intelligence import AssuranceIntelligenceError
from tools.openva.assurance_intelligence import project_assurance_intelligence
from tools.openva.assurance_projection import ASSURANCE_PROJECTION_DATETIME_NAIVE
from tools.openva.assurance_projection import AssuranceProjectionError
from tools.openva.assurance_projection import json_material
from tools.openva.assurance_projection import project_assurance
from tools.openva.assurance_verification import project_evidence_set_state
from tools.openva.assurance_verification import project_verification_freshness
from tools.openva.assurance_verification import project_verification_state
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator, load_schema

VERIFICATION_CONTRACT_ROOT = ROOT / "tests/fixtures/assurance/verification/contracts"
PROJECTION_VALID_ROOT = ROOT / "tests/fixtures/assurance/projection/projection-valid"
LIFECYCLE_POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
VERIFICATION_POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
FRESHNESS_POLICY_PATH = ROOT / "config/assurance-verification-freshness-policy.yaml"
EVIDENCE_POLICY_PATH = ROOT / "config/assurance-evidence-set-policy.yaml"
INTELLIGENCE_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-projection.schema.json"

COMPLETE_FIELDS = {
    "stated_valid_from": "2026-01-10",
    "stated_valid_until": "2027-01-09",
    "stated_identifier": "ACME-ISO-2026",
    "stated_issuer_name": "Example Certification Body",
    "stated_scope_description": "Acme cloud service ISMS",
}


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policies() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    policies = tuple(
        load_yaml(path)
        for path in (
            LIFECYCLE_POLICY_PATH,
            VERIFICATION_POLICY_PATH,
            FRESHNESS_POLICY_PATH,
            EVIDENCE_POLICY_PATH,
        )
    )
    assert all(isinstance(policy, dict) for policy in policies)
    return policies


def policy_ref(policy: dict[str, Any]) -> dict[str, str]:
    return {
        "id": policy["policy_id"],
        "version": policy["policy_version"],
        "digest": sha256_bytes(canonical_json(policy)),
    }


def load_repository(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "vendors": {},
        "sources": {},
        "assurances": {},
        "assurance_observations": {},
    }
    id_fields = {
        "vendors": "vendor_id",
        "sources": "source_id",
        "assurances": "assurance_id",
        "assurance_observations": "assurance_observation_id",
    }
    for directory_name, id_field in id_fields.items():
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            assert isinstance(record, dict)
            records[directory_name][record[id_field]] = record
    return records


def request_for(
    assurance_id: str = "acme-iso-2026",
    *,
    effective_at: str = "2026-06-30T00:00:00Z",
    knowledge_cutoff: str = "2026-06-30T00:00:00Z",
) -> dict[str, Any]:
    lifecycle_policy, verification_policy, freshness_policy, evidence_policy = load_policies()
    return {
        "schema_version": "0.1.0",
        "assurance_id": assurance_id,
        "effective_at": effective_at,
        "knowledge_cutoff": knowledge_cutoff,
        "projection_profile": INTELLIGENCE_PROFILE,
        "policies": {
            "lifecycle": policy_ref(lifecycle_policy),
            "verification": policy_ref(verification_policy),
            "verification_freshness": policy_ref(freshness_policy),
            "evidence_set": policy_ref(evidence_policy),
        },
    }


def lifecycle_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "assurance_id": request["assurance_id"],
        "effective_at": request["effective_at"],
        "knowledge_cutoff": request["knowledge_cutoff"],
        "policy": request["policies"]["lifecycle"],
    }


def verification_case(case_name: str) -> dict[str, dict[str, dict[str, Any]]]:
    return load_repository(VERIFICATION_CONTRACT_ROOT / case_name / "repository")


def complete_support_repository() -> dict[str, dict[str, dict[str, Any]]]:
    repository = verification_case("one-supporting-observation")
    observation = next(iter(repository["assurance_observations"].values()))
    observation["observed_fields"] = deepcopy(COMPLETE_FIELDS)
    observation["observed_at"] = "2026-06-01T00:00:00Z"
    observation["recorded_at"] = "2026-06-01T00:00:00Z"
    return repository


def project(
    repository: dict[str, dict[str, dict[str, Any]]],
    request: dict[str, Any] | None = None,
    *,
    projected_at: str = "2026-06-30T00:00:00Z",
) -> dict[str, Any]:
    lifecycle_policy, verification_policy, freshness_policy, evidence_policy = load_policies()
    result = project_assurance_intelligence(
        request or request_for(),
        repository,
        lifecycle_policy,
        verification_policy,
        freshness_policy,
        evidence_policy,
        projected_at,
    )
    build_openva_validator(INTELLIGENCE_SCHEMA_PATH).validate(json_material(result))
    return dict(result)


def target_and_observations(repository: dict[str, dict[str, dict[str, Any]]], assurance_id: str):
    target = repository["assurances"][assurance_id]
    observations = list(repository["assurance_observations"].values())
    return target, observations


def test_exact_five_axis_profile_and_ordering() -> None:
    projection = project(complete_support_repository())

    assert projection["projection_profile"] == INTELLIGENCE_PROFILE
    assert projection["implemented_axes"] == list(INTELLIGENCE_AXES)
    assert list(projection["axes"]) == list(INTELLIGENCE_AXES)


def test_lifecycle_profile_remains_exactly_two_axis() -> None:
    schema = load_schema(ROOT / "schemas/openva/assurance-projection.schema.json")

    assert schema["properties"]["projection_profile"]["const"] == "openva.assurance-lifecycle.v1"
    assert schema["properties"]["implemented_axes"]["prefixItems"] == [
        {"const": "instrument_state"},
        {"const": "supersession_state"},
    ]
    assert schema["properties"]["implemented_axes"]["maxItems"] == 2


def test_all_axes_match_standalone_evaluator_outputs() -> None:
    repository = complete_support_repository()
    request = request_for()
    lifecycle_policy, verification_policy, freshness_policy, evidence_policy = load_policies()
    target, observations = target_and_observations(repository, request["assurance_id"])

    projection = project(repository, request)
    lifecycle = project_assurance(lifecycle_request(request), repository, lifecycle_policy, projection["projected_at"])
    verification = project_verification_state(
        target,
        observations,
        verification_policy,
        request["effective_at"],
        request["knowledge_cutoff"],
    )
    freshness = project_verification_freshness(
        target,
        observations,
        verification.state,
        freshness_policy,
        request["effective_at"],
        request["knowledge_cutoff"],
    )
    evidence = project_evidence_set_state(
        target,
        observations,
        verification_policy,
        evidence_policy,
        request["effective_at"],
        request["knowledge_cutoff"],
    )

    assert projection["axes"]["instrument_state"] == lifecycle["axes"]["instrument_state"]
    assert projection["axes"]["supersession_state"] == lifecycle["axes"]["supersession_state"]
    assert projection["axes"]["verification_state"] == dict(verification.state)
    assert projection["axes"]["verification_freshness"] == dict(freshness.freshness)
    assert projection["axes"]["evidence_set_state"] == dict(evidence.state)


def test_no_observations_produces_no_conclusion_no_basis_no_evidence() -> None:
    projection = project(verification_case("no-observations"))

    assert projection["axes"]["verification_state"]["value"] == "no_conclusion"
    assert projection["axes"]["verification_freshness"]["value"] == "no_basis"
    assert projection["axes"]["evidence_set_state"]["value"] == "no_evidence"


def test_supporting_complete_current_evidence() -> None:
    projection = project(complete_support_repository())

    assert projection["axes"]["verification_state"]["value"] == "confirmed"
    assert projection["axes"]["verification_freshness"]["value"] == "current"
    assert projection["axes"]["evidence_set_state"]["value"] == "complete"


def test_contradicting_evidence() -> None:
    repository = complete_support_repository()
    observation = next(iter(repository["assurance_observations"].values()))
    observation["evaluation"]["verification_outcome"] = "evidence_conflict"

    projection = project(repository)

    assert projection["axes"]["verification_state"]["value"] == "contradicted"
    assert projection["axes"]["evidence_set_state"]["value"] == "conflicted"


def test_conflicted_evidence_set() -> None:
    repository = complete_support_repository()
    support = next(iter(repository["assurance_observations"].values()))
    support["assurance_observation_id"] = "support"
    support["evaluation"]["verification_outcome"] = "evidence_consistent"
    conflict = deepcopy(support)
    conflict["assurance_observation_id"] = "conflict"
    conflict["evaluation"]["verification_outcome"] = "evidence_conflict"
    repository["assurance_observations"] = {"support": support, "conflict": conflict}

    projection = project(repository)

    assert projection["axes"]["verification_state"]["value"] == "inconclusive"
    assert projection["axes"]["evidence_set_state"]["value"] == "conflicted"


def test_stale_verification_basis() -> None:
    repository = complete_support_repository()
    observation = next(iter(repository["assurance_observations"].values()))
    observation["observed_at"] = "2026-01-01T00:00:00Z"

    projection = project(repository, request_for(effective_at="2026-07-01T00:00:00Z"))

    assert projection["axes"]["verification_freshness"]["value"] == "stale"


def test_future_recorded_observations_are_excluded() -> None:
    no_observation_repo = verification_case("no-observations")
    future_repo = deepcopy(no_observation_repo)
    future_observation = complete_support_repository()["assurance_observations"]["supporting-observation"]
    future_observation["recorded_at"] = "2026-07-01T00:00:00Z"
    future_repo["assurance_observations"] = {"future-observation": future_observation}

    no_observation_projection = project(no_observation_repo)
    future_projection = project(future_repo)

    assert future_projection["axes"]["verification_state"]["value"] == "no_conclusion"
    assert future_projection["input_digest"] == no_observation_projection["input_digest"]


def test_exact_policy_identities_and_mismatch_rejected() -> None:
    request = request_for()
    projection = project(complete_support_repository(), request)

    assert projection["policies"] == request["policies"]
    bad_request = deepcopy(request)
    bad_request["policies"]["verification"]["digest"] = "sha256:" + "0" * 64

    with pytest.raises(AssuranceIntelligenceError) as exc_info:
        project(complete_support_repository(), bad_request)

    assert exc_info.value.code == ASSURANCE_INTELLIGENCE_POLICY_MISMATCH


def test_input_digest_stable_under_observation_reordering() -> None:
    repository = complete_support_repository()
    observation = next(iter(repository["assurance_observations"].values()))
    observation["assurance_observation_id"] = "b-observation"
    second = deepcopy(observation)
    second["assurance_observation_id"] = "a-observation"
    repository["assurance_observations"] = {
        "b-observation": observation,
        "a-observation": second,
    }
    reordered = deepcopy(repository)
    reordered["assurance_observations"] = {
        "a-observation": second,
        "b-observation": observation,
    }

    assert project(repository)["input_digest"] == project(reordered)["input_digest"]


def test_semantic_observation_change_affects_digest() -> None:
    repository = complete_support_repository()
    changed = deepcopy(repository)
    observation = next(iter(changed["assurance_observations"].values()))
    observation["observed_fields"]["stated_scope_description"] = "Different structured scope"

    assert project(repository)["input_digest"] != project(changed)["input_digest"]


def test_different_projected_at_changes_only_projected_at() -> None:
    repository = complete_support_repository()
    first = project(repository, projected_at="2026-06-30T00:00:00Z")
    second = project(repository, projected_at="2026-07-01T00:00:00Z")

    assert first["projected_at"] != second["projected_at"]
    assert {k: v for k, v in first.items() if k != "projected_at"} == {
        k: v for k, v in second.items() if k != "projected_at"
    }


def test_earliest_reevaluation_boundary_selected() -> None:
    projection = project(complete_support_repository())

    assert projection["axes"]["instrument_state"]["interval_end_exclusive_at"] == "2027-01-10T00:00:00Z"
    assert projection["axes"]["verification_freshness"]["next_reevaluation_at"] == "2026-08-30T00:00:00Z"
    assert projection["next_reevaluation_at"] == "2026-08-30T00:00:00Z"


def test_null_aggregate_boundary() -> None:
    repository = load_repository(PROJECTION_VALID_ROOT / "expired-certification/repository")
    request = request_for(
        "acme-expired-cert",
        effective_at="2027-06-30T00:00:00Z",
        knowledge_cutoff="2027-06-30T00:00:00Z",
    )

    projection = project(repository, request, projected_at="2027-06-30T00:00:00Z")

    assert projection["axes"]["instrument_state"]["value"] == "expired"
    assert projection["axes"]["verification_freshness"]["next_reevaluation_at"] is None
    assert projection["next_reevaluation_at"] is None


def test_utc_offset_equivalence() -> None:
    repository = complete_support_repository()
    utc = project(
        deepcopy(repository),
        request_for(
            effective_at="2026-06-30T00:00:00Z",
            knowledge_cutoff="2026-06-30T00:00:00Z",
        ),
        projected_at="2026-06-30T00:00:00Z",
    )
    offset = project(
        deepcopy(repository),
        request_for(
            effective_at="2026-06-30T08:00:00+08:00",
            knowledge_cutoff="2026-06-30T08:00:00+08:00",
        ),
        projected_at="2026-06-30T08:00:00+08:00",
    )

    assert utc == offset


def test_naive_datetimes_are_rejected() -> None:
    request = request_for(effective_at="2026-06-30T00:00:00")

    with pytest.raises(AssuranceProjectionError) as exc_info:
        project(complete_support_repository(), request)

    assert exc_info.value.code == ASSURANCE_PROJECTION_DATETIME_NAIVE


def test_input_immutability_and_repeated_calls_are_deterministic() -> None:
    repository = complete_support_repository()
    request = request_for()
    original_repository = deepcopy(repository)
    original_request = deepcopy(request)

    first = project(repository, request)
    second = project(repository, request)

    assert repository == original_repository
    assert request == original_request
    assert first == second
