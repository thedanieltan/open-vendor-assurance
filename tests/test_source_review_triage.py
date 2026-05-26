from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tools.openva.source_review_triage import (
    CSV_FIELDS,
    build_source_review_triage_plan,
    main,
)


def sweep_row(**updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-security",
        "source_type": "security_page",
        "original_source_url": "https://vendor-a.example/security",
        "original_final_url": "https://vendor-a.example/security",
        "original_http_status": 200,
        "original_status": "possible_mismatch",
        "bucket": "human_review_required",
        "reason_codes": ["original_status_not_hard_p0", "replacement_missing", "possible_mismatch"],
        "requires_human_review": True,
    }
    row.update(updates)
    return row


def sweep_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-26T00:00:00Z",
        "report_type": "source_repair_sweep",
        "records": rows,
        "human_review_required": [row for row in rows if row.get("bucket") == "human_review_required"],
        "no_replacement_found": [row for row in rows if row.get("bucket") == "no_replacement_found"],
    }


def build(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return build_source_review_triage_plan(
        sweep_report(rows),
        generated_at="2026-05-26T00:01:00Z",
    )


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


def test_human_review_rows_classify_into_quality_bucket():
    report = build([sweep_row()])

    item = report["items"][0]
    assert item["bucket"] == "source_quality_review"
    assert item["recommended_next_action"] == "Review source quality, authority, and source_type match before repair."


def test_no_replacement_rows_classify_into_mark_no_replacement_available():
    report = build([
        sweep_row(
            bucket="no_replacement_found",
            original_status="not_found",
            original_http_status=404,
            reason_codes=[
                "original_hard_p0_status",
                "replacement_missing",
                "no_verified_public_vendor_replacement",
            ],
        )
    ])

    assert report["items"][0]["bucket"] == "mark_no_replacement_available"


def test_no_replacement_rows_can_defer_vendor_source_unpublished():
    report = build([
        sweep_row(
            bucket="no_replacement_found",
            original_status="not_found",
            reason_codes=["source_unpublished", "no_verified_public_vendor_replacement"],
        )
    ])

    assert report["items"][0]["bucket"] == "defer_vendor_source_unpublished"


def test_soft_not_found_routes_to_soft_not_found_review():
    report = build([
        sweep_row(
            original_status="soft_not_found",
            soft_404_detected=True,
            reason_codes=["soft_not_found"],
        )
    ])

    assert report["items"][0]["bucket"] == "soft_not_found_review"


def test_redirect_canonical_drift_routes_to_manual_canonical_url_review():
    report = build([
        sweep_row(
            original_status="redirected",
            redirect_canonical_drift=True,
            reason_codes=["redirect_canonical_drift"],
        )
    ])

    assert report["items"][0]["bucket"] == "manual_canonical_url_review"


def test_access_ambiguity_routes_to_access_ambiguous_review():
    report = build([
        sweep_row(
            original_status="bot_protected",
            original_http_status=403,
            reason_codes=["access_ambiguous"],
        )
    ])

    assert report["items"][0]["bucket"] == "access_ambiguous_review"
    assert "blocked" in report["items"][0]["notes"]


def test_quality_issues_route_to_source_quality_review():
    report = build([
        sweep_row(
            original_status="homepage_or_generic_redirect",
            reason_codes=["homepage_or_generic_redirect"],
        ),
        sweep_row(
            vendor_id="vendor-b",
            source_id="vendor-b-dpa",
            source_type="dpa",
            original_status="suspect_inferred_url",
            reason_codes=["suspect_inferred_url"],
        ),
    ])

    assert {item["bucket"] for item in report["items"]} == {"source_quality_review"}


def test_may_repair_automatically_is_always_false_and_requires_human_review_true():
    report = build([
        sweep_row(),
        sweep_row(bucket="no_replacement_found", original_status="not_found"),
    ])

    assert {item["may_repair_automatically"] for item in report["items"]} == {False}
    assert {item["requires_human_review"] for item in report["items"]} == {True}
    assert report["summary"]["may_repair_automatically_count"] == 0
    assert report["summary"]["requires_human_review_count"] == 2


def test_no_self_certifying_fields_are_emitted():
    report = build([
        sweep_row(eligible=True, eligible_for_automerge=True, tool_recommendation="repair")
    ])

    assert not {"eligible", "eligible_for_automerge", "tool_recommendation"} & recursive_keys(report)


def test_deterministic_stable_ordering():
    rows = [
        sweep_row(vendor_id="vendor-c", source_id="vendor-c-security"),
        sweep_row(vendor_id="vendor-a", source_id="vendor-a-dpa", source_type="dpa"),
        sweep_row(
            vendor_id="vendor-b",
            source_id="vendor-b-dpa",
            source_type="dpa",
            bucket="no_replacement_found",
            original_status="not_found",
        ),
    ]

    first = build(rows)
    second = build(list(reversed(rows)))

    assert [(item["bucket"], item["vendor_id"], item["source_id"]) for item in first["items"]] == [
        ("source_quality_review", "vendor-a", "vendor-a-dpa"),
        ("source_quality_review", "vendor-c", "vendor-c-security"),
        ("mark_no_replacement_available", "vendor-b", "vendor-b-dpa"),
    ]
    assert first["items"] == second["items"]


def test_cli_writes_csv_with_stable_columns_and_markdown_summary(tmp_path: Path):
    sweep_path = tmp_path / "source-repair-sweep-report.json"
    output_json = tmp_path / "source-review-triage-plan.json"
    output_csv = tmp_path / "source-review-triage-plan.csv"
    output_md = tmp_path / "source-review-triage-summary.md"
    sweep_path.write_text(json.dumps(sweep_report([sweep_row()])), encoding="utf-8")

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
        ]
    ) == 0

    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_FIELDS
        rows = list(reader)
    assert rows[0]["may_repair_automatically"] == "False"
    assert json.loads(output_json.read_text(encoding="utf-8"))["summary"]["triage_rows"] == 1
    markdown = output_md.read_text(encoding="utf-8")
    assert "## Bucket Counts" in markdown
    assert "## Top Source Types" in markdown
    assert "## Top Vendors" in markdown


def test_markdown_summary_includes_bucket_counts_and_top_source_types_vendors():
    report = build([
        sweep_row(),
        sweep_row(vendor_id="vendor-b", source_id="vendor-b-security"),
    ])

    summary = report["summary"]
    assert summary["bucket_counts"] == {"source_quality_review": 2}
    assert summary["top_source_types"] == {"security_page": 2}
    assert summary["top_vendor_ids"] == {"vendor-a": 1, "vendor-b": 1}
