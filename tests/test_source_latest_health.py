from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.openva.source_latest_health import (
    build_latest_source_health_index,
    main,
    status_bucket,
)


def observation(
    vendor_id: str,
    source_id: str,
    source_url: str,
    status: str,
    *,
    verified_at: str = "2026-05-24T08:30:00Z",
    run_id: str = "26355961230",
    http_status: int | None = 200,
    final_url: str | None = None,
) -> dict:
    return {
        "schema_version": "0.1.0",
        "observation_id": f"{vendor_id}-{source_id}-{run_id}",
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_url": source_url,
        "status": status,
        "http_status": http_status,
        "final_url": final_url or source_url,
        "verified_at": verified_at,
        "run_id": run_id,
        "observer": "source-verification-report",
    }


def ledger(rows: list[dict]) -> dict:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-24T08:31:00Z",
        "report_type": "source_observation_ledger",
        "summary": {"observation_records": len(rows)},
        "observations": rows,
    }


def test_status_bucket_mapping_is_conservative():
    assert status_bucket("ok") == "healthy"
    assert status_bucket("redirected") == "healthy"
    assert status_bucket("not_found") == "unavailable"
    assert status_bucket("gone") == "unavailable"
    assert status_bucket("possible_mismatch") == "warning"
    assert status_bucket("homepage_or_generic_redirect") == "warning"
    assert status_bucket("suspect_inferred_url") == "warning"
    assert status_bucket("bot_protected") == "ambiguous"
    assert status_bucket("forbidden_unknown") == "ambiguous"
    assert status_bucket("gated_or_login_required") == "ambiguous"
    assert status_bucket("rate_limited") == "ambiguous"
    assert status_bucket("new_future_status") == "ambiguous"


def test_builds_one_latest_health_row_per_source_identity():
    older = observation(
        "vendor-a",
        "vendor-a-dpa",
        "https://vendor-a.example/dpa",
        "not_found",
        verified_at="2026-05-23T08:30:00Z",
        run_id="run-1",
        http_status=404,
    )
    newer = observation(
        "vendor-a",
        "vendor-a-dpa",
        "https://vendor-a.example/dpa",
        "ok",
        verified_at="2026-05-24T08:30:00Z",
        run_id="run-2",
    )
    other = observation(
        "vendor-b",
        "vendor-b-security",
        "https://vendor-b.example/security",
        "bot_protected",
        http_status=403,
    )

    report = build_latest_source_health_index(
        ledger([older, other, newer]),
        generated_at="2026-05-24T08:32:00Z",
    )

    assert report["report_type"] == "latest_source_health_index"
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "site_ui_generated": False,
        "historical_ledger_committed": False,
        "non_advisory": True,
    }
    assert report["snapshot"] == {
        "generated_at": "2026-05-24T08:32:00Z",
        "source_observation_ledger_generated_at": "2026-05-24T08:31:00Z",
        "latest_verified_at": "2026-05-24T08:30:00Z",
        "latest_source_health_records": 2,
    }
    assert report["summary"] == {
        "observations_seen": 3,
        "latest_source_health_records": 2,
        "superseded_observations": 1,
        "status_counts": {"bot_protected": 1, "ok": 1},
        "status_bucket_counts": {"ambiguous": 1, "healthy": 1},
    }

    assert [(row["vendor_id"], row["source_id"]) for row in report["sources"]] == [
        ("vendor-a", "vendor-a-dpa"),
        ("vendor-b", "vendor-b-security"),
    ]
    first = report["sources"][0]
    assert first["status"] == "ok"
    assert first["status_bucket"] == "healthy"
    assert first["http_status"] == 200
    assert first["verified_at"] == "2026-05-24T08:30:00Z"
    assert first["run_id"] == "run-2"


def test_rejects_non_ledger_input():
    with pytest.raises(ValueError, match="source_observation_ledger"):
        build_latest_source_health_index({"report_type": "source_verification_report", "observations": []})


def test_latest_health_cli_writes_json(tmp_path: Path):
    ledger_path = tmp_path / "source-observation-ledger.json"
    output_path = tmp_path / "latest-source-health.json"
    ledger_path.write_text(json.dumps(ledger([
        observation("vendor-a", "source-a", "https://vendor-a.example", "redirected"),
    ])) + "\n", encoding="utf-8")

    assert main([
        "build",
        "--source-observation-ledger",
        str(ledger_path),
        "--output",
        str(output_path),
    ]) == 0

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["report_type"] == "latest_source_health_index"
    assert output["summary"]["latest_source_health_records"] == 1
    assert output["sources"][0]["status_bucket"] == "healthy"
