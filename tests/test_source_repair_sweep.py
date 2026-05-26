from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tools.openva.source_repair_sweep import (
    CSV_FIELDS,
    build_source_repair_sweep,
    main,
)


def source(status: str, vendor_id: str = "vendor-a", **updates: Any) -> dict[str, Any]:
    source_id = updates.pop("source_id", f"{vendor_id}-dpa")
    row: dict[str, Any] = {
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_type": "dpa",
        "source_url": f"https://{vendor_id}.example/old-dpa",
        "final_url": f"https://{vendor_id}.example/old-dpa",
        "http_status": 404 if status == "not_found" else 200,
        "verification_status": status,
        "soft_404_detected": status == "soft_not_found",
        "requires_review": status not in {"ok", "redirected"},
    }
    row.update(updates)
    return row


def strict_source(**updates: Any) -> dict[str, Any]:
    row = source(
        "not_found",
        replacement_source_url="https://vendor-a.example/legal/dpa",
        replacement_final_url="https://vendor-a.example/legal/dpa",
        replacement_verification_status="ok",
        replacement_http_status=200,
        replacement_semantic_status="strong",
        replacement_authority_status="vendor_controlled",
        replacement_access_status="public",
    )
    row.update(updates)
    return row


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-26T00:00:00Z",
        "report_type": "source_verification_report",
        "sources": rows,
    }


def discovery_candidate_report(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-26T00:00:00Z",
        "report_type": "source_discovery_report",
        "vendors": [{"vendor_id": candidate["vendor_id"], "candidates": [candidate], "unavailable_sources": []}],
    }


def build(rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    return build_source_repair_sweep(report(rows), generated_at="2026-05-26T00:01:00Z", **kwargs)


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


def test_strict_candidate_with_strong_semantic_match_and_canonical_final_url_enters_strict_repair_ready():
    payload = build([strict_source()])

    assert payload["summary"]["strict_repair_ready_count"] == 1
    item = payload["strict_repair_ready"][0]
    assert item["bucket"] == "strict_repair_ready"
    assert item["requires_human_review"] is False
    assert item["recommended_next_action"] == "Eligible for small reviewed P0 repair batch."
    assert item["redirect_canonical_drift"] is False


def test_soft_not_found_enters_human_review_required():
    payload = build([source("soft_not_found")])

    assert payload["human_review_required"][0]["bucket"] == "human_review_required"
    assert "soft_not_found" in payload["human_review_required"][0]["reason_codes"]


def test_bot_protected_enters_human_review_required_with_no_verification_claims():
    payload = build([source("bot_protected", http_status=403)])

    item = payload["human_review_required"][0]
    assert item["source_exists_inference"] == "likely_endpoint_exists"
    assert item["content_verified"] is False
    assert item["semantic_verified"] is False
    assert "access_ambiguous" in item["reason_codes"]


def test_possible_mismatch_enters_human_review_required():
    payload = build([source("possible_mismatch")])

    assert payload["human_review_required"][0]["bucket"] == "human_review_required"
    assert "possible_mismatch" in payload["human_review_required"][0]["reason_codes"]


def test_homepage_or_generic_redirect_enters_human_review_required():
    payload = build([source("homepage_or_generic_redirect")])

    assert payload["human_review_required"][0]["bucket"] == "human_review_required"
    assert "homepage_or_generic_redirect" in payload["human_review_required"][0]["reason_codes"]


def test_suspect_inferred_url_enters_human_review_required():
    payload = build([source("suspect_inferred_url")])

    assert payload["human_review_required"][0]["bucket"] == "human_review_required"
    assert "suspect_inferred_url" in payload["human_review_required"][0]["reason_codes"]


def test_no_candidate_enters_no_replacement_found():
    payload = build([source("not_found")])

    item = payload["no_replacement_found"][0]
    assert item["bucket"] == "no_replacement_found"
    assert item["recommended_next_action"] == "Keep source unavailable / not available until vendor publishes a source."
    assert "no_verified_public_vendor_replacement" in item["reason_codes"]


def test_inferred_candidate_url_does_not_enter_strict_repair_ready():
    candidate = {
        "vendor_id": "vendor-a",
        "candidate_source_id": "vendor-a-dpa-candidate",
        "source_type_candidate": "dpa",
        "candidate_url": "https://vendor-a.example/legal/data-processing-addendum",
        "discovery_method": "official_domain_crawl",
        "requires_review": True,
        "confidence": "likely",
        "evidence": {
            "final_url": "https://vendor-a.example/legal/data-processing-addendum",
            "http_status": 200,
            "matched_terms": ["data processing", "processor"],
        },
    }

    payload = build([source("not_found")], source_discovery_report=discovery_candidate_report(candidate))

    assert payload["strict_repair_ready"] == []
    item = payload["human_review_required"][0]
    assert "suspect_inferred_url" in item["reason_codes"]
    assert "replacement_candidate_not_strict" in item["reason_codes"]


def test_redirect_canonical_drift_does_not_enter_strict_repair_ready():
    row = strict_source(
        replacement_verification_status="redirected",
        replacement_source_url="https://vendor-a.example/dpa",
        replacement_final_url="https://vendor-a.example/legal/dpa",
    )

    payload = build([row])

    assert payload["strict_repair_ready"] == []
    assert payload["human_review_required"][0]["redirect_canonical_drift"] is True
    assert "redirect_canonical_drift" in payload["human_review_required"][0]["reason_codes"]


def test_weak_semantic_match_does_not_enter_strict_repair_ready():
    payload = build([strict_source(replacement_semantic_status="weak")])

    assert payload["strict_repair_ready"] == []
    assert "weak_semantic_match" in payload["human_review_required"][0]["reason_codes"]


def test_unknown_status_enters_human_review_required_and_never_strict_repair_ready():
    payload = build([source("new_future_status")])

    assert payload["strict_repair_ready"] == []
    assert payload["human_review_required"][0]["bucket"] == "human_review_required"
    assert "unknown_verification_status" in payload["human_review_required"][0]["reason_codes"]


def test_deterministic_stable_ordering():
    rows = [
        source("not_found", "vendor-c"),
        source("possible_mismatch", "vendor-a"),
        strict_source(vendor_id="vendor-b", source_id="vendor-b-dpa"),
    ]

    first = build(rows)
    second = build(list(reversed(rows)))

    assert [(row["bucket"], row["vendor_id"]) for row in first["records"]] == [
        ("human_review_required", "vendor-a"),
        ("no_replacement_found", "vendor-c"),
        ("strict_repair_ready", "vendor-b"),
    ]
    assert first["records"] == second["records"]


def test_csv_outputs_have_expected_columns(tmp_path: Path):
    source_path = tmp_path / "source-verification-report.json"
    source_path.write_text(json.dumps(report([strict_source(), source("not_found", "vendor-b")])), encoding="utf-8")
    json_path = tmp_path / "source-repair-sweep-report.json"
    strict_csv = tmp_path / "source-repair-sweep-strict-candidates.csv"
    human_csv = tmp_path / "source-repair-sweep-human-review.csv"
    no_replacement_csv = tmp_path / "source-repair-sweep-no-replacement.csv"
    markdown_path = tmp_path / "source-repair-sweep-summary.md"

    assert main(
        [
            "build",
            "--source-verification-report",
            str(source_path),
            "--json-output",
            str(json_path),
            "--strict-csv-output",
            str(strict_csv),
            "--human-review-csv-output",
            str(human_csv),
            "--no-replacement-csv-output",
            str(no_replacement_csv),
            "--markdown-output",
            str(markdown_path),
        ]
    ) == 0

    for path in (strict_csv, human_csv, no_replacement_csv):
        with path.open("r", encoding="utf-8", newline="") as handle:
            assert csv.DictReader(handle).fieldnames == CSV_FIELDS
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["total_sources_seen"] == 2
    assert "# OpenVA Source Repair Sweep Summary" in markdown_path.read_text(encoding="utf-8")


def test_report_contains_no_self_certifying_fields():
    payload = build([strict_source(eligible=True, eligible_for_automerge=True, tool_recommendation="automerge")])

    assert not {"eligible", "eligible_for_automerge", "tool_recommendation"} & recursive_keys(payload)
    assert "self_certifying_field_present" in payload["human_review_required"][0]["reason_codes"]
    assert "replacement_candidate_not_strict" in payload["human_review_required"][0]["reason_codes"]
