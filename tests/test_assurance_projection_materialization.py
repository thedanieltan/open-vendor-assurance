from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva import assurance_projection_materialization
from tools.openva.assurance_projection import (
    AssuranceProjectionError,
    diff_assurance_projections,
)
from tools.openva.assurance_projection_materialization import (
    ASSURANCE_CHANGE_EVENT_ID_COLLISION,
    ASSURANCE_PROJECTION_INDEX_INVALID,
    ASSURANCE_PROJECTION_LATEST_INVALID,
    ASSURANCE_PROJECTION_REEVALUATION_NOT_DUE,
    ASSURANCE_PROJECTION_STORAGE_PATH_INVALID,
    ProjectionMaterializationPlan,
    apply_assurance_projection_materialization,
    change_event_relative_path,
    latest_index_relative_path,
    latest_projection_relative_path,
    materialize_assurance_projection,
    plan_assurance_projection_materialization,
    plan_due_assurance_reevaluations,
    resolve_repo_path,
)
from tools.openva.schema_registry import ROOT, build_openva_validator

PROJECTION_ROOT = ROOT / "tests/fixtures/assurance/projection"
POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
LATEST_INDEX_SCHEMA = ROOT / "schemas/openva/assurance-projection-latest-index.schema.json"
PROJECTION_SCHEMA = ROOT / "schemas/openva/assurance-projection.schema.json"
CHANGE_EVENT_SCHEMA = ROOT / "schemas/openva/assurance-change-event.schema.json"
SHA256_B = "sha256:" + "b" * 64


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policy() -> dict[str, Any]:
    policy = load_yaml(POLICY_PATH)
    assert isinstance(policy, dict)
    return policy


def load_repository(repository_root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "vendors": {},
        "sources": {},
        "assurances": {},
    }
    id_field_by_dir = {
        "vendors": "vendor_id",
        "sources": "source_id",
        "assurances": "assurance_id",
    }
    for directory_name, id_field in id_field_by_dir.items():
        directory = repository_root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            assert isinstance(record, dict)
            records[directory_name][record[id_field]] = record
    return records


def expectation(name: str = "active-certification") -> dict[str, Any]:
    return load_json(PROJECTION_ROOT / "projection-valid" / name / "expectations.json")


def repository_for(name: str = "active-certification") -> dict[str, dict[str, dict[str, Any]]]:
    return load_repository(PROJECTION_ROOT / "projection-valid" / name / "repository")


def projection_for(name: str = "active-certification") -> dict[str, Any]:
    return deepcopy(expectation(name)["expected_projection"])


def assert_schema_valid(path: Path, document: dict[str, Any]) -> None:
    errors = sorted(build_openva_validator(path).iter_errors(document), key=lambda error: list(error.path))
    assert errors == []


def materialize_current(tmp_path: Path, name: str = "active-certification"):
    exp = expectation(name)
    return materialize_assurance_projection(
        exp["request"],
        repository_for(name),
        load_policy(),
        exp["expected_projection"]["projected_at"],
        exp["request"]["knowledge_cutoff"],
        tmp_path,
        "current",
    )


def read_latest_index(tmp_path: Path) -> dict[str, Any]:
    return load_json(resolve_repo_path(tmp_path, latest_index_relative_path()))


def read_latest_projection(tmp_path: Path, assurance_id: str) -> dict[str, Any]:
    return load_json(resolve_repo_path(tmp_path, latest_projection_relative_path(assurance_id)))


def test_initial_current_materialization_writes_projection_events_and_index(tmp_path: Path) -> None:
    result = materialize_current(tmp_path)

    assert result.mode == "current"
    assert result.projection_written is True
    assert len(result.event_ids_written) == 2
    assert result.latest_index_updated is True
    assert result.writes_applied is True
    assert [event["transition"]["axis"] for event in result.events] == [
        "instrument_state",
        "supersession_state",
    ]

    projection_path = resolve_repo_path(tmp_path, latest_projection_relative_path(result.assurance_id))
    assert projection_path.exists()
    stored_projection = read_latest_projection(tmp_path, result.assurance_id)
    assert stored_projection == result.projection
    assert_schema_valid(PROJECTION_SCHEMA, stored_projection)

    latest_index = read_latest_index(tmp_path)
    assert_schema_valid(LATEST_INDEX_SCHEMA, latest_index)
    assert latest_index["entries"] == [
        {
            "assurance_id": result.assurance_id,
            "vendor_id": result.projection["vendor_id"],
            "projection_profile": "openva.assurance-lifecycle.v1",
            "projection_ref": latest_projection_relative_path(result.assurance_id),
            "policy": result.projection["policy"],
            "input_digest": result.projection["input_digest"],
            "effective_at": result.projection["effective_at"],
            "knowledge_cutoff": result.projection["knowledge_cutoff"],
            "next_reevaluation_at": result.projection["next_reevaluation_at"],
        }
    ]

    for event_id in result.event_ids_written:
        event_path = resolve_repo_path(
            tmp_path,
            change_event_relative_path(result.projection["vendor_id"], event_id),
        )
        event = load_yaml(event_path)
        assert event["change_event_id"] == event_id
        assert_schema_valid(CHANGE_EVENT_SCHEMA, event)


def test_reapplying_same_plan_is_idempotent(tmp_path: Path) -> None:
    exp = expectation()
    projection = projection_for()
    plan = ProjectionMaterializationPlan(
        mode="current",
        projection=projection,
        previous_projection=None,
        events=tuple(diff_assurance_projections(None, projection, exp["request"]["knowledge_cutoff"])),
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )
    first = apply_assurance_projection_materialization(plan, tmp_path)
    second = apply_assurance_projection_materialization(plan, tmp_path)

    assert len(first.event_ids_written) == 2
    assert second.event_ids_written == ()
    assert set(second.event_ids_already_present) == set(first.event_ids_written)
    assert second.projection_written is False
    assert second.latest_index_updated is False
    assert second.writes_applied is False


def test_projected_at_only_rebuild_skips_all_writes(tmp_path: Path) -> None:
    first = materialize_current(tmp_path)
    projection_path = resolve_repo_path(tmp_path, latest_projection_relative_path(first.assurance_id))
    index_path = resolve_repo_path(tmp_path, latest_index_relative_path())
    projection_bytes = projection_path.read_bytes()
    index_bytes = index_path.read_bytes()

    exp = expectation()
    result = materialize_assurance_projection(
        exp["request"],
        repository_for(),
        load_policy(),
        "2026-07-02T00:00:00Z",
        "2026-07-02T00:00:00Z",
        tmp_path,
        "rebuild",
    )

    assert result.semantic_no_op is True
    assert result.projection_written is False
    assert result.latest_index_updated is False
    assert result.event_ids_written == ()
    assert projection_path.read_bytes() == projection_bytes
    assert index_path.read_bytes() == index_bytes


def test_policy_only_rebuild_updates_projection_and_index_without_events(tmp_path: Path) -> None:
    first = materialize_current(tmp_path)
    changed_projection = deepcopy(first.projection)
    changed_projection["policy"]["digest"] = SHA256_B
    plan = ProjectionMaterializationPlan(
        mode="rebuild",
        projection=changed_projection,
        previous_projection=first.projection,
        events=(),
        projection_changed=True,
        write_projection=True,
        write_events=False,
        update_latest_index=True,
    )

    result = apply_assurance_projection_materialization(plan, tmp_path)

    assert result.projection_written is True
    assert result.latest_index_updated is True
    assert result.event_ids_written == ()
    assert read_latest_projection(tmp_path, result.assurance_id)["policy"]["digest"] == SHA256_B
    assert read_latest_index(tmp_path)["entries"][0]["policy"]["digest"] == SHA256_B


def test_axis_state_change_rebuild_persists_event_projection_and_index(tmp_path: Path) -> None:
    first = materialize_current(tmp_path)
    changed_projection = deepcopy(first.projection)
    changed_projection["effective_at"] = "2027-01-10T00:00:00Z"
    changed_projection["axes"]["instrument_state"]["value"] = "expired"
    changed_projection["axes"]["instrument_state"]["reason_codes"] = ["stated_valid_until_passed"]
    changed_projection["next_reevaluation_at"] = None
    events = tuple(diff_assurance_projections(first.projection, changed_projection, "2027-01-10T00:00:00Z"))
    plan = ProjectionMaterializationPlan(
        mode="rebuild",
        projection=changed_projection,
        previous_projection=first.projection,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )

    result = apply_assurance_projection_materialization(plan, tmp_path)

    assert result.projection_written is True
    assert result.latest_index_updated is True
    assert result.event_ids_written == (events[0]["change_event_id"],)
    assert result.events[0]["transition"] == {
        "axis": "instrument_state",
        "from": "effective",
        "to": "expired",
    }


def test_historical_mode_is_side_effect_free(tmp_path: Path) -> None:
    exp = expectation()
    result = materialize_assurance_projection(
        exp["request"],
        repository_for(),
        load_policy(),
        exp["expected_projection"]["projected_at"],
        exp["request"]["knowledge_cutoff"],
        tmp_path,
        "historical",
    )

    assert result.mode == "historical"
    assert result.events == ()
    assert result.writes_applied is False
    assert not any(tmp_path.rglob("*"))


def test_scheduled_reevaluation_guard_and_due_execution(tmp_path: Path) -> None:
    materialize_current(tmp_path)
    exp = expectation()
    with pytest.raises(AssuranceProjectionError) as exc:
        materialize_assurance_projection(
            exp["request"],
            repository_for(),
            load_policy(),
            exp["expected_projection"]["projected_at"],
            "2026-06-30T00:00:00Z",
            tmp_path,
            "scheduled_reevaluation",
        )
    assert exc.value.code == ASSURANCE_PROJECTION_REEVALUATION_NOT_DUE

    due_request = deepcopy(exp["request"])
    due_request["effective_at"] = "2027-01-10T00:00:00Z"
    result = materialize_assurance_projection(
        due_request,
        repository_for(),
        load_policy(),
        "2027-01-10T00:00:00Z",
        "2027-01-10T00:00:00Z",
        tmp_path,
        "scheduled_reevaluation",
    )
    assert result.projection_written is True
    assert [event["transition"]["axis"] for event in result.events] == ["instrument_state"]


def test_scheduled_reevaluation_without_due_boundary_fails(tmp_path: Path) -> None:
    result = materialize_current(tmp_path, "expired-certification")
    assert result.projection["next_reevaluation_at"] is None
    exp = expectation("expired-certification")
    with pytest.raises(AssuranceProjectionError) as exc:
        materialize_assurance_projection(
            exp["request"],
            repository_for("expired-certification"),
            load_policy(),
            exp["expected_projection"]["projected_at"],
            exp["request"]["knowledge_cutoff"],
            tmp_path,
            "scheduled_reevaluation",
        )
    assert exc.value.code == ASSURANCE_PROJECTION_REEVALUATION_NOT_DUE


def test_due_reevaluation_planning_is_pure_and_sorted(tmp_path: Path) -> None:
    materialize_current(tmp_path, "active-certification")
    materialize_current(tmp_path, "future-certification")
    latest_index = read_latest_index(tmp_path)

    candidates = plan_due_assurance_reevaluations(latest_index, "2027-01-10T00:00:00Z")

    assert [(candidate.due_at, candidate.assurance_id) for candidate in candidates] == sorted(
        (candidate.due_at, candidate.assurance_id) for candidate in candidates
    )
    assert all(candidate.due_at <= "2027-01-10T00:00:00Z" for candidate in candidates)
    with pytest.raises(AssuranceProjectionError):
        plan_due_assurance_reevaluations(latest_index, "2027-01-10T00:00:00")


def test_event_id_collision_fails_closed_without_index_update(tmp_path: Path) -> None:
    exp = expectation()
    projection = projection_for()
    events = tuple(diff_assurance_projections(None, projection, exp["request"]["knowledge_cutoff"]))
    plan = ProjectionMaterializationPlan(
        mode="current",
        projection=projection,
        previous_projection=None,
        events=events,
        projection_changed=True,
        write_projection=True,
        write_events=True,
        update_latest_index=True,
    )
    apply_assurance_projection_materialization(plan, tmp_path)
    event_path = resolve_repo_path(
        tmp_path,
        change_event_relative_path(projection["vendor_id"], events[0]["change_event_id"]),
    )
    corrupted = load_yaml(event_path)
    corrupted["reason_code"] = "point_in_time_scope"
    event_path.write_text(yaml.safe_dump(corrupted, sort_keys=False), encoding="utf-8")
    index_before = resolve_repo_path(tmp_path, latest_index_relative_path()).read_bytes()

    with pytest.raises(AssuranceProjectionError) as exc:
        apply_assurance_projection_materialization(plan, tmp_path)

    assert exc.value.code == ASSURANCE_CHANGE_EVENT_ID_COLLISION
    assert resolve_repo_path(tmp_path, latest_index_relative_path()).read_bytes() == index_before


def test_malformed_stored_artifacts_fail_closed(tmp_path: Path) -> None:
    first = materialize_current(tmp_path)
    latest_path = resolve_repo_path(tmp_path, latest_projection_relative_path(first.assurance_id))
    latest_path.write_text("{\"bad\": true}\n", encoding="utf-8")
    exp = expectation()
    with pytest.raises(AssuranceProjectionError) as exc:
        materialize_assurance_projection(
            exp["request"],
            repository_for(),
            load_policy(),
            exp["expected_projection"]["projected_at"],
            exp["request"]["knowledge_cutoff"],
            tmp_path,
            "current",
        )
    assert exc.value.code == ASSURANCE_PROJECTION_LATEST_INVALID

    latest_path.unlink()
    index_path = resolve_repo_path(tmp_path, latest_index_relative_path())
    index_path.write_text("{\"bad\": true}\n", encoding="utf-8")
    plan = ProjectionMaterializationPlan(
        mode="current",
        projection=projection_for(),
        previous_projection=None,
        events=(),
        projection_changed=True,
        write_projection=True,
        write_events=False,
        update_latest_index=True,
    )
    with pytest.raises(AssuranceProjectionError) as exc:
        apply_assurance_projection_materialization(plan, tmp_path)
    assert exc.value.code == ASSURANCE_PROJECTION_INDEX_INVALID


def test_storage_paths_are_safe_and_deterministic(tmp_path: Path) -> None:
    assert latest_projection_relative_path("acme-cert") == "maintenance/assurance-projections/latest/ac/acme-cert.json"
    assert change_event_relative_path("acme", "assurance-change-" + "a" * 64).startswith(
        "data/vendors/acme/assurance_changes/"
    )
    with pytest.raises(AssuranceProjectionError) as exc:
        latest_projection_relative_path("../bad")
    assert exc.value.code == ASSURANCE_PROJECTION_STORAGE_PATH_INVALID
    with pytest.raises(AssuranceProjectionError):
        resolve_repo_path(tmp_path, "../escape.json")


def test_persistent_materialization_rejects_backward_latest_state(tmp_path: Path) -> None:
    materialize_current(tmp_path)
    exp = expectation()
    request = deepcopy(exp["request"])
    request["effective_at"] = "2026-06-29T00:00:00Z"
    with pytest.raises(AssuranceProjectionError):
        materialize_assurance_projection(
            request,
            repository_for(),
            load_policy(),
            exp["expected_projection"]["projected_at"],
            exp["request"]["knowledge_cutoff"],
            tmp_path,
            "current",
        )


def test_materializer_uses_project_and_diff_without_clock_network_or_scheduler() -> None:
    source = inspect.getsource(assurance_projection_materialization)
    assert "project_assurance(" in source
    assert "diff_assurance_projections(" in source
    forbidden = [
        ".now(",
        ".utcnow(",
        "time.time",
        "sleep(",
        "requests.",
        "httpx",
        "urlopen",
        "socket.",
        "scheduler",
        "webhook",
    ]
    assert [token for token in forbidden if token in source] == []


def test_planning_inputs_are_not_mutated() -> None:
    exp = expectation()
    request = deepcopy(exp["request"])
    repository = repository_for()
    policy = load_policy()
    before = (deepcopy(request), deepcopy(repository), deepcopy(policy))

    plan = plan_assurance_projection_materialization(
        request,
        repository,
        policy,
        exp["expected_projection"]["projected_at"],
        exp["request"]["knowledge_cutoff"],
        None,
        "current",
    )

    assert plan.events
    assert (request, repository, policy) == before
