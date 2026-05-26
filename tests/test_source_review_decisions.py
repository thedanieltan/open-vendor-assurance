from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tools.openva.source_review_decisions import (
    CSV_FIELDS,
    build_decision_sheet,
    build_sheet_markdown,
    build_validation_markdown,
    main,
    review_item_id_for,
    validate_decision_sheet,
    write_sheet_csv,
)


def triage_item(**updates: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-security",
        "source_type": "security_page",
        "source_url": "https://vendor-a.example/security-old",
        "final_url": "https://vendor-a.example/security-old",
        "http_status": 404,
        "verification_status": "not_found",
        "bucket": "mark_no_replacement_available",
        "reason_codes": ["no_verified_public_vendor_replacement"],
        "recommended_next_action": "Keep source unavailable / not available until a public vendor source is verified.",
    }
    item.update(updates)
    return item


def triage_plan(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-26T00:00:00Z",
        "report_type": "source_review_triage_plan",
        "items": items,
        "summary": {"triage_rows": len(items)},
    }


def sheet_rows(plan: dict[str, Any]) -> list[dict[str, str]]:
    return build_decision_sheet(plan, generated_at="2026-05-26T00:01:00Z")["rows"]


def write_rows(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def validate(plan: dict[str, Any], path: Path, verifier=None) -> dict[str, Any]:
    return validate_decision_sheet(
        plan,
        decision_sheet_path=path,
        triage_source="source-review-triage-plan.json",
        generated_at="2026-05-26T00:02:00Z",
        verifier=verifier,
    )


def completed_row(plan: dict[str, Any], decision: str, **updates: Any) -> dict[str, Any]:
    row = sheet_rows(plan)[0]
    row.update(
        {
            "review_decision": decision,
            "reviewer_note": "Reviewed public source context.",
            "reviewed_by": "reviewer@example.com",
            "reviewed_at": "2026-05-26T00:00:00Z",
        }
    )
    row.update(updates)
    return row


def ok_verifier(item: dict[str, Any], url: str) -> dict[str, Any]:
    return {
        "ok": True,
        "replacement_source_url": url,
        "replacement_final_url": url,
        "replacement_verification_status": "ok",
        "replacement_http_status": 200,
        "replacement_semantic_status": "strong",
        "replacement_authority_status": "vendor_controlled",
        "replacement_access_status": "public_web",
        "replacement_url_safety_status": "passed",
        "soft_404_detected": False,
        "redirect_canonical_drift": False,
    }


def rejecting_verifier(reason: str):
    def _verify(item: dict[str, Any], url: str) -> dict[str, Any]:
        return {"ok": False, "reason_codes": [reason], "message": reason}

    return _verify


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


def reason_codes(report: dict[str, Any]) -> set[str]:
    return {reason for row in report["invalid_rows"] for reason in row["reason_codes"]}


def test_build_sheet_creates_expected_reviewer_columns():
    report = build_decision_sheet(triage_plan([triage_item()]))

    assert list(report["rows"][0]) == CSV_FIELDS
    for field in ["review_decision", "approved_replacement_url", "reviewer_note", "reviewed_by", "reviewed_at"]:
        assert field in report["rows"][0]


def test_build_sheet_leaves_review_decision_blank():
    report = build_decision_sheet(triage_plan([triage_item()]))

    assert report["rows"][0]["review_decision"] == ""


def test_csv_output_escapes_formula_injection_values(tmp_path: Path):
    plan = triage_plan([triage_item(vendor_id="=cmd", source_id="+source", source_type="@type")])
    output = tmp_path / "source-review-decision-sheet.csv"

    write_sheet_csv(build_decision_sheet(plan), output)

    text = output.read_text(encoding="utf-8")
    assert "'=cmd" in text
    assert "'+source" in text
    assert "'@type" in text


def test_validate_sheet_accepts_valid_no_replacement_decision(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "mark_no_replacement_available")])

    report = validate(plan, path)

    assert report["summary"]["invalid_rows_count"] == 0
    assert report["summary"]["no_replacement_decisions_count"] == 1
    assert report["no_replacement_decisions"][0]["requires_catalog_truth_state_followup"] is True


def test_validate_sheet_accepts_valid_defer_decision(tmp_path: Path):
    plan = triage_plan([triage_item(bucket="access_ambiguous_review")])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "defer_access_ambiguous")])

    report = validate(plan, path)

    assert report["summary"]["invalid_rows_count"] == 0
    assert report["summary"]["deferred_decisions_count"] == 1
    assert report["deferred_decisions"][0]["truth_state"] == "access_ambiguous"


def test_validate_sheet_rejects_invalid_review_decision_enum(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "approve_it")])

    report = validate(plan, path)

    assert "invalid_review_decision" in reason_codes(report)


def test_validate_sheet_rejects_changed_immutable_context(tmp_path: Path):
    plan = triage_plan([triage_item()])
    row = completed_row(plan, "mark_no_replacement_available")
    row["vendor_id"] = "vendor-b"
    row["source_id"] = "vendor-b-security"
    row["source_type"] = "privacy_notice"
    row["source_url"] = "https://vendor-b.example/privacy"
    path = tmp_path / "sheet.csv"
    write_rows(path, [row])

    report = validate(plan, path)

    assert {"vendor_id_changed", "source_id_changed", "source_type_changed", "source_url_changed"} <= reason_codes(report)


def test_validate_sheet_rejects_duplicate_review_item_id(tmp_path: Path):
    plan = triage_plan([triage_item()])
    row = completed_row(plan, "mark_no_replacement_available")
    path = tmp_path / "sheet.csv"
    write_rows(path, [row, row])

    report = validate(plan, path)

    assert "duplicate_review_item_id" in reason_codes(report)


def test_validate_sheet_rejects_unexpected_self_certifying_fields(tmp_path: Path):
    plan = triage_plan([triage_item()])
    row = completed_row(plan, "mark_no_replacement_available")
    row["eligible"] = "true"
    path = tmp_path / "sheet.csv"
    write_rows(path, [row], fields=CSV_FIELDS + ["eligible"])

    report = validate(plan, path)

    assert {"unexpected_columns", "self_certifying_field_present"} <= reason_codes(report)


def test_validate_sheet_rejects_unsafe_url_schemes(tmp_path: Path):
    plan = triage_plan([triage_item(source_url="javascript:alert(1)")])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "mark_no_replacement_available")])

    report = validate(plan, path)

    assert "source_url_safety_not_passed" in reason_codes(report)


def test_validate_sheet_rejects_same_url_replacement(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(
        path,
        [
            completed_row(
                plan,
                "replace_with_url",
                approved_replacement_url="https://vendor-a.example/security-old",
            )
        ],
    )

    report = validate(plan, path, verifier=ok_verifier)

    assert "replacement_url_same_as_current" in reason_codes(report)


def test_validate_sheet_rejects_tracking_param_only_replacement(tmp_path: Path):
    plan = triage_plan([triage_item(source_url="https://vendor-a.example/security-old")])
    path = tmp_path / "sheet.csv"
    write_rows(
        path,
        [
            completed_row(
                plan,
                "replace_with_url",
                approved_replacement_url="https://vendor-a.example/security-old?utm_source=review",
            )
        ],
    )

    report = validate(plan, path, verifier=ok_verifier)

    assert "replacement_url_tracking_param_only" in reason_codes(report)


def test_validate_sheet_rejects_replace_with_url_without_reviewer_metadata(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    row = completed_row(
        plan,
        "replace_with_url",
        approved_replacement_url="https://vendor-a.example/security",
        reviewed_by="",
    )
    write_rows(path, [row])

    report = validate(plan, path, verifier=ok_verifier)

    assert "reviewed_by_missing" in reason_codes(report)


def test_validate_sheet_rejects_mark_no_replacement_with_approved_url(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(
        path,
        [completed_row(plan, "mark_no_replacement_available", approved_replacement_url="https://vendor-a.example/security")],
    )

    report = validate(plan, path)

    assert "approved_replacement_url_not_allowed" in reason_codes(report)


def test_validate_sheet_rejects_defer_access_ambiguous_with_approved_url(tmp_path: Path):
    plan = triage_plan([triage_item(bucket="access_ambiguous_review")])
    path = tmp_path / "sheet.csv"
    write_rows(
        path,
        [completed_row(plan, "defer_access_ambiguous", approved_replacement_url="https://vendor-a.example/security")],
    )

    report = validate(plan, path)

    assert "approved_replacement_url_not_allowed" in reason_codes(report)


def test_validate_sheet_fail_closes_when_live_verification_errors(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "replace_with_url", approved_replacement_url="https://vendor-a.example/security")])

    def broken_verifier(item: dict[str, Any], url: str) -> dict[str, Any]:
        raise RuntimeError("network unavailable")

    report = validate(plan, path, verifier=broken_verifier)

    assert "live_verification_error" in reason_codes(report)
    assert report["summary"]["approved_repairs_count"] == 0


def test_validate_sheet_rejects_soft_404_replacement(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "replace_with_url", approved_replacement_url="https://vendor-a.example/security")])

    report = validate(plan, path, verifier=rejecting_verifier("soft_404_detected"))

    assert "soft_404_detected" in reason_codes(report)


def test_validate_sheet_rejects_weak_semantic_replacement(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "replace_with_url", approved_replacement_url="https://vendor-a.example/security")])

    report = validate(plan, path, verifier=rejecting_verifier("replacement_semantic_status_not_strong"))

    assert "replacement_semantic_status_not_strong" in reason_codes(report)


def test_validate_sheet_rejects_redirect_canonical_drift(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "replace_with_url", approved_replacement_url="https://vendor-a.example/security")])

    report = validate(plan, path, verifier=rejecting_verifier("redirect_canonical_drift"))

    assert "redirect_canonical_drift" in reason_codes(report)


def test_validate_sheet_emits_approved_repairs_only_for_fully_verified_replacement_rows(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "replace_with_url", approved_replacement_url="https://vendor-a.example/security")])

    report = validate(plan, path, verifier=ok_verifier)

    assert report["summary"]["invalid_rows_count"] == 0
    assert report["summary"]["approved_repairs_count"] == 1
    assert report["approved_repairs"][0]["replacement_semantic_status"] == "strong"


def test_validation_output_has_reviewer_input_trusted_false(tmp_path: Path):
    plan = triage_plan([triage_item()])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "mark_no_replacement_available")])

    report = validate(plan, path)

    assert report["posture"]["reviewer_input_trusted"] is False


def test_validation_output_never_contains_self_certifying_fields(tmp_path: Path):
    plan = triage_plan([triage_item(eligible=True, eligible_for_automerge=True, tool_recommendation="repair")])
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "mark_no_replacement_available")])

    report = validate(plan, path)

    assert not {"eligible", "eligible_for_automerge", "tool_recommendation"} & recursive_keys(report)


def test_markdown_summaries_include_invalid_row_counts_and_next_actions(tmp_path: Path):
    plan = triage_plan([triage_item()])
    sheet_report = build_decision_sheet(plan)
    path = tmp_path / "sheet.csv"
    write_rows(path, [completed_row(plan, "approve_it")])
    validation = validate(plan, path)

    sheet_markdown = build_sheet_markdown(sheet_report)
    validation_markdown = build_validation_markdown(validation)

    assert "Reviewer decisions are not trusted until independently validated." in sheet_markdown
    assert "Invalid rows: `1`" in validation_markdown
    assert "Fix invalid rows and re-run validation" in validation_markdown


def test_deterministic_stable_ordering(tmp_path: Path):
    items = [
        triage_item(vendor_id="vendor-b", source_id="vendor-b-security", source_url="https://vendor-b.example/security"),
        triage_item(vendor_id="vendor-a", source_id="vendor-a-security", source_url="https://vendor-a.example/security"),
    ]
    plan = triage_plan(items)
    rows = [
        completed_row(triage_plan([items[1]]), "mark_no_replacement_available"),
        completed_row(triage_plan([items[0]]), "mark_no_replacement_available"),
    ]
    path = tmp_path / "sheet.csv"
    write_rows(path, rows)

    report = validate(plan, path)

    assert [row["source_review_decision_id"] for row in report["no_replacement_decisions"]] == sorted(
        review_item_id_for(item) for item in items
    )


def test_cli_build_and_validate_write_outputs(tmp_path: Path):
    plan = triage_plan([triage_item()])
    triage_path = tmp_path / "source-review-triage-plan.json"
    sheet_path = tmp_path / "source-review-decision-sheet.csv"
    sheet_md = tmp_path / "source-review-decision-sheet-summary.md"
    validation_json = tmp_path / "source-review-decision-validation.json"
    validation_md = tmp_path / "source-review-decision-validation-summary.md"
    triage_path.write_text(json.dumps(plan), encoding="utf-8")

    assert main(
        [
            "build-sheet",
            "--triage-plan",
            str(triage_path),
            "--output-csv",
            str(sheet_path),
            "--output-md",
            str(sheet_md),
        ]
    ) == 0
    rows = sheet_rows(plan)
    rows[0].update(
        {
            "review_decision": "mark_no_replacement_available",
            "reviewer_note": "No public vendor replacement found.",
            "reviewed_by": "reviewer@example.com",
            "reviewed_at": "2026-05-26T00:00:00Z",
        }
    )
    write_rows(sheet_path, rows)

    assert main(
        [
            "validate-sheet",
            "--triage-plan",
            str(triage_path),
            "--decision-sheet",
            str(sheet_path),
            "--output-json",
            str(validation_json),
            "--output-md",
            str(validation_md),
        ]
    ) == 0
    assert json.loads(validation_json.read_text(encoding="utf-8"))["summary"]["invalid_rows_count"] == 0
