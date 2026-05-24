from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

from tools.openva.entity_review_queue import CSV_FIELDS, build_entity_review_queue, main


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def vendor(root: Path, vendor_id: str, **overrides) -> None:
    payload = {
        "schema_version": "0.1.0",
        "vendor_id": vendor_id,
        "display_name": "Example Vendor",
        "legal_name": "Example Vendor, Inc.",
        "headquarters_country": "US",
        "regions_served": ["global"],
        "vendor_categories": ["productivity_software"],
        "entity_surface": "operating_entity",
    }
    payload.update(overrides)
    write_yaml(root / "data" / "vendors" / vendor_id / "vendor.yaml", payload)


def source(root: Path, vendor_id: str, title: str) -> None:
    write_yaml(
        root / "data" / "vendors" / vendor_id / "sources" / f"{vendor_id}-privacy.yaml",
        {
            "schema_version": "0.1.0",
            "vendor_id": vendor_id,
            "source_id": f"{vendor_id}-privacy",
            "source_type": "privacy_notice",
            "title_en": title,
            "source_url": f"https://{vendor_id}.example/privacy",
            "not_advice": True,
        },
    )


def issue_types(report: dict, vendor_id: str) -> list[str]:
    return [item["issue_type"] for item in report["items"] if item["vendor_id"] == vendor_id]


def test_missing_legal_entity_queues_record(tmp_path: Path):
    vendor(tmp_path, "missing", legal_name=None)

    report = build_entity_review_queue(tmp_path, generated_at="2026-05-25T00:00:00Z")

    assert issue_types(report, "missing") == ["missing_legal_entity"]
    item = report["items"][0]
    assert item["requires_human_review"] is True
    assert "contracting legal entity" in item["recommended_review_action"]


def test_brand_entity_ambiguity_queues_record_from_catalog(tmp_path: Path):
    vendor(tmp_path, "brand", display_name="Akur8", legal_name="Akur8")

    report = build_entity_review_queue(tmp_path, generated_at="2026-05-25T00:00:00Z")

    assert issue_types(report, "brand") == ["brand_entity_ambiguity"]


def test_source_entity_mismatch_possible_queues_record(tmp_path: Path):
    vendor(tmp_path, "vendor", display_name="Vendor", legal_name="Vendor Inc.")
    source(tmp_path, "vendor", "Other Entity LLC Privacy Notice")

    report = build_entity_review_queue(tmp_path, generated_at="2026-05-25T00:00:00Z")

    assert issue_types(report, "vendor") == ["source_entity_mismatch_possible"]


def test_clean_entity_record_not_queued(tmp_path: Path):
    vendor(tmp_path, "clean", display_name="Clean", legal_name="Clean Inc.")
    source(tmp_path, "clean", "Clean Privacy Notice")

    report = build_entity_review_queue(tmp_path, generated_at="2026-05-25T00:00:00Z")

    assert report["items"] == []


def test_deterministic_ordering_and_guardrail_posture(tmp_path: Path):
    vendor(tmp_path, "zeta", legal_name=None)
    vendor(tmp_path, "alpha", display_name="Alpha", legal_name="Alpha")

    report = build_entity_review_queue(tmp_path, generated_at="2026-05-25T00:00:00Z")

    assert [(item["vendor_id"], item["issue_type"]) for item in report["items"]] == [
        ("alpha", "brand_entity_ambiguity"),
        ("zeta", "missing_legal_entity"),
    ]
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "requires_human_review": True,
        "non_advisory": True,
    }


def test_cli_writes_json_csv_and_markdown(tmp_path: Path):
    vendor(tmp_path, "missing", legal_name=None)
    output = tmp_path / "entity-review-queue.json"
    csv_output = tmp_path / "entity-review-queue.csv"
    markdown_output = tmp_path / "entity-review-summary.md"

    assert main([
        "build",
        "--root",
        str(tmp_path),
        "--output",
        str(output),
        "--csv-output",
        str(csv_output),
        "--markdown-output",
        str(markdown_output),
    ]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["queued_vendor_issue_count"] == 1
    with csv_output.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_FIELDS
        assert list(reader)[0]["issue_type"] == "missing_legal_entity"
    assert "# OpenVA Entity Review Queue" in markdown_output.read_text(encoding="utf-8")
