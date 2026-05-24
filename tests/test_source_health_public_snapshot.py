from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.openva.source_health_public_snapshot import (
    build_source_health_public_snapshot,
    main,
)


def latest_row(
    vendor_id: str,
    source_id: str,
    status: str,
    bucket: str,
    *,
    source_url: str | None = None,
    http_status: int | None = 200,
    final_url: str | None = None,
) -> dict:
    url = source_url or f"https://{vendor_id}.example/{source_id}"
    return {
        "schema_version": "0.1.0",
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_url": url,
        "status": status,
        "status_bucket": bucket,
        "http_status": http_status,
        "final_url": final_url or url,
        "verified_at": "2026-05-24T08:30:00Z",
        "run_id": "26355961230",
        "observer": "source-verification-report",
        "observation_id": f"{vendor_id}-{source_id}-abc123",
    }


def latest_health(rows: list[dict]) -> dict:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-24T08:32:00Z",
        "report_type": "latest_source_health_index",
        "snapshot": {
            "generated_at": "2026-05-24T08:32:00Z",
            "source_observation_ledger_generated_at": "2026-05-24T08:31:00Z",
            "latest_verified_at": "2026-05-24T08:30:00Z",
            "latest_source_health_records": len(rows),
        },
        "summary": {"latest_source_health_records": len(rows)},
        "sources": rows,
    }


def test_builds_public_snapshot_from_latest_source_health():
    source = latest_row(
        "vendor-a",
        "vendor-a-dpa",
        "redirected",
        "healthy",
        final_url="https://vendor-a.example/legal/dpa",
    )

    snapshot = build_source_health_public_snapshot(
        latest_health([source]),
        generated_at="2026-05-24T08:33:00Z",
    )

    assert snapshot["schema_version"] == "0.1.0"
    assert snapshot["generated_at"] == "2026-05-24T08:33:00Z"
    assert snapshot["report_type"] == "source_health_public_snapshot"
    assert snapshot["source"] == "latest-source-health"
    assert snapshot["snapshot_type"] == "artifact_derived"
    assert snapshot["metadata"]["artifact_derived"] is True
    assert snapshot["metadata"]["network_fetch_performed"] is False
    assert snapshot["metadata"]["catalog_mutation_performed"] is False
    assert "not a permanent guarantee" in snapshot["metadata"]["snapshot_notice"]
    assert snapshot["summary"] == {
        "source_count": 1,
        "status_bucket_counts": {
            "healthy": 1,
            "warning": 0,
            "unavailable": 0,
            "ambiguous": 0,
        },
    }

    assert snapshot["health"] == [
        {
            "vendor_id": "vendor-a",
            "source_id": "vendor-a-dpa",
            "source_url": "https://vendor-a.example/vendor-a-dpa",
            "status": "redirected",
            "status_bucket": "healthy",
            "http_status": 200,
            "final_url": "https://vendor-a.example/legal/dpa",
            "verified_at": "2026-05-24T08:30:00Z",
            "run_id": "26355961230",
            "observer": "source-verification-report",
        }
    ]


def test_preserves_one_public_health_row_per_source():
    rows = [
        latest_row("vendor-a", "source-a", "ok", "healthy"),
        latest_row("vendor-a", "source-b", "possible_mismatch", "warning"),
        latest_row("vendor-b", "source-a", "gone", "unavailable", http_status=410),
        latest_row("vendor-c", "source-a", "bot_protected", "ambiguous", http_status=403),
    ]

    snapshot = build_source_health_public_snapshot(latest_health(rows), generated_at="2026-05-24T08:33:00Z")

    assert len(snapshot["health"]) == 4
    assert snapshot["summary"]["status_bucket_counts"] == {
        "healthy": 1,
        "warning": 1,
        "unavailable": 1,
        "ambiguous": 1,
    }


def test_rejects_invalid_latest_health_input():
    with pytest.raises(ValueError, match="latest_source_health_index"):
        build_source_health_public_snapshot({"report_type": "source_observation_ledger", "sources": []})


def test_rejects_unknown_status_bucket():
    row = latest_row("vendor-a", "source-a", "ok", "magic")

    with pytest.raises(ValueError, match="unknown status_bucket"):
        build_source_health_public_snapshot(latest_health([row]))


def test_rejects_self_certifying_fields():
    row = latest_row("vendor-a", "source-a", "ok", "healthy")
    row["eligible_for_automerge"] = True

    with pytest.raises(ValueError, match="self-certifying"):
        build_source_health_public_snapshot(latest_health([row]))


def test_snapshot_does_not_emit_self_certifying_fields():
    snapshot = build_source_health_public_snapshot(
        latest_health([latest_row("vendor-a", "source-a", "ok", "healthy")]),
        generated_at="2026-05-24T08:33:00Z",
    )
    text = json.dumps(snapshot, sort_keys=True)

    assert "eligible" not in text
    assert "eligible_for_automerge" not in text
    assert "tool_recommendation" not in text


def test_public_snapshot_cli_writes_json(tmp_path: Path):
    latest_path = tmp_path / "latest-source-health.json"
    output_path = tmp_path / "public" / "source-health-snapshot.json"
    latest_path.write_text(
        json.dumps(latest_health([latest_row("vendor-a", "source-a", "ok", "healthy")])) + "\n",
        encoding="utf-8",
    )

    assert main([
        "build",
        "--latest-source-health",
        str(latest_path),
        "--output",
        str(output_path),
    ]) == 0

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["report_type"] == "source_health_public_snapshot"
    assert output["summary"]["source_count"] == 1
