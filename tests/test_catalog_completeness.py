from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

from tools.openva.catalog_completeness import CSV_FIELDS, build_catalog_completeness, main


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def vendor(root: Path, vendor_id: str, **overrides) -> None:
    payload = {
        "schema_version": "0.1.0",
        "vendor_id": vendor_id,
        "display_name": vendor_id.title(),
        "legal_name": f"{vendor_id.title()} Inc.",
        "headquarters_country": "US",
        "regions_served": ["global"],
        "public_entrypoints": [f"https://{vendor_id}.example"],
        "vendor_categories": ["productivity_software"],
    }
    payload.update(overrides)
    write_yaml(root / "data" / "vendors" / vendor_id / "vendor.yaml", payload)


def source(root: Path, vendor_id: str, source_type: str, source_id: str | None = None) -> None:
    resolved_id = source_id or f"{vendor_id}-{source_type}"
    write_yaml(
        root / "data" / "vendors" / vendor_id / "sources" / f"{resolved_id}.yaml",
        {
            "schema_version": "0.1.0",
            "vendor_id": vendor_id,
            "source_id": resolved_id,
            "source_type": source_type,
            "source_url": f"https://{vendor_id}.example/{source_type}",
            "access_class": "public_web",
            "rights_class": "metadata_only",
            "not_advice": True,
        },
    )


def complete_vendor(root: Path, vendor_id: str = "complete") -> None:
    vendor(root, vendor_id)
    for source_type in [
        "privacy_notice",
        "dpa",
        "subprocessors_list",
        "security_page",
        "compliance_page",
    ]:
        source(root, vendor_id, source_type)


def by_vendor(report: dict, vendor_id: str) -> dict:
    return next(vendor for vendor in report["vendors"] if vendor["vendor_id"] == vendor_id)


def test_detects_missing_expected_source_types(tmp_path: Path):
    vendor(tmp_path, "partial")
    source(tmp_path, "partial", "privacy_notice")

    report = build_catalog_completeness(tmp_path, generated_at="2026-05-25T00:00:00Z")
    row = by_vendor(report, "partial")

    assert row["has_privacy_notice_source"] is True
    assert row["has_dpa_source"] is False
    assert row["has_subprocessor_source"] is False
    assert row["has_security_source"] is False
    assert row["has_compliance_source"] is False
    assert row["missing_expected_sources"] == [
        "dpa",
        "subprocessors_list",
        "security",
        "compliance",
    ]
    assert report["summary"]["missing_dpa_count"] == 1
    assert report["summary"]["missing_subprocessor_count"] == 1
    assert report["summary"]["missing_security_count"] == 1
    assert report["summary"]["missing_compliance_count"] == 1


def test_computes_source_count_and_deterministic_bucket(tmp_path: Path):
    complete_vendor(tmp_path, "complete")
    vendor(tmp_path, "entityless", legal_name=None)
    source(tmp_path, "entityless", "privacy_notice")
    vendor(tmp_path, "minimal")

    report = build_catalog_completeness(tmp_path, generated_at="2026-05-25T00:00:00Z")

    assert [vendor["vendor_id"] for vendor in report["vendors"]] == ["complete", "entityless", "minimal"]
    assert by_vendor(report, "complete")["source_count"] == 5
    assert by_vendor(report, "complete")["completeness_bucket"] == "complete_enough_for_review"
    assert by_vendor(report, "entityless")["completeness_bucket"] == "entity_review_needed"
    assert by_vendor(report, "minimal")["completeness_bucket"] == "minimal"


def test_cli_emits_json_csv_and_markdown(tmp_path: Path):
    complete_vendor(tmp_path, "complete")
    report_path = tmp_path / "catalog-completeness-report.json"
    csv_path = tmp_path / "catalog-completeness-vendors.csv"
    markdown_path = tmp_path / "catalog-completeness-summary.md"

    assert main([
        "build",
        "--root",
        str(tmp_path),
        "--output",
        str(report_path),
        "--csv-output",
        str(csv_path),
        "--markdown-output",
        str(markdown_path),
    ]) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["vendor_count"] == 1
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_FIELDS
        rows = list(reader)
    assert rows[0]["completeness_bucket"] == "complete_enough_for_review"
    assert "# OpenVA Catalog Completeness Audit" in markdown_path.read_text(encoding="utf-8")


def test_report_is_static_non_advisory_and_has_no_prohibited_wording(tmp_path: Path):
    complete_vendor(tmp_path, "complete")

    report = build_catalog_completeness(tmp_path, generated_at="2026-05-25T00:00:00Z")
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "non_advisory": True,
    }
    text = json.dumps(report, sort_keys=True).lower()
    for prohibited in ["trusted", "approved", "safe", "compliant", "canonical"]:
        assert prohibited not in text
