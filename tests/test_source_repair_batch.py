from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from tools.openva.source_repair_batch import (
    CSV_FIELDS,
    build_markdown_summary,
    build_source_repair_batch_plan,
    main,
)
from tools.openva.source_repair_plan import validate_source_repair_plan


def strict_row(vendor_id: str = "vendor-a", **updates: Any) -> dict[str, Any]:
    source_id = updates.pop("source_id", f"{vendor_id}-dpa")
    row: dict[str, Any] = {
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_type": "dpa",
        "original_source_url": f"https://{vendor_id}.example/old-dpa",
        "original_status": "not_found",
        "original_http_status": 404,
        "original_final_url": f"https://{vendor_id}.example/old-dpa",
        "replacement_source_url": f"https://{vendor_id}.example/legal/dpa",
        "replacement_final_url": f"https://{vendor_id}.example/legal/dpa",
        "replacement_http_status": 200,
        "replacement_verification_status": "ok",
        "replacement_semantic_status": "strong",
        "replacement_authority_status": "vendor_controlled",
        "replacement_access_status": "public",
        "soft_404_detected": False,
        "redirect_canonical_drift": False,
        "bucket": "strict_repair_ready",
        "reason_codes": ["original_hard_p0_status"],
        "requires_human_review": False,
    }
    row.update(updates)
    return row


def sweep(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-26T00:00:00Z",
        "report_type": "source_repair_sweep",
        "records": rows,
        "strict_repair_ready": [row for row in rows if row.get("bucket") == "strict_repair_ready"],
        "human_review_required": [row for row in rows if row.get("bucket") == "human_review_required"],
        "no_replacement_found": [row for row in rows if row.get("bucket") == "no_replacement_found"],
    }


def build(rows: list[dict[str, Any]], max_records: int = 10) -> dict[str, Any]:
    return build_source_repair_batch_plan(
        sweep(rows),
        max_records=max_records,
        generated_at="2026-05-26T00:01:00Z",
    )


def evidence_for(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_id": row["vendor_id"],
        "source_id": row["source_id"],
        "source_type": row["source_type"],
        "source_url": row["original_source_url"],
        "original": {
            "prior": {"verification_status": "not_found", "http_status": 404},
            "fresh": {"verification_status": "not_found", "http_status": 404},
        },
        "replacement": None,
        "proposed_change": None,
    }


def evidence_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "report_type": "p0_source_repair_evidence",
        "generated_at": "2026-05-26T00:00:00Z",
        "repairs": [evidence_for(row) for row in rows],
    }


def recursive_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(recursive_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(recursive_keys(child))
        return keys
    return set()


def test_builds_p0_source_repair_plan_from_strict_repair_ready_rows():
    payload = build([strict_row()])

    assert payload["report_type"] == "p0_source_repair_plan"
    assert payload["plan_source"] == "source_repair_sweep"
    assert payload["batch_type"] == "strict_repair_ready"
    assert payload["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "report_only": True,
        "non_advisory": True,
    }
    assert payload["summary"]["repair_count"] == 1
    assert payload["repairs"][0]["replacement_url_safety_status"] == "passed"
    assert payload["repairs"][0]["source_repair_sweep_reason_codes"] == ["original_hard_p0_status"]


def test_enforces_max_10_records_and_excludes_overflow():
    rows = [strict_row(f"vendor-{index:02d}") for index in range(12)]

    payload = build(rows)

    assert payload["summary"]["repair_count"] == 10
    assert payload["summary"]["excluded_by_reason"] == {"over_max_records": 2}
    assert [row["exclusion_reasons"] for row in payload["excluded"]] == [
        ["over_max_records"],
        ["over_max_records"],
    ]


def test_rejects_max_records_above_10():
    with pytest.raises(ValueError, match="<= 10"):
        build([strict_row()], max_records=11)


def test_excludes_human_review_required_rows():
    payload = build([strict_row(bucket="human_review_required", requires_human_review=True)])

    assert payload["repairs"] == []
    assert payload["excluded"][0]["exclusion_reasons"] == ["not_strict_repair_ready"]


def test_excludes_no_replacement_found_rows():
    payload = build([
        strict_row(
            bucket="no_replacement_found",
            replacement_source_url=None,
            replacement_final_url=None,
        )
    ])

    assert payload["repairs"] == []
    assert "not_strict_repair_ready" in payload["excluded"][0]["exclusion_reasons"]


def test_excludes_soft_404_detected_rows():
    payload = build([strict_row(soft_404_detected=True, reason_codes=["soft_404_detected"])])

    assert payload["repairs"] == []
    assert "soft_404_detected" in payload["excluded"][0]["exclusion_reasons"]


def test_excludes_redirect_canonical_drift_rows():
    payload = build([strict_row(redirect_canonical_drift=True, reason_codes=["redirect_canonical_drift"])])

    assert payload["repairs"] == []
    assert "redirect_canonical_drift" in payload["excluded"][0]["exclusion_reasons"]


def test_excludes_weak_semantic_rows():
    payload = build([strict_row(replacement_semantic_status="weak", reason_codes=["weak_semantic_match"])])

    assert payload["repairs"] == []
    assert "replacement_semantic_status_not_strong" in payload["excluded"][0]["exclusion_reasons"]
    assert "weak_semantic_match" in payload["excluded"][0]["exclusion_reasons"]


def test_excludes_inferred_candidate_rows():
    payload = build([strict_row(reason_codes=["suspect_inferred_url"])])

    assert payload["repairs"] == []
    assert "suspect_inferred_url" in payload["excluded"][0]["exclusion_reasons"]


def test_excludes_rows_missing_replacement_final_url():
    payload = build([strict_row(replacement_final_url=None)])

    assert payload["repairs"] == []
    assert "replacement_final_url_missing" in payload["excluded"][0]["exclusion_reasons"]


def test_excludes_rows_containing_self_certifying_fields():
    payload = build([strict_row(eligible=True, eligible_for_automerge=True, tool_recommendation="merge")])

    assert payload["repairs"] == []
    assert "self_certifying_field_present" in payload["excluded"][0]["exclusion_reasons"]
    assert not {"eligible", "eligible_for_automerge", "tool_recommendation"} & recursive_keys(payload)


def test_emits_deterministic_ordering():
    rows = [
        strict_row("vendor-b", source_id="vendor-b-security", source_type="security_page"),
        strict_row("vendor-a", source_id="vendor-a-dpa", source_type="dpa"),
        strict_row("vendor-a", source_id="vendor-a-security", source_type="security_page"),
    ]

    payload = build(rows)

    assert [(row["vendor_id"], row["source_type"], row["source_id"]) for row in payload["repairs"]] == [
        ("vendor-a", "dpa", "vendor-a-dpa"),
        ("vendor-a", "security_page", "vendor-a-security"),
        ("vendor-b", "security_page", "vendor-b-security"),
    ]


def test_cli_emits_csv_with_expected_columns_and_markdown_summary(tmp_path: Path):
    sweep_path = tmp_path / "source-repair-sweep-report.json"
    output_json = tmp_path / "source-repair-batch-plan.json"
    output_csv = tmp_path / "source-repair-batch-plan.csv"
    output_md = tmp_path / "source-repair-batch-summary.md"
    sweep_path.write_text(json.dumps(sweep([strict_row()])), encoding="utf-8")

    assert main(
        [
            "build",
            "--sweep-report",
            str(sweep_path),
            "--output-json",
            str(output_json),
            "--output-csv",
            str(output_csv),
            "--output-md",
            str(output_md),
            "--max-records",
            "10",
        ]
    ) == 0

    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_FIELDS
        rows = list(reader)
    assert rows[0]["replacement_url_safety_status"] == "passed"
    assert "# OpenVA Strict Source Repair Batch Plan" in output_md.read_text(encoding="utf-8")
    assert json.loads(output_json.read_text(encoding="utf-8"))["summary"]["repair_count"] == 1


def test_markdown_summary_mentions_report_only_guardrails():
    markdown = build_markdown_summary(build([strict_row()]))

    assert "Does not mutate catalog YAML" in markdown
    assert "Does not invoke source repair actions" in markdown


def test_output_is_compatible_with_source_repair_plan_validate_where_feasible():
    row = strict_row()
    payload = build([row])
    validation = validate_source_repair_plan(evidence_report([row]), payload)

    assert validation["summary"]["approved_count"] == 1
    assert validation["summary"]["rejected_count"] == 0
