from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from tools.openva.assurance_intelligence import INTELLIGENCE_AXES
from tools.openva.assurance_intelligence import INTELLIGENCE_PROFILE
from tools.openva.assurance_intelligence import project_assurance_intelligence
from tools.openva.assurance_intelligence_materialization import (
    materialize_assurance_intelligence,
    latest_intelligence_index_relative_path,
    latest_intelligence_projection_relative_path,
    load_latest_intelligence_projection,
    plan_due_assurance_intelligence_reevaluations,
    resolve_repo_path,
)
from tools.openva.assurance_projection import project_assurance
from tools.openva.assurance_projection_materialization import (
    latest_index_relative_path as lifecycle_latest_index_relative_path,
    latest_projection_relative_path as lifecycle_latest_projection_relative_path,
)
from tools.openva.assurance_verification import project_evidence_set_state
from tools.openva.assurance_verification import project_verification_freshness
from tools.openva.assurance_verification import project_verification_state
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator, load_schema

VERIFICATION_CONTRACT_ROOT = ROOT / "tests/fixtures/assurance/verification/contracts"
LIFECYCLE_POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
VERIFICATION_POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
FRESHNESS_POLICY_PATH = ROOT / "config/assurance-verification-freshness-policy.yaml"
EVIDENCE_POLICY_PATH = ROOT / "config/assurance-evidence-set-policy.yaml"
INTELLIGENCE_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-projection.schema.json"
INTELLIGENCE_INDEX_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-latest-index.schema.json"
CHANGE_EVENT_SCHEMA_PATH = ROOT / "schemas/openva/assurance-change-event.schema.json"

COMPLETE_FIELDS = {
    "stated_valid_from": "2026-01-10",
    "stated_valid_until": "2027-01-09",
    "stated_identifier": "ACME-ISO-2026",
    "stated_issuer_name": "Example Certification Body",
    "stated_scope_description": "Acme cloud service ISMS",
}


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def load_repository(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "vendors": {},
        "sources": {},
        "source_observations": {},
        "assurances": {},
        "assurance_observations": {},
    }
    id_fields = {
        "vendors": "vendor_id",
        "sources": "source_id",
        "source_observations": "observation_id",
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
    projection = project_assurance_intelligence(
        request or request_for(),
        repository,
        lifecycle_policy,
        verification_policy,
        freshness_policy,
        evidence_policy,
        projected_at,
    )
    build_openva_validator(INTELLIGENCE_SCHEMA_PATH).validate(projection)
    return dict(projection)


def materialize(
    tmp_path: Path,
    repository: dict[str, dict[str, dict[str, Any]]] | None = None,
    request: dict[str, Any] | None = None,
    *,
    projected_at: str = "2026-06-30T00:00:00Z",
    detected_at: str = "2026-06-30T00:00:00Z",
    mode: str = "current",
):
    lifecycle_policy, verification_policy, freshness_policy, evidence_policy = load_policies()
    return materialize_assurance_intelligence(
        request or request_for(),
        repository or complete_support_repository(),
        lifecycle_policy,
        verification_policy,
        freshness_policy,
        evidence_policy,
        projected_at,
        detected_at,
        tmp_path,
        mode,  # type: ignore[arg-type]
    )


def test_end_to_end_projection_matches_standalone_evaluators() -> None:
    repository = complete_support_repository()
    request = request_for()
    lifecycle_policy, verification_policy, freshness_policy, evidence_policy = load_policies()

    projection = project(repository, request)
    lifecycle = project_assurance(lifecycle_request(request), repository, lifecycle_policy, projection["projected_at"])
    target = repository["assurances"][request["assurance_id"]]
    observations = list(repository["assurance_observations"].values())
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

    assert projection["projection_profile"] == INTELLIGENCE_PROFILE
    assert projection["implemented_axes"] == list(INTELLIGENCE_AXES)
    assert list(projection["axes"]) == list(INTELLIGENCE_AXES)
    assert projection["axes"]["instrument_state"] == lifecycle["axes"]["instrument_state"]
    assert projection["axes"]["supersession_state"] == lifecycle["axes"]["supersession_state"]
    assert projection["axes"]["verification_state"] == dict(verification.state)
    assert projection["axes"]["verification_freshness"] == dict(freshness.freshness)
    assert projection["axes"]["evidence_set_state"] == dict(evidence.state)
    assert projection["next_reevaluation_at"] == "2026-08-30T00:00:00Z"


def test_materialization_acceptance_and_idempotence(tmp_path: Path) -> None:
    first = materialize(tmp_path)

    assert first.projection_written is True
    assert len(first.event_ids_written) == 5
    assert first.latest_index_updated is True
    assert [event["transition"]["axis"] for event in first.events] == list(INTELLIGENCE_AXES)
    build_openva_validator(INTELLIGENCE_SCHEMA_PATH).validate(first.projection)

    latest_projection_path = resolve_repo_path(
        tmp_path,
        latest_intelligence_projection_relative_path(first.assurance_id),
    )
    latest_index_path = resolve_repo_path(tmp_path, latest_intelligence_index_relative_path())
    latest_projection_bytes = latest_projection_path.read_bytes()
    latest_index_bytes = latest_index_path.read_bytes()

    second = materialize(tmp_path)
    assert second.projection_written is False
    assert second.event_ids_written == ()
    assert second.event_ids_already_present == ()
    assert second.latest_index_updated is False
    assert latest_projection_path.read_bytes() == latest_projection_bytes
    assert latest_index_path.read_bytes() == latest_index_bytes

    projected_only = materialize(
        tmp_path,
        projected_at="2026-07-01T00:00:00Z",
        detected_at="2026-07-01T00:00:00Z",
        mode="rebuild",
    )
    assert projected_only.semantic_no_op is True
    assert projected_only.writes_applied is False
    assert latest_projection_path.read_bytes() == latest_projection_bytes
    assert latest_index_path.read_bytes() == latest_index_bytes

    assert not resolve_repo_path(tmp_path, lifecycle_latest_projection_relative_path(first.assurance_id)).exists()
    assert not resolve_repo_path(tmp_path, lifecycle_latest_index_relative_path()).exists()


def test_state_and_non_state_rebuild_behaviour(tmp_path: Path) -> None:
    no_observation = materialize(tmp_path, repository=verification_case("no-observations"))
    complete = materialize(tmp_path, repository=complete_support_repository(), mode="rebuild")

    assert [event["transition"]["axis"] for event in complete.events] == [
        "verification_state",
        "verification_freshness",
        "evidence_set_state",
    ]
    assert complete.projection_written is True
    assert complete.latest_index_updated is True

    projection = load_latest_intelligence_projection(tmp_path, complete.assurance_id)
    assert projection is not None
    policy_only = deepcopy(projection)
    policy_only["policies"]["verification"]["digest"] = "sha256:" + "c" * 64

    from tools.openva.assurance_intelligence_materialization import IntelligenceMaterializationPlan
    from tools.openva.assurance_intelligence_materialization import apply_assurance_intelligence_materialization

    result = apply_assurance_intelligence_materialization(
        IntelligenceMaterializationPlan(
            mode="rebuild",
            projection=policy_only,
            previous_projection=projection,
            events=(),
            projection_changed=True,
            write_projection=True,
            write_events=False,
            update_latest_index=True,
        ),
        tmp_path,
    )

    assert no_observation.projection["axes"]["verification_state"]["value"] == "no_conclusion"
    assert result.projection_written is True
    assert result.event_ids_written == ()
    assert result.latest_index_updated is True


def test_source_observation_transport_metadata_does_not_affect_intelligence() -> None:
    repository = complete_support_repository()
    baseline = project(repository)
    changed = deepcopy(repository)
    source_observation = next(iter(changed["source_observations"].values()))
    source_observation["result"] = "fetch_failed"
    source_observation["http_status"] = 503
    source_observation["source_health"] = {"status": "unreachable"}
    source_observation["hashes"]["raw_sha256"] = "sha256:" + "c" * 64
    source_observation["hashes"]["normalized_text_sha256"] = "sha256:" + "d" * 64

    assert project(changed) == baseline


def test_historical_and_due_planning_boundaries(tmp_path: Path) -> None:
    historical = materialize(tmp_path, mode="historical")
    assert historical.writes_applied is False
    assert historical.events == ()
    assert list(tmp_path.rglob("*")) == []

    current = materialize(tmp_path)
    latest_index = load_json(resolve_repo_path(tmp_path, latest_intelligence_index_relative_path()))
    build_openva_validator(INTELLIGENCE_INDEX_SCHEMA_PATH).validate(latest_index)

    before_due = plan_due_assurance_intelligence_reevaluations(latest_index, "2026-08-29T23:59:59Z")
    at_due = plan_due_assurance_intelligence_reevaluations(latest_index, str(current.projection["next_reevaluation_at"]))

    assert before_due == ()
    assert [candidate.assurance_id for candidate in at_due] == [current.assurance_id]


def test_lifecycle_profile_remains_two_axis() -> None:
    schema = load_schema(ROOT / "schemas/openva/assurance-projection.schema.json")

    assert schema["properties"]["projection_profile"]["const"] == "openva.assurance-lifecycle.v1"
    assert schema["properties"]["implemented_axes"]["prefixItems"] == [
        {"const": "instrument_state"},
        {"const": "supersession_state"},
    ]
    assert schema["properties"]["implemented_axes"]["maxItems"] == 2


def test_materialized_event_documents_validate(tmp_path: Path) -> None:
    result = materialize(tmp_path)
    for event_id in result.event_ids_written:
        event = load_yaml(resolve_repo_path(tmp_path, f"data/vendors/acme/assurance_changes/{event_id}.yaml"))
        build_openva_validator(CHANGE_EVENT_SCHEMA_PATH).validate(event)
