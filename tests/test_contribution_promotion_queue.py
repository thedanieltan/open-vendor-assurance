from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva.contribution_promotion_queue import build_contribution_promotion_queue


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_vendor(root: Path, vendor_id: str = "stripe") -> None:
    write_yaml(
        root / "data/vendors" / vendor_id / "vendor.yaml",
        {
            "vendor_id": vendor_id,
            "display_name": "Stripe",
            "legal_name": "Stripe, Inc.",
            "headquarters_country": "US",
            "regions_served": ["global"],
            "official_domains": ["stripe.com"],
            "public_entrypoints": ["https://stripe.com"],
            "vendor_categories": ["payments"],
        },
    )


def intake_report(url: str = "https://stripe.com/legal/dpa") -> dict:
    return {
        "schema_version": "0.1.0",
        "report_type": "contribution_intake_agent",
        "issue_number": 42,
        "vendor": {"vendor_id": "stripe", "display_name": "Stripe"},
        "decision": "open_catalog_pr",
        "checks": [
            {
                "url": url,
                "passed": True,
                "network_verification": {
                    "verification_status": "ok",
                    "http_status": 200,
                    "final_url": url,
                    "title_detected": "Stripe Data Processing Addendum",
                    "observed_at": "2026-05-23T00:00:00Z",
                },
            }
        ],
        "proposed_sources": [
            {
                "source_id": "stripe-dpa",
                "source_type": "dpa",
                "source_url": url,
                "title_native": "Stripe Data Processing Addendum",
                "title_en": "Stripe Data Processing Addendum",
                "source_language": "en",
                "source_authority_class": "vendor_published",
                "access_class": "public_web",
                "rights_class": "metadata_only",
            }
        ],
    }


def test_queue_promotes_verified_public_same_domain_source(tmp_path):
    add_vendor(tmp_path)
    report_path = tmp_path / "reports/intake-42.json"
    write_json(report_path, intake_report())

    queue = build_contribution_promotion_queue(root=tmp_path, intake_paths=[report_path])

    assert queue["summary"]["submitted_candidates"] == 1
    assert queue["summary"]["deduplicated_candidates"] == 1
    assert queue["summary"]["machine_validated_promotions"] == 1
    assert queue["summary"]["human_review_required"] == 0
    item = queue["machine_validated_promotions"][0]
    assert item["source"]["catalog_tier"] == "machine_validated"
    assert item["source"]["review_state"] == "auto_validated"
    assert item["source"]["advisory_boundary"] == "non_advisory"
    assert item["source"]["not_advice"] is True


def test_queue_deduplicates_repeated_contributor_submissions(tmp_path):
    add_vendor(tmp_path)
    first = tmp_path / "reports/intake-1.json"
    second = tmp_path / "reports/intake-2.json"
    write_json(first, intake_report())
    duplicated = intake_report()
    duplicated["issue_number"] = 43
    write_json(second, duplicated)

    queue = build_contribution_promotion_queue(root=tmp_path, intake_paths=[tmp_path / "reports"])

    assert queue["summary"]["submitted_candidates"] == 2
    assert queue["summary"]["deduplicated_candidates"] == 1
    assert queue["summary"]["machine_validated_promotions"] == 1
    assert len(queue["machine_validated_promotions"][0]["submissions"]) == 2


def test_queue_sends_missing_verification_to_human_review(tmp_path):
    add_vendor(tmp_path)
    report = intake_report()
    report["checks"] = []
    report_path = tmp_path / "reports/intake-42.json"
    write_json(report_path, report)

    queue = build_contribution_promotion_queue(root=tmp_path, intake_paths=[report_path])

    assert queue["summary"]["machine_validated_promotions"] == 0
    assert queue["summary"]["human_review_required"] == 1
    assert "verification_not_successful" in queue["human_review_required"][0]["reasons"]


def test_queue_rejects_advisory_contributor_text(tmp_path):
    add_vendor(tmp_path)
    report = intake_report()
    report["proposed_sources"][0]["title_en"] = "Stripe approved low risk vendor"
    report["proposed_sources"][0]["title_native"] = "Stripe approved low risk vendor"
    report_path = tmp_path / "reports/intake-42.json"
    write_json(report_path, report)

    queue = build_contribution_promotion_queue(root=tmp_path, intake_paths=[report_path])

    assert queue["summary"]["machine_validated_promotions"] == 0
    assert queue["summary"]["rejected"] == 1
    assert "advisory_wording_present" in queue["rejected"][0]["reasons"]


def test_queue_reads_catalog_batch_yaml(tmp_path):
    batch_path = tmp_path / "catalog-batches/intake/batch.yaml"
    write_yaml(
        batch_path,
        {
            "schema_version": "0.1.0",
            "batch_id": "intake-batch",
            "collected_at": "2026-05-23T00:00:00Z",
            "vendors": [
                {
                    "vendor_id": "stripe",
                    "display_name": "Stripe",
                    "official_domains": ["stripe.com"],
                    "sources": [
                        {
                            "source_id": "stripe-privacy",
                            "source_type": "privacy_notice",
                            "source_url": "https://stripe.com/privacy",
                            "title_native": "Stripe Privacy Notice",
                            "title_en": "Stripe Privacy Notice",
                            "verification_status": "ok",
                            "http_status": 200,
                            "final_url": "https://stripe.com/privacy",
                        }
                    ],
                }
            ],
        },
    )

    queue = build_contribution_promotion_queue(root=tmp_path, batch_paths=[batch_path])

    assert queue["summary"]["machine_validated_promotions"] == 1
    assert queue["machine_validated_promotions"][0]["source"]["source_type"] == "privacy_notice"


def test_queue_emits_observation_for_verification_result(tmp_path):
    add_vendor(tmp_path)
    report_path = tmp_path / "reports/intake-42.json"
    write_json(report_path, intake_report())

    queue = build_contribution_promotion_queue(root=tmp_path, intake_paths=[report_path])

    assert queue["summary"]["observations"] == 1
    observation = queue["observations"][0]
    assert observation["canonical"] is False
    assert observation["catalog_tier"] == "observation"
    assert observation["review_state"] == "auto_observed"
    assert observation["advisory_boundary"] == "non_advisory"
