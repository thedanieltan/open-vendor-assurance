import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas/openva" / name).read_text(encoding="utf-8"))


def assert_valid(schema_name: str, instance: dict) -> None:
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda err: list(err.path))
    assert errors == []


def assert_invalid(schema_name: str, instance: dict) -> None:
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda err: list(err.path))
    assert errors != []


def valid_vendor_profile() -> dict:
    return {
        "schema_version": "0.1.0",
        "vendor_id": "example",
        "display_name": "Example",
        "legal_name": "Example Inc.",
        "headquarters_country": "US",
        "official_domains": ["example.com"],
        "source_policy": {
            "public_sources_only": True,
            "gated_materials_excluded": True,
            "raw_documents_mirrored_by_default": False,
        },
        "catalog_status": "active",
    }


def valid_source_reference() -> dict:
    return {
        "schema_version": "0.1.0",
        "source_id": "example-trust-center",
        "vendor_id": "example",
        "source_type": "trust_center",
        "title_native": "Example Trust Center",
        "source_url": "https://trust.example.com",
        "source_language": "en",
        "source_authority_class": "vendor_published",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "vendor",
            "collected_at": "2026-06-01T00:00:00Z",
            "observer": "human",
            "confidence": "high",
        },
        "not_advice": True,
    }


def valid_observation() -> dict:
    return {
        "schema_version": "0.1.0",
        "observation_id": "example-trust-center-2026-06-12",
        "vendor_id": "example",
        "source_id": "example-trust-center",
        "observed_at": "2026-06-12T00:00:00Z",
        "result": "ok",
        "access_class": "public_web",
        "hashes": {
            "raw_sha256": "sha256:" + "a" * 64,
            "normalized_text_sha256": "sha256:" + "b" * 64,
        },
        "storage": {
            "raw_document_stored": False,
            "extracted_text_stored": False,
            "screenshot_stored": False,
        },
        "not_advice": True,
    }


# Vendor identity fields


def test_vendor_profile_accepts_identity_history_fields():
    instance = valid_vendor_profile()
    instance["display_aliases"] = ["Example Labs", "ExampleHQ"]
    instance["previous_domains"] = ["examplelabs.com"]

    assert_valid("vendor-public-profile.schema.json", instance)


def test_vendor_profile_remains_valid_without_identity_history_fields():
    assert_valid("vendor-public-profile.schema.json", valid_vendor_profile())


def test_vendor_profile_rejects_malformed_previous_domain():
    instance = valid_vendor_profile()
    instance["previous_domains"] = ["https://examplelabs.com"]

    assert_invalid("vendor-public-profile.schema.json", instance)


def test_vendor_profile_rejects_duplicate_display_aliases():
    instance = valid_vendor_profile()
    instance["display_aliases"] = ["Example Labs", "Example Labs"]

    assert_invalid("vendor-public-profile.schema.json", instance)


# Source registry fields


def test_source_reference_remains_valid_without_registry_fields():
    assert_valid("source-reference.schema.json", valid_source_reference())


def test_source_reference_accepts_full_registry_fields():
    instance = valid_source_reference()
    instance["canonical_confidence"] = {
        "class": "canonical",
        "basis": "Linked from the vendor's official domain footer; no redirects observed.",
        "assessed_at": "2026-06-12T00:00:00Z",
    }
    instance["retrieval"] = {
        "method": "html_page",
        "machine_readable": False,
        "hints": {
            "feed_url": None,
            "llms_txt_url": "https://trust.example.com/llms.txt",
            "notes": "Subprocessor table rendered server-side.",
        },
    }
    instance["source_health"] = {
        "status": "ok",
        "as_of": "2026-06-12T00:00:00Z",
        "basis": "source-health run source-maintenance-report-12345",
    }
    instance["change_detection"] = {
        "baseline_observed_at": "2026-06-12T00:00:00Z",
        "baseline_observation_id": "example-trust-center-2026-06-12",
        "baseline_raw_sha256": "sha256:" + "a" * 64,
        "baseline_normalized_text_sha256": "sha256:" + "b" * 64,
    }

    assert_valid("source-reference.schema.json", instance)


def test_canonical_confidence_requires_class():
    instance = valid_source_reference()
    instance["canonical_confidence"] = {"basis": "No classification yet."}

    assert_invalid("source-reference.schema.json", instance)


def test_canonical_confidence_rejects_unknown_class():
    instance = valid_source_reference()
    instance["canonical_confidence"] = {"class": "verified_good"}

    assert_invalid("source-reference.schema.json", instance)


def test_retrieval_requires_method_and_machine_readable():
    instance = valid_source_reference()
    instance["retrieval"] = {"method": "rss_feed"}

    assert_invalid("source-reference.schema.json", instance)


def test_retrieval_rejects_unknown_method():
    instance = valid_source_reference()
    instance["retrieval"] = {"method": "screen_scrape", "machine_readable": False}

    assert_invalid("source-reference.schema.json", instance)


def test_retrieval_rejects_unknown_hint_key():
    instance = valid_source_reference()
    instance["retrieval"] = {
        "method": "json_api",
        "machine_readable": True,
        "hints": {"api_endpoint": "https://api.example.com/trust", "scrape_script": "x.py"},
    }

    assert_invalid("source-reference.schema.json", instance)


def test_source_health_requires_status_and_as_of():
    instance = valid_source_reference()
    instance["source_health"] = {"status": "ok"}

    assert_invalid("source-reference.schema.json", instance)


def test_source_health_rejects_unknown_status():
    instance = valid_source_reference()
    instance["source_health"] = {"status": "excellent", "as_of": "2026-06-12T00:00:00Z"}

    assert_invalid("source-reference.schema.json", instance)


def test_change_detection_requires_baseline_observed_at():
    instance = valid_source_reference()
    instance["change_detection"] = {"baseline_raw_sha256": "sha256:" + "a" * 64}

    assert_invalid("source-reference.schema.json", instance)


def test_change_detection_rejects_malformed_baseline_hash():
    instance = valid_source_reference()
    instance["change_detection"] = {
        "baseline_observed_at": "2026-06-12T00:00:00Z",
        "baseline_raw_sha256": "md5:abc123",
    }

    assert_invalid("source-reference.schema.json", instance)


def test_source_reference_still_rejects_undeclared_fields():
    instance = valid_source_reference()
    instance["risk_score"] = 5

    assert_invalid("source-reference.schema.json", instance)


# Observation history fields


def test_observation_remains_valid_without_history_fields():
    assert_valid("observation.schema.json", valid_observation())


def test_observation_accepts_history_fields():
    instance = valid_observation()
    instance["redirect_chain"] = [
        "https://example.com/trust",
        "https://trust.example.com/",
    ]
    instance["material_change"] = False
    instance["previous_observation_id"] = "example-trust-center-2026-06-01"

    assert_valid("observation.schema.json", instance)


def test_observation_material_change_allows_not_evaluated():
    instance = valid_observation()
    instance["material_change"] = None

    assert_valid("observation.schema.json", instance)


def test_observation_rejects_non_uri_redirect_chain_entries():
    instance = valid_observation()
    instance["redirect_chain"] = [302]

    assert_invalid("observation.schema.json", instance)


def test_observation_rejects_malformed_previous_observation_id():
    instance = valid_observation()
    instance["previous_observation_id"] = "Bad_ID"

    assert_invalid("observation.schema.json", instance)
