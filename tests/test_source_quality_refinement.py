from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.openva.source_quality_refinement import (
    CSV_FIELDS,
    build_source_quality_refinement_queue,
    main,
)


def source(status: str, vendor_id: str = "vendor-a", source_id: str | None = None, source_type: str = "security_page") -> dict:
    resolved_source_id = source_id or f"{vendor_id}-{status}"
    return {
        "vendor_id": vendor_id,
        "source_id": resolved_source_id,
        "source_type": source_type,
        "source_url": f"https://{vendor_id}.example/{resolved_source_id}",
        "final_url": f"https://{vendor_id}.example/final/{resolved_source_id}",
        "http_status": 200,
        "verification_status": status,
        "requires_review": status not in {"ok", "redirected"},
    }


def report(rows: list[dict]) -> dict:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-24T13:00:00Z",
        "report_type": "source_verification_report",
        "sources": rows,
    }


def test_queues_only_layer_2c_quality_statuses():
    payload = build_source_quality_refinement_queue(
        report([
            source("homepage_or_generic_redirect", "vendor-c"),
            source("possible_mismatch", "vendor-b"),
            source("soft_not_found", "vendor-d"),
            source("suspect_inferred_url", "vendor-a"),
        ]),
        generated_at="2026-05-24T13:01:00Z",
    )

    assert [item["verification_status"] for item in payload["items"]] == [
        "homepage_or_generic_redirect",
        "possible_mismatch",
        "soft_not_found",
        "suspect_inferred_url",
    ]
    assert {item["requires_human_review"] for item in payload["items"]} == {True}
    assert payload["items"][0]["recommended_review_action"] == "Find a more specific vendor-controlled source URL."
    assert payload["items"][1]["recommended_review_action"] == "Verify semantic match against source_type before replacing."
    assert payload["items"][2]["recommended_review_action"] == "Replace with a reachable vendor-controlled source URL or return to unresolved handling."
    assert payload["items"][3]["recommended_review_action"] == "Confirm whether this inferred URL is real and authoritative."


def test_excludes_confirmed_p0_and_access_ambiguity_and_ok_statuses():
    excluded_statuses = [
        "not_found",
        "gone",
        "bot_protected",
        "forbidden_unknown",
        "gated_or_login_required",
        "rate_limited",
        "unreachable",
        "ok",
        "redirected",
    ]

    payload = build_source_quality_refinement_queue(
        report([source(status, source_id=f"source-{index}") for index, status in enumerate(excluded_statuses)]),
        generated_at="2026-05-24T13:01:00Z",
    )

    assert payload["summary"]["total_quality_review_count"] == 0
    assert payload["items"] == []


def test_emits_human_review_only_posture_and_no_self_certifying_fields():
    payload = build_source_quality_refinement_queue(
        report([source("possible_mismatch")]),
        generated_at="2026-05-24T13:01:00Z",
    )

    assert payload["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "requires_human_review": True,
        "non_advisory": True,
    }
    text = json.dumps(payload, sort_keys=True)
    assert "eligible" not in text
    assert "eligible_for_automerge" not in text
    assert "tool_recommendation" not in text


def test_emits_deterministic_stable_ordering():
    payload = build_source_quality_refinement_queue(
        report([
            source("suspect_inferred_url", "vendor-z", "source-z"),
            source("possible_mismatch", "vendor-c", "source-c"),
            source("homepage_or_generic_redirect", "vendor-b", "source-b"),
            source("possible_mismatch", "vendor-a", "source-a"),
        ]),
        generated_at="2026-05-24T13:01:00Z",
    )

    assert [(item["verification_status"], item["vendor_id"], item["source_id"]) for item in payload["items"]] == [
        ("homepage_or_generic_redirect", "vendor-b", "source-b"),
        ("possible_mismatch", "vendor-a", "source-a"),
        ("possible_mismatch", "vendor-c", "source-c"),
        ("suspect_inferred_url", "vendor-z", "source-z"),
    ]


def test_summary_counts_are_correct():
    payload = build_source_quality_refinement_queue(
        report([
            source("homepage_or_generic_redirect", "vendor-a", source_type="trust_center"),
            source("possible_mismatch", "vendor-a", source_type="trust_center"),
            source("possible_mismatch", "vendor-b", source_type="security_page"),
            source("soft_not_found", "vendor-d", source_type="compliance_page"),
            source("suspect_inferred_url", "vendor-c", source_type="privacy_notice"),
        ]),
        generated_at="2026-05-24T13:01:00Z",
    )

    assert payload["summary"] == {
        "total_quality_review_count": 5,
        "homepage_or_generic_redirect_count": 1,
        "possible_mismatch_count": 2,
        "soft_not_found_count": 1,
        "suspect_inferred_url_count": 1,
        "by_source_type": {"trust_center": 2, "compliance_page": 1, "privacy_notice": 1, "security_page": 1},
        "by_vendor_id": {"vendor-a": 2, "vendor-b": 1, "vendor-c": 1, "vendor-d": 1},
    }


def test_cli_writes_json_csv_and_markdown_outputs(tmp_path: Path):
    report_path = tmp_path / "source-verification-report.json"
    json_path = tmp_path / "source-quality-refinement-queue.json"
    csv_path = tmp_path / "source-quality-refinement-queue.csv"
    markdown_path = tmp_path / "source-quality-refinement-summary.md"
    report_path.write_text(
        json.dumps(report([
            source("possible_mismatch", "vendor-b"),
            source("not_found", "vendor-a"),
        ])) + "\n",
        encoding="utf-8",
    )

    assert main([
        "build",
        "--source-verification-report",
        str(report_path),
        "--json-output",
        str(json_path),
        "--csv-output",
        str(csv_path),
        "--markdown-output",
        str(markdown_path),
    ]) == 0

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["total_quality_review_count"] == 1
    assert "# OpenVA Source Quality Refinement Queue" in markdown_path.read_text(encoding="utf-8")

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_FIELDS
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["verification_status"] == "possible_mismatch"
    assert rows[0]["requires_human_review"] == "True"
