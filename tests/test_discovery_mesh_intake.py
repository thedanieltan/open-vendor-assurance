import json
from pathlib import Path

import pytest

from tools.openva.discovery_mesh_intake import (
    materialize_partition,
    partition_records,
    prepare_intake,
)


def _candidate(vendor_id: str, index: int, *, payload: str = "x") -> dict:
    candidate_id = f"{vendor_id}-privacy-{index:04d}"
    return {
        "vendor_id": vendor_id,
        "candidate_source_id": candidate_id,
        "source_type_candidate": "privacy_notice",
        "candidate_url": f"https://{vendor_id}.example/privacy/{index}",
        "evidence": {"payload": payload},
    }


def _action(candidate: dict) -> dict:
    vendor_id = candidate["vendor_id"]
    candidate_id = candidate["candidate_source_id"]
    return {
        "action": "promote_candidate_source_for_review",
        "vendor_id": vendor_id,
        "candidate_source_id": candidate_id,
        "path": (
            f"data/vendors/{vendor_id}/candidate_sources/"
            f"{candidate_id}.yaml"
        ),
        "requires_human_review": True,
    }


def _fixture(tmp_path: Path, vendor_counts: list[tuple[str, int]]) -> tuple[Path, Path, Path]:
    rows = []
    actions = []
    for vendor_id, count in vendor_counts:
        for index in range(count):
            candidate = _candidate(vendor_id, index)
            rows.append({"vendor_id": vendor_id, "candidate": candidate})
            actions.append(_action(candidate))
    artifact = tmp_path / "artifact"
    generated = artifact / "maintenance" / "generated"
    generated.mkdir(parents=True)
    for name in (
        "vendor-breadth-signal-ledger.json",
        "vendor-breadth-resolution-queue.json",
        "vendor-breadth-candidates.json",
        "vendor-breadth-provider-metrics.json",
    ):
        (generated / name).write_text('{"ok": true}\n', encoding="utf-8")
    plan = {
        "report_type": "promotion_plan",
        "actions": actions,
        "deferred_actions": [],
        "skipped_actions": [],
        "summary": {},
        "inputs": {},
        "posture": {
            "writes_canonical_sources": False,
            "writes_repository_state": False,
        },
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    candidate_ndjson = tmp_path / "candidates.ndjson"
    candidate_ndjson.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return artifact, plan_path, candidate_ndjson


def test_prepare_partitions_every_action_without_total_cap(tmp_path: Path) -> None:
    artifact, plan_path, candidate_ndjson = _fixture(
        tmp_path,
        [("alpha", 4), ("beta", 3), ("gamma", 2)],
    )
    output = tmp_path / "prepared"
    manifest = prepare_intake(
        artifact_root=artifact,
        candidate_ndjson_path=candidate_ndjson,
        promotion_plan_path=plan_path,
        output_dir=output,
        source_run_id="123",
        max_files=5,
        max_bytes=1_000_000,
    )

    assert manifest["summary"]["total_action_count"] == 9
    assert manifest["summary"]["source_partition_count"] == 3
    assert manifest["transaction_bounds"]["catalog_vendor_count_cap"] is None
    assert manifest["transaction_bounds"]["total_action_count_cap"] is None
    source_partitions = [
        row for row in manifest["partitions"] if row["kind"] == "source"
    ]
    assert sum(row["action_count"] for row in source_partitions) == 9
    candidate_paths = [
        path
        for row in source_partitions
        for path in row["paths"]
        if "/candidate_sources/" in path
    ]
    assert len(candidate_paths) == len(set(candidate_paths)) == 9
    assert all(row["action_count"] + 1 <= 5 for row in source_partitions)
    assert all(
        row["branch"].startswith("agent-discovery-mesh-intake-123-source-")
        for row in source_partitions
    )


def test_materialize_writes_only_the_selected_partition(tmp_path: Path) -> None:
    artifact, plan_path, candidate_ndjson = _fixture(
        tmp_path,
        [("alpha", 4), ("beta", 3)],
    )
    prepared = tmp_path / "prepared"
    manifest = prepare_intake(
        artifact_root=artifact,
        candidate_ndjson_path=candidate_ndjson,
        promotion_plan_path=plan_path,
        output_dir=prepared,
        source_run_id="456",
        max_files=4,
        max_bytes=1_000_000,
    )
    partition = next(
        row for row in manifest["partitions"] if row["kind"] == "source"
    )
    repository = tmp_path / "repository"
    materialize_partition(
        manifest_path=prepared / "manifest.json",
        partition_id=partition["partition_id"],
        candidate_ndjson_path=candidate_ndjson,
        prepared_root=prepared,
        repository_root=repository,
    )

    assert (repository / partition["promotion_plan_path"]).is_file()
    for path in partition["paths"]:
        assert (repository / path).is_file()
    all_candidate_files = list(repository.glob("data/vendors/*/candidate_sources/*.yaml"))
    assert len(all_candidate_files) == partition["action_count"]


def test_partition_identity_is_deterministic(tmp_path: Path) -> None:
    artifact, plan_path, candidate_ndjson = _fixture(
        tmp_path,
        [("beta", 3), ("alpha", 3)],
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["actions"] = list(reversed(plan["actions"]))
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    candidate_rows = candidate_ndjson.read_text(encoding="utf-8").splitlines()
    candidate_ndjson.write_text(
        "\n".join(reversed(candidate_rows)) + "\n",
        encoding="utf-8",
    )
    first = prepare_intake(
        artifact_root=artifact,
        candidate_ndjson_path=candidate_ndjson,
        promotion_plan_path=plan_path,
        output_dir=tmp_path / "one",
        source_run_id="9",
        max_files=4,
        max_bytes=1_000_000,
    )
    second = prepare_intake(
        artifact_root=artifact,
        candidate_ndjson_path=candidate_ndjson,
        promotion_plan_path=plan_path,
        output_dir=tmp_path / "two",
        source_run_id="9",
        max_files=4,
        max_bytes=1_000_000,
    )

    assert [
        (row["partition_id"], row["paths"])
        for row in first["partitions"]
    ] == [
        (row["partition_id"], row["paths"])
        for row in second["partitions"]
    ]


def test_prepare_fails_closed_when_plan_candidate_is_missing(tmp_path: Path) -> None:
    artifact, plan_path, candidate_ndjson = _fixture(
        tmp_path,
        [("alpha", 2)],
    )
    candidate_ndjson.write_text(
        candidate_ndjson.read_text(encoding="utf-8").splitlines()[0] + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="promotion candidates missing"):
        prepare_intake(
            artifact_root=artifact,
            candidate_ndjson_path=candidate_ndjson,
            promotion_plan_path=plan_path,
            output_dir=tmp_path / "prepared",
            source_run_id="10",
        )


def test_partition_records_rejects_a_single_oversized_candidate() -> None:
    from tools.openva.discovery_mesh_intake import ActionRecord

    record = ActionRecord(
        action={"action": "promote_candidate_source_for_review"},
        path="data/vendors/a/candidate_sources/a.yaml",
        vendor_id="a",
        candidate_id="a",
        candidate_bytes=101,
        action_bytes=1,
    )
    with pytest.raises(ValueError, match="single candidate exceeds"):
        partition_records([record], max_files=2, max_bytes=100)
