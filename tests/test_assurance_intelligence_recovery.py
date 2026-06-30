from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva import assurance_intelligence_materialization
from tools.openva.assurance_intelligence import ASSURANCE_INTELLIGENCE_DIFF_NON_MONOTONIC
from tools.openva.assurance_intelligence import ASSURANCE_INTELLIGENCE_POLICY_MISMATCH
from tools.openva.assurance_intelligence import ASSURANCE_INTELLIGENCE_TARGET_UNKNOWN
from tools.openva.assurance_intelligence import AssuranceIntelligenceError
from tools.openva.assurance_intelligence import diff_assurance_intelligence_projections
from tools.openva.assurance_intelligence_materialization import (
    ASSURANCE_INTELLIGENCE_INDEX_INVALID,
    ASSURANCE_INTELLIGENCE_LATEST_INVALID,
    AssuranceIntelligenceMaterializationError,
    IntelligenceMaterializationPlan,
    apply_assurance_intelligence_materialization,
    latest_intelligence_index_relative_path,
    latest_intelligence_projection_relative_path,
    load_latest_intelligence_index,
    load_latest_intelligence_projection,
    materialize_assurance_intelligence,
    resolve_repo_path,
)
from tools.openva.assurance_projection_materialization import ASSURANCE_CHANGE_EVENT_ID_COLLISION
from tools.openva.assurance_verification import ASSURANCE_VERIFICATION_INPUT_INVALID
from tools.openva.assurance_verification import AssuranceVerificationError
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT

VERIFICATION_CONTRACT_ROOT = ROOT / "tests/fixtures/assurance/verification/contracts"
LIFECYCLE_POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
VERIFICATION_POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
FRESHNESS_POLICY_PATH = ROOT / "config/assurance-verification-freshness-policy.yaml"
EVIDENCE_POLICY_PATH = ROOT / "config/assurance-evidence-set-policy.yaml"

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


def initial_plan() -> IntelligenceMaterializationPlan:
    projection = materialize(Path("unused"), mode="historical").projection
    events = tuple(diff_assurance_intelligence_projections(None, projection, "2026-06-30T00:00:00Z"))
    return IntelligenceMaterializationPlan(
        mode="current",
        projection=projection,
        previous_projection=None,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )


def test_clean_rebuild_from_canonical_inputs_preserves_events_and_recreates_latest(tmp_path: Path) -> None:
    first = materialize(tmp_path)
    projection_path = resolve_repo_path(tmp_path, latest_intelligence_projection_relative_path(first.assurance_id))
    index_path = resolve_repo_path(tmp_path, latest_intelligence_index_relative_path())
    event_paths = sorted((tmp_path / "data/vendors/acme/assurance_changes").glob("*.yaml"))
    event_bytes = {path.name: path.read_bytes() for path in event_paths}

    projection_path.unlink()
    index_path.unlink()

    rebuilt = materialize(tmp_path, mode="current")

    assert rebuilt.projection_written is True
    assert rebuilt.latest_index_updated is True
    assert rebuilt.event_ids_written == ()
    assert set(rebuilt.event_ids_already_present) == set(first.event_ids_written)
    assert load_latest_intelligence_projection(tmp_path, first.assurance_id) == first.projection
    assert load_latest_intelligence_index(tmp_path)["entries"][0]["assurance_id"] == first.assurance_id
    assert {path.name: path.read_bytes() for path in event_paths} == event_bytes


def test_malformed_latest_projection_and_index_fail_closed(tmp_path: Path) -> None:
    first = materialize(tmp_path)
    projection_path = resolve_repo_path(tmp_path, latest_intelligence_projection_relative_path(first.assurance_id))
    index_path = resolve_repo_path(tmp_path, latest_intelligence_index_relative_path())

    projection_path.write_text('{"not": "a projection"}\n', encoding="utf-8")
    with pytest.raises(AssuranceIntelligenceMaterializationError) as latest_error:
        load_latest_intelligence_projection(tmp_path, first.assurance_id)
    assert latest_error.value.code == ASSURANCE_INTELLIGENCE_LATEST_INVALID

    projection_path.write_text(json.dumps(first.projection, sort_keys=True), encoding="utf-8")
    index_path.write_text('{"not": "an index"}\n', encoding="utf-8")
    with pytest.raises(AssuranceIntelligenceMaterializationError) as index_error:
        load_latest_intelligence_index(tmp_path)
    assert index_error.value.code == ASSURANCE_INTELLIGENCE_INDEX_INVALID


def test_event_collision_and_partial_write_failures_do_not_update_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = initial_plan()
    first_event = plan.events[0]
    event_path = resolve_repo_path(
        tmp_path,
        f"data/vendors/acme/assurance_changes/{first_event['change_event_id']}.yaml",
    )
    event_path.parent.mkdir(parents=True, exist_ok=True)
    conflicting = deepcopy(first_event)
    conflicting["reason_code"] = "point_in_time_scope"
    event_path.write_text(yaml.safe_dump(conflicting, sort_keys=True), encoding="utf-8")

    with pytest.raises(AssuranceIntelligenceMaterializationError) as collision:
        apply_assurance_intelligence_materialization(plan, tmp_path)
    assert collision.value.code == ASSURANCE_CHANGE_EVENT_ID_COLLISION
    assert not resolve_repo_path(tmp_path, latest_intelligence_index_relative_path()).exists()

    event_path.unlink()
    original_atomic = assurance_intelligence_materialization.atomic_write_bytes

    def fail_event_write(path: Path, content: bytes) -> bool:
        if path.suffix == ".yaml":
            raise OSError("event write failed")
        return original_atomic(path, content)

    monkeypatch.setattr(assurance_intelligence_materialization, "atomic_write_bytes", fail_event_write)
    with pytest.raises(OSError):
        apply_assurance_intelligence_materialization(plan, tmp_path)
    assert not resolve_repo_path(tmp_path, latest_intelligence_index_relative_path()).exists()


def test_interrupted_states_converge_with_index_last_semantics(tmp_path: Path) -> None:
    plan = initial_plan()
    first_event = plan.events[0]
    event_path = resolve_repo_path(
        tmp_path,
        f"data/vendors/acme/assurance_changes/{first_event['change_event_id']}.yaml",
    )
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text(yaml.safe_dump(first_event, sort_keys=True), encoding="utf-8")

    event_only = apply_assurance_intelligence_materialization(plan, tmp_path)
    assert first_event["change_event_id"] in event_only.event_ids_already_present
    assert event_only.projection_written is True
    assert event_only.latest_index_updated is True

    index_path = resolve_repo_path(tmp_path, latest_intelligence_index_relative_path())
    index_path.unlink()
    no_index = apply_assurance_intelligence_materialization(plan, tmp_path)
    assert no_index.projection_written is False
    assert no_index.latest_index_updated is True


def test_invalid_inputs_and_backward_time_fail_closed(tmp_path: Path) -> None:
    bad_policy_request = request_for()
    bad_policy_request["policies"]["verification"]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(AssuranceIntelligenceError) as policy_error:
        materialize(tmp_path, request=bad_policy_request)
    assert policy_error.value.code == ASSURANCE_INTELLIGENCE_POLICY_MISMATCH

    missing_target = request_for("missing-assurance")
    with pytest.raises(AssuranceIntelligenceError) as missing_error:
        materialize(tmp_path, request=missing_target)
    assert missing_error.value.code == ASSURANCE_INTELLIGENCE_TARGET_UNKNOWN

    unknown_reference = complete_support_repository()
    next(iter(unknown_reference["assurance_observations"].values()))["assurance_id"] = "missing-assurance"
    with pytest.raises(AssuranceVerificationError) as reference_error:
        materialize(tmp_path, repository=unknown_reference)
    assert reference_error.value.code == ASSURANCE_VERIFICATION_INPUT_INVALID

    vendor_mismatch = complete_support_repository()
    next(iter(vendor_mismatch["assurance_observations"].values()))["vendor_id"] = "other-vendor"
    with pytest.raises(AssuranceVerificationError) as vendor_error:
        materialize(tmp_path, repository=vendor_mismatch)
    assert vendor_error.value.code == ASSURANCE_VERIFICATION_INPUT_INVALID

    first = materialize(tmp_path)
    backward_request = request_for(effective_at="2026-06-29T00:00:00Z")
    with pytest.raises(AssuranceIntelligenceError) as backward_error:
        materialize(tmp_path, request=backward_request, projected_at="2026-06-29T00:00:00Z")
    assert backward_error.value.code == ASSURANCE_INTELLIGENCE_DIFF_NON_MONOTONIC
    assert load_latest_intelligence_projection(tmp_path, first.assurance_id) == first.projection
