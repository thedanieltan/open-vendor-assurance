from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva import assurance_intelligence_materialization
from tools.openva.assurance_intelligence import diff_assurance_intelligence_projections
from tools.openva.assurance_intelligence_materialization import (
    ASSURANCE_INTELLIGENCE_REEVALUATION_NOT_DUE,
    AssuranceIntelligenceMaterializationError,
    IntelligenceMaterializationPlan,
    apply_assurance_intelligence_materialization,
    latest_intelligence_index_relative_path,
    latest_intelligence_projection_relative_path,
    latest_index_document,
    materialize_assurance_intelligence,
    plan_due_assurance_intelligence_reevaluations,
    resolve_repo_path,
)
from tools.openva.assurance_projection_materialization import (
    ASSURANCE_CHANGE_EVENT_ID_COLLISION,
    latest_index_relative_path as lifecycle_latest_index_relative_path,
    latest_projection_relative_path as lifecycle_latest_projection_relative_path,
)
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator

VERIFICATION_CONTRACT_ROOT = ROOT / "tests/fixtures/assurance/verification/contracts"
LIFECYCLE_POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
VERIFICATION_POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
FRESHNESS_POLICY_PATH = ROOT / "config/assurance-verification-freshness-policy.yaml"
EVIDENCE_POLICY_PATH = ROOT / "config/assurance-evidence-set-policy.yaml"
INTELLIGENCE_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-projection.schema.json"
INTELLIGENCE_INDEX_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-latest-index.schema.json"
CHANGE_EVENT_SCHEMA_PATH = ROOT / "schemas/openva/assurance-change-event.schema.json"
SHA256_C = "sha256:" + "c" * 64

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
        "projection_profile": "openva.assurance-intelligence.v1",
        "policies": {
            "lifecycle": policy_ref(lifecycle_policy),
            "verification": policy_ref(verification_policy),
            "verification_freshness": policy_ref(freshness_policy),
            "evidence_set": policy_ref(evidence_policy),
        },
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


def verification_case(name: str) -> dict[str, dict[str, dict[str, Any]]]:
    return load_repository(VERIFICATION_CONTRACT_ROOT / name / "repository")


def complete_support_repository() -> dict[str, dict[str, dict[str, Any]]]:
    repository = verification_case("one-supporting-observation")
    observation = next(iter(repository["assurance_observations"].values()))
    observation["observed_fields"] = deepcopy(COMPLETE_FIELDS)
    observation["observed_at"] = "2026-06-01T00:00:00Z"
    observation["recorded_at"] = "2026-06-01T00:00:00Z"
    return repository


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


def projection_from(
    repository: dict[str, dict[str, dict[str, Any]]] | None = None,
    request: dict[str, Any] | None = None,
    *,
    projected_at: str = "2026-06-30T00:00:00Z",
) -> dict[str, Any]:
    result = materialize(Path("unused"), repository, request, projected_at=projected_at, mode="historical")
    return dict(result.projection)


def assert_schema_valid(path: Path, document: dict[str, Any]) -> None:
    build_openva_validator(path).validate(document)


def read_latest_projection(tmp_path: Path, assurance_id: str) -> dict[str, Any]:
    return load_json(resolve_repo_path(tmp_path, latest_intelligence_projection_relative_path(assurance_id)))


def read_latest_index(tmp_path: Path) -> dict[str, Any]:
    return load_json(resolve_repo_path(tmp_path, latest_intelligence_index_relative_path()))


def test_initial_materialization_writes_projection_five_events_and_unified_index(tmp_path: Path) -> None:
    result = materialize(tmp_path)

    assert result.mode == "current"
    assert result.projection_written is True
    assert len(result.event_ids_written) == 5
    assert result.latest_index_updated is True
    assert [event["transition"]["axis"] for event in result.events] == [
        "instrument_state",
        "supersession_state",
        "verification_state",
        "verification_freshness",
        "evidence_set_state",
    ]

    projection_path = resolve_repo_path(tmp_path, latest_intelligence_projection_relative_path(result.assurance_id))
    assert projection_path.exists()
    stored_projection = read_latest_projection(tmp_path, result.assurance_id)
    assert stored_projection == result.projection
    assert_schema_valid(INTELLIGENCE_SCHEMA_PATH, stored_projection)

    latest_index = read_latest_index(tmp_path)
    assert_schema_valid(INTELLIGENCE_INDEX_SCHEMA_PATH, latest_index)
    assert latest_index["entries"][0]["projection_ref"] == latest_intelligence_projection_relative_path(result.assurance_id)
    assert latest_index["entries"][0]["policies"] == result.projection["policies"]

    assert not resolve_repo_path(tmp_path, lifecycle_latest_projection_relative_path(result.assurance_id)).exists()
    assert not resolve_repo_path(tmp_path, lifecycle_latest_index_relative_path()).exists()

    for event_id in result.event_ids_written:
        event_path = resolve_repo_path(tmp_path, f"data/vendors/acme/assurance_changes/{event_id}.yaml")
        event = load_yaml(event_path)
        assert event["change_event_id"] == event_id
        assert_schema_valid(CHANGE_EVENT_SCHEMA_PATH, event)


def test_projected_at_only_rebuild_skips_all_writes(tmp_path: Path) -> None:
    first = materialize(tmp_path)
    projection_path = resolve_repo_path(tmp_path, latest_intelligence_projection_relative_path(first.assurance_id))
    index_path = resolve_repo_path(tmp_path, latest_intelligence_index_relative_path())
    projection_bytes = projection_path.read_bytes()
    index_bytes = index_path.read_bytes()

    result = materialize(
        tmp_path,
        projected_at="2026-07-01T00:00:00Z",
        detected_at="2026-07-01T00:00:00Z",
        mode="rebuild",
    )

    assert result.semantic_no_op is True
    assert result.projection_written is False
    assert result.latest_index_updated is False
    assert result.event_ids_written == ()
    assert projection_path.read_bytes() == projection_bytes
    assert index_path.read_bytes() == index_bytes


def test_policy_digest_only_rebuild_updates_projection_and_index_without_events(tmp_path: Path) -> None:
    first = materialize(tmp_path)
    changed_projection = deepcopy(first.projection)
    changed_projection["policies"]["verification"]["digest"] = SHA256_C
    plan = IntelligenceMaterializationPlan(
        mode="rebuild",
        projection=changed_projection,
        previous_projection=first.projection,
        events=(),
        projection_changed=True,
        write_projection=True,
        write_events=False,
        update_latest_index=True,
    )

    result = apply_assurance_intelligence_materialization(plan, tmp_path)

    assert result.projection_written is True
    assert result.latest_index_updated is True
    assert result.event_ids_written == ()
    assert read_latest_projection(tmp_path, result.assurance_id)["policies"]["verification"]["digest"] == SHA256_C
    assert read_latest_index(tmp_path)["entries"][0]["policies"]["verification"]["digest"] == SHA256_C


def test_state_changing_rebuild_persists_event_projection_and_index(tmp_path: Path) -> None:
    first = materialize(tmp_path, repository=verification_case("no-observations"))
    changed_projection = projection_from(complete_support_repository())
    events = tuple(
        diff_assurance_intelligence_projections(
            first.projection,
            changed_projection,
            "2026-06-30T00:00:00Z",
        )
    )
    plan = IntelligenceMaterializationPlan(
        mode="rebuild",
        projection=changed_projection,
        previous_projection=first.projection,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )

    result = apply_assurance_intelligence_materialization(plan, tmp_path)

    assert result.projection_written is True
    assert result.latest_index_updated is True
    assert [event["transition"]["axis"] for event in result.events] == [
        "verification_state",
        "verification_freshness",
        "evidence_set_state",
    ]


def test_reapplying_same_plan_is_idempotent(tmp_path: Path) -> None:
    projection = projection_from(complete_support_repository())
    events = tuple(diff_assurance_intelligence_projections(None, projection, "2026-06-30T00:00:00Z"))
    plan = IntelligenceMaterializationPlan(
        mode="current",
        projection=projection,
        previous_projection=None,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )

    first = apply_assurance_intelligence_materialization(plan, tmp_path)
    second = apply_assurance_intelligence_materialization(plan, tmp_path)

    assert len(first.event_ids_written) == 5
    assert second.event_ids_written == ()
    assert set(second.event_ids_already_present) == set(first.event_ids_written)
    assert second.projection_written is False
    assert second.latest_index_updated is False
    assert second.writes_applied is False


def test_event_id_collision_fails_closed(tmp_path: Path) -> None:
    projection = projection_from(complete_support_repository())
    event = diff_assurance_intelligence_projections(None, projection, "2026-06-30T00:00:00Z")[0]
    event_path = resolve_repo_path(tmp_path, f"data/vendors/acme/assurance_changes/{event['change_event_id']}.yaml")
    event_path.parent.mkdir(parents=True, exist_ok=True)
    bad_event = deepcopy(event)
    bad_event["reason_code"] = "point_in_time_scope"
    event_path.write_text(yaml.safe_dump(bad_event, sort_keys=True), encoding="utf-8")
    plan = IntelligenceMaterializationPlan(
        mode="current",
        projection=projection,
        previous_projection=None,
        events=(event,),
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )

    with pytest.raises(AssuranceIntelligenceMaterializationError) as exc_info:
        apply_assurance_intelligence_materialization(plan, tmp_path)

    assert exc_info.value.code == ASSURANCE_CHANGE_EVENT_ID_COLLISION


def test_historical_mode_has_no_side_effects(tmp_path: Path) -> None:
    result = materialize(tmp_path, mode="historical")

    assert result.mode == "historical"
    assert result.events == ()
    assert result.writes_applied is False
    assert list(tmp_path.rglob("*")) == []


def test_scheduled_reevaluation_due_guard(tmp_path: Path) -> None:
    first = materialize(tmp_path)
    early_request = request_for(effective_at="2026-08-29T00:00:00Z", knowledge_cutoff="2026-08-29T00:00:00Z")
    with pytest.raises(AssuranceIntelligenceMaterializationError) as exc_info:
        materialize(
            tmp_path,
            request=early_request,
            projected_at="2026-08-29T00:00:00Z",
            detected_at="2026-08-29T00:00:00Z",
            mode="scheduled_reevaluation",
        )
    assert exc_info.value.code == ASSURANCE_INTELLIGENCE_REEVALUATION_NOT_DUE

    due_request = request_for(
        effective_at=str(first.projection["next_reevaluation_at"]),
        knowledge_cutoff=str(first.projection["next_reevaluation_at"]),
    )
    result = materialize(
        tmp_path,
        request=due_request,
        projected_at=str(first.projection["next_reevaluation_at"]),
        detected_at=str(first.projection["next_reevaluation_at"]),
        mode="scheduled_reevaluation",
    )
    assert result.mode == "scheduled_reevaluation"


def test_due_planning_is_pure_and_sorted() -> None:
    index = latest_index_document(
        [
            {
                "assurance_id": "b-assurance",
                "vendor_id": "acme",
                "projection_profile": "openva.assurance-intelligence.v1",
                "projection_ref": "maintenance/assurance-intelligence/latest/b-/b-assurance.json",
                "policies": request_for()["policies"],
                "input_digest": "sha256:" + "b" * 64,
                "effective_at": "2026-06-30T00:00:00Z",
                "knowledge_cutoff": "2026-06-30T00:00:00Z",
                "next_reevaluation_at": "2026-07-02T00:00:00Z",
            },
            {
                "assurance_id": "a-assurance",
                "vendor_id": "acme",
                "projection_profile": "openva.assurance-intelligence.v1",
                "projection_ref": "maintenance/assurance-intelligence/latest/a-/a-assurance.json",
                "policies": request_for()["policies"],
                "input_digest": "sha256:" + "a" * 64,
                "effective_at": "2026-06-30T00:00:00Z",
                "knowledge_cutoff": "2026-06-30T00:00:00Z",
                "next_reevaluation_at": "2026-07-01T00:00:00Z",
            },
            {
                "assurance_id": "c-assurance",
                "vendor_id": "acme",
                "projection_profile": "openva.assurance-intelligence.v1",
                "projection_ref": "maintenance/assurance-intelligence/latest/c-/c-assurance.json",
                "policies": request_for()["policies"],
                "input_digest": "sha256:" + "c" * 64,
                "effective_at": "2026-06-30T00:00:00Z",
                "knowledge_cutoff": "2026-06-30T00:00:00Z",
                "next_reevaluation_at": None,
            },
        ]
    )
    before = deepcopy(index)

    candidates = plan_due_assurance_intelligence_reevaluations(index, "2026-07-02T00:00:00Z")

    assert [candidate.assurance_id for candidate in candidates] == ["a-assurance", "b-assurance"]
    assert index == before


def test_atomic_failure_prevents_latest_index_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projection = projection_from(complete_support_repository())
    events = tuple(diff_assurance_intelligence_projections(None, projection, "2026-06-30T00:00:00Z"))
    plan = IntelligenceMaterializationPlan(
        mode="current",
        projection=projection,
        previous_projection=None,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )
    original_atomic = assurance_intelligence_materialization.atomic_write_bytes

    def fail_projection(path: Path, content: bytes) -> bool:
        if path.name == f"{projection['assurance_id']}.json":
            raise OSError("projection write failed")
        return original_atomic(path, content)

    monkeypatch.setattr(assurance_intelligence_materialization, "atomic_write_bytes", fail_projection)

    with pytest.raises(OSError):
        apply_assurance_intelligence_materialization(plan, tmp_path)

    assert not resolve_repo_path(tmp_path, latest_intelligence_index_relative_path()).exists()


def test_index_document_is_sorted_by_assurance_id() -> None:
    request = request_for()
    document = latest_index_document(
        [
            {
                "assurance_id": "z-assurance",
                "vendor_id": "acme",
                "projection_profile": "openva.assurance-intelligence.v1",
                "projection_ref": "maintenance/assurance-intelligence/latest/z-/z-assurance.json",
                "policies": request["policies"],
                "input_digest": "sha256:" + "d" * 64,
                "effective_at": "2026-06-30T00:00:00Z",
                "knowledge_cutoff": "2026-06-30T00:00:00Z",
                "next_reevaluation_at": None,
            },
            {
                "assurance_id": "a-assurance",
                "vendor_id": "acme",
                "projection_profile": "openva.assurance-intelligence.v1",
                "projection_ref": "maintenance/assurance-intelligence/latest/a-/a-assurance.json",
                "policies": request["policies"],
                "input_digest": "sha256:" + "a" * 64,
                "effective_at": "2026-06-30T00:00:00Z",
                "knowledge_cutoff": "2026-06-30T00:00:00Z",
                "next_reevaluation_at": None,
            },
        ]
    )

    assert [entry["assurance_id"] for entry in document["entries"]] == ["a-assurance", "z-assurance"]
    assert_schema_valid(INTELLIGENCE_INDEX_SCHEMA_PATH, document)
