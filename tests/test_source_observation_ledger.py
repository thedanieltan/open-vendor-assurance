from __future__ import annotations

import json
from pathlib import Path

from tools.openva.source_observation_ledger import (
    build_source_observation_ledger,
    main,
)


def verification_report(rows=None):
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-24T08:30:00Z",
        "report_type": "source_verification_report",
        "sources": rows
        or [
            {
                "vendor_id": "vendor-b",
                "source_id": "vendor-b-security",
                "source_url": "https://vendor-b.example/security",
                "verification_status": "ok",
                "http_status": 200,
                "final_url": "https://vendor-b.example/security",
            },
            {
                "vendor_id": "vendor-a",
                "source_id": "vendor-a-dpa",
                "source_url": "https://vendor-a.example/dpa",
                "verification_status": "not_found",
                "http_status": 404,
                "final_url": "https://vendor-a.example/dpa",
            },
        ],
    }


def test_builds_stable_source_observation_ledger_records():
    ledger = build_source_observation_ledger(
        verification_report(),
        run_id="26355961230",
        generated_at="2026-05-24T08:31:00Z",
    )

    assert ledger["report_type"] == "source_observation_ledger"
    assert ledger["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "non_advisory": True,
    }
    assert ledger["summary"] == {
        "source_verification_rows_seen": 2,
        "observation_records": 2,
        "duplicate_records_deduplicated": 0,
        "status_counts": {"not_found": 1, "ok": 1},
    }
    assert [row["vendor_id"] for row in ledger["observations"]] == ["vendor-a", "vendor-b"]

    row = ledger["observations"][0]
    assert set(row) == {
        "schema_version",
        "observation_id",
        "vendor_id",
        "source_id",
        "source_url",
        "status",
        "http_status",
        "final_url",
        "verified_at",
        "run_id",
        "observer",
    }
    assert row["vendor_id"] == "vendor-a"
    assert row["source_id"] == "vendor-a-dpa"
    assert row["source_url"] == "https://vendor-a.example/dpa"
    assert row["status"] == "not_found"
    assert row["http_status"] == 404
    assert row["final_url"] == "https://vendor-a.example/dpa"
    assert row["verified_at"] == "2026-05-24T08:30:00Z"
    assert row["run_id"] == "26355961230"
    assert row["observer"] == "source-verification-report"
    assert row["observation_id"].startswith("vendor-a-vendor-a-dpa-")


def test_ledger_output_is_deterministic_for_same_input():
    first = build_source_observation_ledger(
        verification_report(),
        run_id="run-1",
        generated_at="2026-05-24T08:31:00Z",
    )
    second = build_source_observation_ledger(
        verification_report(),
        run_id="run-1",
        generated_at="2026-05-24T08:31:00Z",
    )

    assert first == second


def test_ledger_deduplicates_exact_duplicate_observation_records():
    row = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-dpa",
        "source_url": "https://vendor-a.example/dpa",
        "verification_status": "ok",
        "http_status": 200,
        "final_url": "https://vendor-a.example/dpa",
    }
    ledger = build_source_observation_ledger(
        verification_report([row, dict(row)]),
        run_id="run-1",
        generated_at="2026-05-24T08:31:00Z",
    )

    assert ledger["summary"]["source_verification_rows_seen"] == 2
    assert ledger["summary"]["observation_records"] == 1
    assert ledger["summary"]["duplicate_records_deduplicated"] == 1


def test_ledger_rejects_missing_required_source_fields():
    bad = verification_report([
        {
            "vendor_id": "vendor-a",
            "source_id": "vendor-a-dpa",
            "source_url": "https://vendor-a.example/dpa",
        }
    ])

    try:
        build_source_observation_ledger(bad, run_id="run-1")
    except ValueError as error:
        assert "verification_status" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_ledger_cli_writes_json_output(tmp_path: Path):
    report_path = tmp_path / "source-verification-report.json"
    output_path = tmp_path / "source-observation-ledger.json"
    summary_path = tmp_path / "source-observation-ledger-summary.md"
    report_path.write_text(json.dumps(verification_report()) + "\n", encoding="utf-8")

    assert main([
        "build",
        "--source-verification-report",
        str(report_path),
        "--run-id",
        "26355961230",
        "--output",
        str(output_path),
        "--summary-md",
        str(summary_path),
    ]) == 0

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["report_type"] == "source_observation_ledger"
    assert output["summary"]["observation_records"] == 2

    summary = summary_path.read_text(encoding="utf-8")
    assert "# OpenVA Source Observation Ledger" in summary
    assert "- Run ID: `26355961230`" in summary
    assert "- Does not mutate catalog files." in summary
