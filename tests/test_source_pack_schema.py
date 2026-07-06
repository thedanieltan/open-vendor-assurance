from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/openva/source-pack-result.schema.json"

REQUIRED_SOURCE_FIELDS = {
    "match_status",
    "source_type",
    "source_url",
    "result_state",
    "mode",
    "confidence",
    "public_access_status",
    "checked_at",
    "snapshot_id",
    "candidate_queued",
    "not_advice",
}

FORBIDDEN_ADVISORY_TERMS = {
    "approved",
    "recommended",
    "risk_score",
    "risk_rating",
    "compliance_decision",
    "security_decision",
    "legal_opinion",
    "vendor_approval",
    "suitability",
}


def load_schema() -> dict[str, Any]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert isinstance(schema, dict)
    return schema


def validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def valid_source_pack() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "source_pack_id": "source-pack-examplecloud-2026-07-06",
        "snapshot_id": "sha256:example-snapshot",
        "mode": "cached_only",
        "vendor_input": {
            "display_name": "ExampleCloud",
            "business_entity_name": "ExampleCloud Inc.",
            "domain": "examplecloud.com",
            "jurisdiction": "US",
            "registration_number": None,
            "registered_address": None,
        },
        "matched_vendor": {
            "vendor_id": "examplecloud",
            "display_name": "ExampleCloud",
            "legal_name": "ExampleCloud Inc.",
            "official_domain": "examplecloud.com",
        },
        "match_status": "matched",
        "requested_source_types": ["dpa", "privacy_notice", "subprocessors_list", "security_page"],
        "sources": [
            {
                "match_status": "matched",
                "source_type": "dpa",
                "source_url": "https://examplecloud.com/legal/dpa",
                "candidate_url": None,
                "result_state": "found",
                "mode": "cached_only",
                "confidence": "high",
                "public_access_status": "public",
                "checked_at": None,
                "snapshot_id": "sha256:example-snapshot",
                "candidate_queued": False,
                "not_advice": True,
                "notes": ["Public vendor-published source reference found."],
            }
        ],
        "missing_source_types": ["security_page"],
        "ambiguous_source_types": [],
        "notes": ["Browser-local cached result; no live source check performed."],
        "not_advice": True,
    }


def test_source_pack_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_schema())


def test_source_pack_source_rows_require_phase_3_contract_fields() -> None:
    schema = load_schema()
    source_required = set(schema["$defs"]["source_pack_source"]["required"])

    assert REQUIRED_SOURCE_FIELDS <= source_required


def test_valid_source_pack_example_validates() -> None:
    errors = sorted(validator().iter_errors(valid_source_pack()), key=lambda error: list(error.path))

    assert errors == []


def test_source_pack_requires_not_advice_at_root_and_source_level() -> None:
    pack = valid_source_pack()
    pack["not_advice"] = False
    pack["sources"][0]["not_advice"] = False

    messages = [error.message for error in validator().iter_errors(pack)]

    assert "True was expected" in messages
    assert len([message for message in messages if message == "True was expected"]) == 2


def test_source_pack_contract_rejects_advisory_fields() -> None:
    pack = valid_source_pack()
    pack["risk_score"] = 0.1
    pack["sources"][0]["approved"] = True

    errors = sorted(validator().iter_errors(pack), key=lambda error: list(error.path))
    paths = {tuple(error.path) for error in errors}

    assert () in paths
    assert ("sources", 0) in paths


def test_source_pack_vocabulary_matches_resolver_first_public_states() -> None:
    schema = load_schema()

    assert set(schema["$defs"]["match_status"]["enum"]) == {"matched", "ambiguous", "no_match"}
    assert set(schema["$defs"]["mode"]["enum"]) == {"cached_only", "checked_on_demand", "discovered"}
    assert set(schema["$defs"]["result_state"]["enum"]) == {
        "found",
        "missing",
        "ambiguous",
        "unavailable",
        "gated",
        "candidate_found",
        "not_checked_live",
    }
    assert set(schema["$defs"]["confidence"]["enum"]) == {"high", "medium", "low", "none"}
    assert set(schema["$defs"]["public_access_status"]["enum"]) == {
        "public",
        "gated",
        "unavailable",
        "ambiguous",
        "unknown",
    }


def test_source_pack_schema_text_does_not_publish_advisory_contract_terms() -> None:
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8").lower()

    for forbidden in FORBIDDEN_ADVISORY_TERMS:
        assert forbidden not in schema_text
