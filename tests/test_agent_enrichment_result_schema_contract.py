"""Contract tests for the preferred agent enrichment result fields."""

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA = json.loads((ROOT / "schemas/openva/agent-enrichment-result.schema.json").read_text(encoding="utf-8"))


def _valid_result():
    return {
        "row_id": "1",
        "input": {
            "vendor_name": "Example Vendor",
            "domain": "vendor.example",
            "business_entity_name": None,
            "registration_number": None,
        },
        "identity": {
            "match_status": "match",
            "matched_vendor_id": "example-vendor",
            "matched_vendor_name": "Example Vendor",
            "match_basis": ["domain_exact"],
            "no_match_reason": None,
        },
        "source_references": {
            "dpa": {
                "status": "indexed",
                "source_type": "dpa",
                "url": "https://vendor.example/legal/dpa",
                "title": None,
                "source_id": "example-vendor-dpa",
            },
            "trust_center": {
                "status": "not_indexed",
                "source_type": "trust_center",
                "url": None,
                "title": None,
                "source_id": None,
            },
        },
        "match": {
            "status": "matched",
            "method": "domain_exact",
            "confidence": 1.0,
            "vendor_id": "example-vendor",
            "display_name": "Example Vendor",
            "candidates": [],
        },
        "sources": [],
        "primary_source_by_type": {},
        "source_urls_by_type": {},
        "notes": [],
        "not_advice": True,
    }


def test_schema_requires_preferred_agent_fields():
    assert "identity" in RESULT_SCHEMA["required"]
    assert "source_references" in RESULT_SCHEMA["required"]
    jsonschema.validate(_valid_result(), RESULT_SCHEMA)


@pytest.mark.parametrize("field", ["identity", "source_references"])
def test_schema_rejects_results_missing_preferred_agent_fields(field):
    result = _valid_result()
    result.pop(field)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, RESULT_SCHEMA)


def test_identity_schema_rejects_ambiguous_as_top_level_status():
    result = _valid_result()
    result["identity"] = {
        "match_status": "ambiguous",
        "matched_vendor_id": None,
        "matched_vendor_name": None,
        "match_basis": [],
        "no_match_reason": "multiple_plausible_entities",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, RESULT_SCHEMA)


def test_identity_schema_accepts_ambiguous_as_no_match_reason():
    result = _valid_result()
    result["identity"] = {
        "match_status": "no_match",
        "matched_vendor_id": None,
        "matched_vendor_name": None,
        "match_basis": [],
        "no_match_reason": "multiple_plausible_entities",
    }
    jsonschema.validate(result, RESULT_SCHEMA)


def test_source_reference_schema_rejects_unpublished_status():
    result = _valid_result()
    result["source_references"]["dpa"]["status"] = "verified_live"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, RESULT_SCHEMA)


def test_entity_resolution_schema_is_optional_for_compact_default_results():
    assert "entity_resolution" not in RESULT_SCHEMA["required"]
    jsonschema.validate(_valid_result(), RESULT_SCHEMA)


def test_entity_resolution_schema_accepts_compact_resolved_entity_status():
    result = _valid_result()
    result["entity_resolution"] = {
        "status": "resolved",
        "matched_entity_id": "example-vendor-ltd",
        "candidate_entity_ids": [],
        "review_required": False,
        "reason_code": "identifier_exact_match",
    }
    jsonschema.validate(result, RESULT_SCHEMA)


def test_entity_resolution_schema_accepts_compact_ambiguous_entity_status():
    result = _valid_result()
    result["entity_resolution"] = {
        "status": "ambiguous",
        "matched_entity_id": None,
        "candidate_entity_ids": [
            "example-vendor-us-inc",
            "example-vendor-eu-limited",
        ],
        "review_required": True,
        "reason_code": "brand_only_multiple_entities",
    }
    jsonschema.validate(result, RESULT_SCHEMA)


def test_entity_resolution_schema_rejects_embedded_diagnostic_evidence():
    result = _valid_result()
    result["entity_resolution"] = {
        "status": "resolved",
        "matched_entity_id": "example-vendor-ltd",
        "candidate_entity_ids": [],
        "review_required": False,
        "reason_code": "identifier_exact_match",
        "official_source_ids": ["example-registry"],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, RESULT_SCHEMA)


def test_compatibility_fields_remain_required_for_existing_adapters():
    for field in ("match", "sources", "primary_source_by_type", "source_urls_by_type"):
        assert field in RESULT_SCHEMA["required"]
        result = _valid_result()
        result.pop(field)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(result, RESULT_SCHEMA)
