from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva.field_provenance import CSV_FIELDS, build_field_provenance_coverage, main

ROOT = Path(__file__).resolve().parents[1]


def schema_errors(instance: dict) -> list:
    schema = json.loads((ROOT / "schemas/openva/field-provenance.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return sorted(validator.iter_errors(instance), key=lambda error: list(error.path))


def valid_provenance() -> dict:
    return {
        "schema_version": "0.1.0",
        "provenance_id": "example-legal-entity-name",
        "vendor_id": "example",
        "field_name": "legal_entity_name",
        "field_value": "Example Inc.",
        "source_id": "example-privacy",
        "source_url": "https://example.com/privacy",
        "extracted_at": "2026-05-25T00:00:00Z",
        "extraction_method": "manual_review",
        "review_state": "human_reviewed",
        "confidence": "high",
        "notes": None,
        "not_advice": True,
    }


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def vendor(root: Path, vendor_id: str) -> None:
    write_yaml(
        root / "data" / "vendors" / vendor_id / "vendor.yaml",
        {
            "schema_version": "0.1.0",
            "vendor_id": vendor_id,
            "display_name": vendor_id.title(),
            "legal_name": f"{vendor_id.title()} Inc.",
            "official_domains": [f"{vendor_id}.example"],
            "not_advice": True,
        },
    )


def provenance(root: Path, vendor_id: str, field_name: str) -> None:
    payload = valid_provenance()
    payload.update(
        {
            "provenance_id": f"{vendor_id}-{field_name.replace('_', '-')}",
            "vendor_id": vendor_id,
            "field_name": field_name,
            "field_value": f"{vendor_id} {field_name}",
        }
    )
    write_yaml(root / "data" / "vendors" / vendor_id / "provenance" / f"{payload['provenance_id']}.yaml", payload)


def test_valid_field_provenance_passes_schema():
    assert schema_errors(valid_provenance()) == []


def test_sourced_field_provenance_requires_source_id_and_source_url():
    instance = valid_provenance()
    instance.pop("source_id")

    assert schema_errors(instance) != []

    instance = valid_provenance()
    instance.pop("source_url")

    assert schema_errors(instance) != []


def test_invalid_review_state_and_confidence_fail_schema():
    instance = valid_provenance()
    instance["review_state"] = "reviewed"
    assert schema_errors(instance) != []

    instance = valid_provenance()
    instance["confidence"] = "certain"
    assert schema_errors(instance) != []


def test_inferred_field_can_omit_source_id_and_url():
    instance = valid_provenance()
    instance["extraction_method"] = "inferred"
    instance.pop("source_id")
    instance.pop("source_url")
    instance["review_state"] = "needs_review"
    instance["confidence"] = "low"

    assert schema_errors(instance) == []


def test_generated_coverage_report_detects_missing_provenance(tmp_path: Path):
    vendor(tmp_path, "complete")
    for field_name in [
        "legal_entity_name",
        "homepage_url",
        "privacy_notice_url",
        "dpa_url",
        "subprocessor_url",
        "security_url",
        "compliance_url",
        "certification_claims",
        "data_processing_region",
    ]:
        provenance(tmp_path, "complete", field_name)
    vendor(tmp_path, "missing")

    report = build_field_provenance_coverage(tmp_path, generated_at="2026-05-25T00:00:00Z")

    complete = next(row for row in report["vendors"] if row["vendor_id"] == "complete")
    missing = next(row for row in report["vendors"] if row["vendor_id"] == "missing")
    assert complete["coverage_bucket"] == "strong"
    assert complete["requires_human_review"] is False
    assert missing["coverage_bucket"] == "missing"
    assert missing["requires_human_review"] is True


def test_cli_writes_coverage_json_csv_and_markdown(tmp_path: Path):
    vendor(tmp_path, "example")
    provenance(tmp_path, "example", "legal_entity_name")
    output = tmp_path / "field-provenance-coverage.json"
    csv_output = tmp_path / "field-provenance-coverage.csv"
    markdown_output = tmp_path / "field-provenance-summary.md"

    assert main([
        "coverage",
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
    assert payload["summary"]["field_provenance_record_count"] == 1
    with csv_output.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == CSV_FIELDS
        assert list(reader)[0]["coverage_bucket"] == "partial"
    assert "# OpenVA Field Provenance Coverage" in markdown_output.read_text(encoding="utf-8")
