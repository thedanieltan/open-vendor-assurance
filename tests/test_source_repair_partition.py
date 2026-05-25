from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from tools.openva.source_repair_actions import build_repair_action_plan
from tools.openva.source_repair_partition import main, partition_source_repair_validation


def evidence_row(**updates):
    row = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-dpa",
        "source_type": "dpa",
        "source_url": "https://example.com/old-dpa",
        "original": {
            "prior": {"verification_status": "not_found", "http_status": 404},
            "fresh": {"verification_status": "not_found", "http_status": 404},
        },
        "replacement": None,
        "proposed_change": None,
    }
    row.update(updates)
    return row


def evidence_report(rows):
    return {
        "report_type": "p0_source_repair_evidence",
        "generated_at": "2026-05-25T00:00:00Z",
        "repairs": rows,
    }


def validation_row(**updates):
    row = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-dpa",
        "source_type": "dpa",
        "original_source_url": "https://example.com/old-dpa",
        "replacement_source_url": "https://example.com/new-dpa",
        "replacement_verification_status": "ok",
        "replacement_http_status": 200,
        "replacement_semantic_status": "strong",
        "replacement_authority_status": "vendor_controlled",
        "replacement_access_status": "public",
        "replacement_url_safety_status": "passed",
        "reasons": [],
    }
    row.update(updates)
    return row


def validation_report(*, approved=None, rejected=None, unmatched=None):
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-25T01:00:00Z",
        "report_type": "p0_source_repair_plan_validation",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "inputs": {
            "evidence_report_type": "p0_source_repair_evidence",
            "plan_report_type": "p0_source_repair_plan",
        },
        "approved": approved or [],
        "rejected": rejected or [],
        "unmatched": unmatched or [],
        "summary": {
            "evidence_repair_count": 0,
            "plan_repair_count": len(approved or []) + len(rejected or []) + len(unmatched or []),
            "approved_count": len(approved or []),
            "rejected_count": len(rejected or []),
            "unmatched_count": len(unmatched or []),
        },
    }


def partition(evidence, validation):
    return partition_source_repair_validation(
        evidence=evidence,
        validation=validation,
        source_validation_report="maintenance/reviewed/validation.json",
        source_evidence_report="maintenance/reviewed/evidence.json",
    )


def write_source(root: Path, row: dict):
    path = root / "data" / "vendors" / row["vendor_id"] / "sources" / f"{row['source_id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "source_id": row["source_id"],
                "vendor_id": row["vendor_id"],
                "source_type": row["source_type"],
                "source_url": row["original_source_url"],
                "review_state": "auto_validated",
                "catalog_tier": "machine_validated",
                "provenance": {"observer": "agent", "confidence": "medium"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_all_rows_eligible_go_to_automerge_partition():
    rows = [
        validation_row(vendor_id="vendor-b", source_id="vendor-b-dpa", original_source_url="https://b.test/old", replacement_source_url="https://b.test/new"),
        validation_row(vendor_id="vendor-a", source_id="vendor-a-dpa", original_source_url="https://a.test/old", replacement_source_url="https://a.test/new"),
    ]
    evidence = evidence_report([
        evidence_row(vendor_id="vendor-a", source_id="vendor-a-dpa", source_url="https://a.test/old"),
        evidence_row(vendor_id="vendor-b", source_id="vendor-b-dpa", source_url="https://b.test/old"),
    ])

    automerge, manual, report, _ = partition(evidence, validation_report(approved=rows))

    assert [row["vendor_id"] for row in automerge["approved"]] == ["vendor-a", "vendor-b"]
    assert manual["approved"] == []
    assert report["summary"] == {
        "total_rows": 2,
        "automerge_eligible_count": 2,
        "manual_review_required_count": 0,
        "excluded_count": 0,
    }


def test_mixed_rows_split_eligible_and_manual_with_reasons():
    eligible = validation_row(vendor_id="vendor-a", source_id="vendor-a-dpa")
    manual = validation_row(
        vendor_id="vendor-b",
        source_id="vendor-b-dpa",
        original_source_url="https://b.test/old",
        replacement_source_url="https://b.test/new",
        replacement_authority_status="approved_exception",
    )
    evidence = evidence_report([
        evidence_row(vendor_id="vendor-a", source_id="vendor-a-dpa"),
        evidence_row(vendor_id="vendor-b", source_id="vendor-b-dpa", source_url="https://b.test/old"),
    ])

    automerge, manual_report, report, _ = partition(evidence, validation_report(approved=[manual, eligible]))

    assert [row["source_id"] for row in automerge["approved"]] == ["vendor-a-dpa"]
    assert [row["source_id"] for row in manual_report["approved"]] == ["vendor-b-dpa"]
    assert report["manual_review_required"][0]["reasons"] == ["authority_not_allowed"]


def test_missing_evidence_goes_to_manual_review_required():
    row = validation_row()

    automerge, manual, report, _ = partition(evidence_report([]), validation_report(approved=[row]))

    assert automerge["approved"] == []
    assert manual["approved"] == [row]
    assert report["manual_review_required"][0]["reasons"] == ["evidence_missing"]


def test_weak_semantic_status_goes_to_manual_review_required():
    row = validation_row(replacement_semantic_status="weak", reasons=["replacement_semantic_status_not_strong"])

    _, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(rejected=[row]))

    assert manual["rejected"] == [row]
    assert "validation_not_approved" in report["manual_review_required"][0]["reasons"]
    assert "semantic_status_not_strong" in report["manual_review_required"][0]["reasons"]


def test_access_not_public_goes_to_manual_review_required():
    row = validation_row(replacement_access_status="bot_protected")

    automerge, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(approved=[row]))

    assert automerge["approved"] == []
    assert manual["approved"] == [row]
    assert report["manual_review_required"][0]["reasons"] == ["access_not_public"]


def test_source_type_change_goes_to_manual_review_required():
    row = validation_row(source_type="security_page", reasons=["source_type_changed"])

    _, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(rejected=[row]))

    assert manual["rejected"] == [row]
    assert "source_type_changed" in report["manual_review_required"][0]["reasons"]


def test_self_certifying_field_prevents_automerge_eligibility():
    row = validation_row(eligible_for_automerge=True)

    automerge, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(approved=[row]))

    assert automerge["approved"] == []
    assert manual["approved"] == [row]
    assert report["manual_review_required"][0]["reasons"] == ["self_certifying_field_present"]


def test_soft_404_diagnostic_prevents_automerge_eligibility():
    row = validation_row(replacement_soft_404_detected=True, reasons=["soft_404_detected"])

    automerge, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(approved=[row]))

    assert automerge["approved"] == []
    assert manual["approved"] == [row]
    assert report["manual_review_required"][0]["reasons"] == ["soft_404_detected"]


def test_mixpanel_batch007_soft_404_shape_goes_to_manual_review_required():
    row = validation_row(
        vendor_id="mixpanel",
        source_id="mixpanel-compliance",
        source_type="compliance_page",
        original_source_url="https://mixpanel.com/security/#compliance",
        replacement_source_url="https://mixpanel.com/legal/security/#compliance",
        replacement_verification_status="soft_not_found",
        replacement_soft_404_detected=True,
        reasons=["soft_404_detected"],
    )
    evidence = evidence_report([
        evidence_row(
            vendor_id="mixpanel",
            source_id="mixpanel-compliance",
            source_type="compliance_page",
            source_url="https://mixpanel.com/security/#compliance",
        )
    ])

    automerge, manual, report, _ = partition(evidence, validation_report(rejected=[row]))

    assert automerge["approved"] == []
    assert manual["rejected"] == [row]
    assert report["manual_review_required"][0]["reasons"] == [
        "validation_not_approved",
        "soft_404_detected",
        "unknown_or_unsupported_status",
    ]


def test_redirecting_replacement_not_canonical_goes_to_manual_review_required():
    row = validation_row(
        replacement_verification_status="redirected",
        replacement_source_url="https://example.com/privacy",
        replacement_final_url="https://docs.example.com/legal/privacy-policy",
    )

    automerge, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(approved=[row]))

    assert automerge["approved"] == []
    assert manual["approved"] == [row]
    assert report["manual_review_required"][0]["reasons"] == ["redirected_replacement_not_canonical"]


def test_redirecting_replacement_with_stored_final_url_can_be_automerge_eligible():
    row = validation_row(
        replacement_verification_status="redirected",
        replacement_source_url="https://docs.example.com/legal/privacy-policy",
        replacement_final_url="https://docs.example.com/legal/privacy-policy/",
    )

    automerge, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(approved=[row]))

    assert [item["source_id"] for item in automerge["approved"]] == ["vendor-a-dpa"]
    assert manual["approved"] == []
    assert report["automerge_eligible"][0]["reasons"] == [
        "approved_validation_row",
        "confirmed_p0",
        "replacement_redirected",
        "http_status_2xx_or_3xx",
        "semantic_strong",
        "authority_allowed",
        "public_access",
        "url_safety_passed",
        "source_type_unchanged",
        "replacement_url_differs",
    ]


def test_redirected_replacement_without_final_url_goes_to_manual_review_required():
    row = validation_row(replacement_verification_status="redirected")

    automerge, manual, report, _ = partition(evidence_report([evidence_row()]), validation_report(approved=[row]))

    assert automerge["approved"] == []
    assert manual["approved"] == [row]
    assert report["manual_review_required"][0]["reasons"] == ["final_url_missing"]


def test_output_ordering_is_deterministic():
    rows = [
        validation_row(vendor_id="vendor-c", source_id="vendor-c-dpa", original_source_url="https://c.test/old", replacement_source_url="https://c.test/new"),
        validation_row(vendor_id="vendor-a", source_id="vendor-a-dpa", original_source_url="https://a.test/old", replacement_source_url="https://a.test/new"),
        validation_row(vendor_id="vendor-b", source_id="vendor-b-dpa", original_source_url="https://b.test/old", replacement_source_url="https://b.test/new"),
    ]
    evidence = evidence_report([
        evidence_row(vendor_id="vendor-c", source_id="vendor-c-dpa", source_url="https://c.test/old"),
        evidence_row(vendor_id="vendor-b", source_id="vendor-b-dpa", source_url="https://b.test/old"),
        evidence_row(vendor_id="vendor-a", source_id="vendor-a-dpa", source_url="https://a.test/old"),
    ])

    automerge, _, report, _ = partition(evidence, validation_report(approved=rows))

    assert [row["vendor_id"] for row in automerge["approved"]] == ["vendor-a", "vendor-b", "vendor-c"]
    assert [row["vendor_id"] for row in report["automerge_eligible"]] == ["vendor-a", "vendor-b", "vendor-c"]


def test_partitioned_validation_reports_remain_consumable_by_source_repair_pr(tmp_path):
    row = validation_row()
    write_source(tmp_path, row)
    automerge, manual, _, _ = partition(evidence_report([evidence_row()]), validation_report(approved=[row]))

    action_plan = build_repair_action_plan(automerge, root=tmp_path)
    manual_action_plan = build_repair_action_plan(manual, root=tmp_path)

    assert action_plan["summary"]["file_actions_planned"] == 1
    assert manual_action_plan["summary"]["file_actions_planned"] == 0


def test_cli_writes_partition_outputs_without_catalog_source_or_policy_mutation(tmp_path, monkeypatch):
    row = validation_row()
    source_path = write_source(tmp_path, row)
    source_before = source_path.read_text(encoding="utf-8")
    policy_path = tmp_path / "automerge-policy.yaml"
    policy_path.write_text("source_repair:\n  max_source_records_per_pr: 10\n", encoding="utf-8")
    policy_before = policy_path.read_text(encoding="utf-8")
    evidence_path = tmp_path / "evidence.json"
    validation_path = tmp_path / "validation.json"
    evidence_path.write_text(json.dumps(evidence_report([evidence_row()])), encoding="utf-8")
    validation_path.write_text(json.dumps(validation_report(approved=[row])), encoding="utf-8")
    automerge_output = tmp_path / "automerge.json"
    manual_output = tmp_path / "manual.json"
    report_output = tmp_path / "partition.json"
    summary_output = tmp_path / "partition.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openva-source-repair-partition",
            "partition",
            "--evidence",
            str(evidence_path),
            "--validation",
            str(validation_path),
            "--automerge-output",
            str(automerge_output),
            "--manual-output",
            str(manual_output),
            "--report-output",
            str(report_output),
            "--summary-output",
            str(summary_output),
            "--policy",
            str(policy_path),
        ],
    )

    assert main() == 0
    assert json.loads(automerge_output.read_text(encoding="utf-8"))["approved"][0]["source_id"] == row["source_id"]
    assert json.loads(manual_output.read_text(encoding="utf-8"))["approved"] == []
    assert source_path.read_text(encoding="utf-8") == source_before
    assert policy_path.read_text(encoding="utf-8") == policy_before
    assert not (tmp_path / "openva-pack.json").exists()
