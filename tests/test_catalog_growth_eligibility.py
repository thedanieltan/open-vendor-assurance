import csv
import json
from pathlib import Path

from tools.openva.catalog_growth_eligibility import (
    REJECT_EXISTING_VENDOR,
    REJECT_NO_PUBLIC_SOURCE,
    REJECT_WEAK_SEMANTIC_MATCH,
    REVIEW_REQUIRED,
    STRICT_PROMOTE_READY,
    build_catalog_growth_eligibility,
    write_outputs,
)


def vendor(candidate_vendor_id="vendor-a", domain="vendor-a.example", **updates):
    row = {
        "candidate_vendor_id": candidate_vendor_id,
        "display_name_candidate": "Vendor A",
        "official_domain_candidate": domain,
        "coverage_lane": "security",
        "cohort_id": "security-001",
        "requires_review": True,
        "writes_canonical_vendors": False,
        "non_advisory": True,
    }
    row.update(updates)
    return row


def source(vendor_id="vendor-a", confidence="likely", http_status=200, matched_terms=None, **updates):
    row = {
        "candidate_source_id": f"{vendor_id}-security-page-candidate",
        "vendor_id": vendor_id,
        "source_type_candidate": "security_page",
        "candidate_url": f"https://{vendor_id}.example/security",
        "confidence": confidence,
        "requires_review": True,
        "not_advice": True,
        "evidence": {
            "http_status": http_status,
            "final_url": f"https://{vendor_id}.example/security",
            "matched_terms": matched_terms if matched_terms is not None else ["security"],
            "page_title": "Security",
        },
    }
    row.update(updates)
    return row


def vendor_report(rows):
    return {
        "schema_version": "0.1.0",
        "report_type": "vendor_candidate_discovery_report",
        "vendor_candidates": rows,
    }


def source_report(vendors):
    return {
        "schema_version": "0.1.0",
        "report_type": "source_discovery_report",
        "vendors": vendors,
    }


def test_strict_candidate_is_reported_as_promote_ready(tmp_path: Path):
    report = build_catalog_growth_eligibility(
        vendor_report([vendor()]),
        source_report([{"vendor_id": "vendor-a", "candidates": [source()], "observations": []}]),
        root=tmp_path,
        generated_at="2026-05-26T00:00:00Z",
    )

    assert report["summary"]["strict_promote_ready_count"] == 1
    assert report["items"][0]["classification"] == STRICT_PROMOTE_READY
    assert report["strict_promotions"][0]["posture"]["writes_canonical_sources"] is False
    assert report["posture"]["writes_repository_state"] is False


def test_candidate_without_source_is_rejected_as_no_public_source(tmp_path: Path):
    report = build_catalog_growth_eligibility(
        vendor_report([vendor()]),
        source_report([]),
        root=tmp_path,
        generated_at="2026-05-26T00:00:00Z",
    )

    assert report["items"][0]["classification"] == REJECT_NO_PUBLIC_SOURCE
    assert report["items"][0]["promotable_now"] is False


def test_weak_source_candidate_is_not_promoted(tmp_path: Path):
    report = build_catalog_growth_eligibility(
        vendor_report([vendor()]),
        source_report([{"vendor_id": "vendor-a", "candidates": [source(confidence="candidate", matched_terms=[])], "observations": []}]),
        root=tmp_path,
        generated_at="2026-05-26T00:00:00Z",
    )

    assert report["items"][0]["classification"] == REJECT_WEAK_SEMANTIC_MATCH
    assert report["summary"]["strict_promotion_action_count"] == 0


def test_advisory_wording_candidate_is_deferred_before_promotion(tmp_path: Path):
    advisory_source = source()
    advisory_source["evidence"]["page_title"] = "Cloud Security | How Example Keeps Your Data Safe"

    report = build_catalog_growth_eligibility(
        vendor_report([vendor()]),
        source_report([{"vendor_id": "vendor-a", "candidates": [advisory_source], "observations": []}]),
        root=tmp_path,
        generated_at="2026-05-26T00:00:00Z",
    )

    assert report["items"][0]["classification"] == REVIEW_REQUIRED
    assert "strict_growth_advisory_wording_detected:safe" in report["items"][0]["reason_codes"]
    assert report["summary"]["strict_promotion_action_count"] == 0
    assert report["strict_promotions"] == []


def test_strict_sources_are_capped_and_deferred_deterministically(tmp_path: Path):
    dpa = source()
    dpa["candidate_source_id"] = "vendor-a-dpa-candidate"
    dpa["source_type_candidate"] = "dpa"
    dpa["candidate_url"] = "https://vendor-a.example/dpa"
    dpa["evidence"]["page_title"] = "Data Processing Addendum"
    privacy = source()
    privacy["candidate_source_id"] = "vendor-a-privacy-notice-candidate"
    privacy["source_type_candidate"] = "privacy_notice"
    privacy["candidate_url"] = "https://vendor-a.example/privacy"
    privacy["evidence"]["page_title"] = "Privacy Notice"
    security = source()
    security["candidate_source_id"] = "vendor-a-security-page-candidate"
    security["source_type_candidate"] = "security_page"
    security["candidate_url"] = "https://vendor-a.example/security"

    report = build_catalog_growth_eligibility(
        vendor_report([vendor()]),
        source_report([{"vendor_id": "vendor-a", "candidates": [security, privacy, dpa], "observations": []}]),
        root=tmp_path,
        generated_at="2026-05-26T00:00:00Z",
    )

    item = report["items"][0]
    promoted_types = [action["source"]["source_type_candidate"] for action in report["strict_promotions"]]

    assert item["classification"] == STRICT_PROMOTE_READY
    assert promoted_types == ["dpa", "privacy_notice"]
    assert item["strict_source_count"] == 2
    assert "strict_growth_vendor_source_cap_exceeded" in item["reason_codes"]
    assert item["deferred_strict_sources"] == [
        {
            "candidate_source_id": "vendor-a-security-page-candidate",
            "source_type_candidate": "security_page",
            "candidate_url": "https://vendor-a.example/security",
            "reason_codes": ["strict_growth_vendor_source_cap_exceeded"],
        }
    ]


def test_existing_vendor_is_rejected(tmp_path: Path):
    vendor_dir = tmp_path / "data" / "vendors" / "vendor-a"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "vendor.yaml").write_text(
        "vendor_id: vendor-a\nofficial_domains:\n  - vendor-a.example\npublic_entrypoints:\n  - https://vendor-a.example\n",
        encoding="utf-8",
    )

    report = build_catalog_growth_eligibility(
        vendor_report([vendor()]),
        source_report([{"vendor_id": "vendor-a", "candidates": [source()], "observations": []}]),
        root=tmp_path,
        generated_at="2026-05-26T00:00:00Z",
    )

    assert report["items"][0]["classification"] == REJECT_EXISTING_VENDOR
    assert report["summary"]["strict_promote_ready_count"] == 0


def test_writer_outputs_report_csv_and_markdown(tmp_path: Path):
    report = build_catalog_growth_eligibility(
        vendor_report([vendor(), vendor("vendor-b", "vendor-b.example")]),
        source_report([{"vendor_id": "vendor-a", "candidates": [source()], "observations": []}]),
        root=tmp_path,
        generated_at="2026-05-26T00:00:00Z",
    )
    output_json = tmp_path / "catalog-growth-eligibility-report.json"
    output_strict = tmp_path / "catalog-growth-strict-promotions.json"
    output_review = tmp_path / "catalog-growth-review-required.csv"
    output_rejected = tmp_path / "catalog-growth-rejected.csv"
    output_md = tmp_path / "catalog-growth-eligibility-summary.md"

    write_outputs(report, output_json, output_strict, output_review, output_rejected, output_md)

    assert json.loads(output_json.read_text(encoding="utf-8"))["summary"]["candidate_count"] == 2
    assert json.loads(output_strict.read_text(encoding="utf-8"))["summary"]["action_count"] == 1
    with output_rejected.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["classification"] == REJECT_NO_PUBLIC_SOURCE
    assert "Catalog Growth Eligibility Summary" in output_md.read_text(encoding="utf-8")
