import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tools.openva import validate

ROOT = Path(__file__).resolve().parents[1]


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas/openva" / name).read_text(encoding="utf-8"))


def schema_errors(schema_name: str, instance: dict) -> list:
    validator = Draft202012Validator(load_schema(schema_name), format_checker=FormatChecker())
    return sorted(validator.iter_errors(instance), key=lambda error: list(error.path))


def valid_legal_entity() -> dict:
    return {
        "schema_version": "0.1.0",
        "entity_id": "example-sg",
        "vendor_id": "example",
        "legal_name": "Example Singapore Pte. Ltd.",
        "jurisdiction": "SG",
        "verification_source_ids": ["example-sg-registry"],
        "catalog_status": "canonical",
        "not_advice": True,
    }


def valid_entity_mention() -> dict:
    return {
        "schema_version": "0.1.0",
        "mention_id": "example-sg-mention",
        "vendor_id": "example",
        "observed_name": "Example Singapore Pte. Ltd.",
        "observed_role": "subprocessor",
        "appears_in_source_id": "example-subprocessors",
        "observed_at": "2026-05-19T00:00:00Z",
        "assertion_source": "vendor_published",
        "resolution": {"status": "unresolved"},
        "not_advice": True,
    }


def test_legal_entity_schema_requires_verification_for_canonical_records():
    assert schema_errors("legal-entity.schema.json", valid_legal_entity()) == []

    instance = valid_legal_entity()
    instance["verification_source_ids"] = []

    assert schema_errors("legal-entity.schema.json", instance) != []


def test_legal_entity_schema_accepts_stub_without_verification_source():
    instance = valid_legal_entity()
    instance["verification_source_ids"] = []
    instance["catalog_status"] = "stub"

    assert schema_errors("legal-entity.schema.json", instance) == []


def test_legal_entity_schema_accepts_identifier_scheme_and_authority():
    instance = valid_legal_entity()
    instance["registration_number"] = "202000001A"
    instance["identifier_scheme"] = "SG_UEN"
    instance["identifier_authority"] = "Accounting and Corporate Regulatory Authority"
    instance["identifier_authority_url"] = "https://www.acra.gov.sg/"

    assert schema_errors("legal-entity.schema.json", instance) == []


def test_legal_entity_schema_rejects_identifier_scheme_without_authority():
    instance = valid_legal_entity()
    instance["registration_number"] = "0001477333"
    instance["identifier_scheme"] = "US_SEC_CIK"

    assert schema_errors("legal-entity.schema.json", instance) != []


def test_legal_entity_schema_rejects_identifier_authority_without_scheme():
    instance = valid_legal_entity()
    instance["registration_number"] = "0001477333"
    instance["identifier_authority"] = "U.S. Securities and Exchange Commission"

    assert schema_errors("legal-entity.schema.json", instance) != []


def test_legal_entity_schema_rejects_unknown_identifier_scheme():
    instance = valid_legal_entity()
    instance["registration_number"] = "0001477333"
    instance["identifier_scheme"] = "US_DELAWARE_FILE_NUMBER"
    instance["identifier_authority"] = "Delaware Division of Corporations"

    assert schema_errors("legal-entity.schema.json", instance) != []


def test_legal_entity_schema_accepts_source_backed_registered_address():
    instance = valid_legal_entity()
    instance["registered_address"] = {
        "address_lines": ["1 Example Road"],
        "locality": "Singapore",
        "region": None,
        "postal_code": "000001",
        "country": "SG",
        "source_ids": ["example-sg-registry"],
    }

    assert schema_errors("legal-entity.schema.json", instance) == []


def test_legal_entity_schema_rejects_registered_address_without_source_ids():
    instance = valid_legal_entity()
    instance["registered_address"] = {
        "address_lines": ["1 Example Road"],
        "country": "SG",
    }

    assert schema_errors("legal-entity.schema.json", instance) != []


def test_legal_entity_schema_rejects_lifecycle_event_without_source_ids():
    instance = valid_legal_entity()
    instance["lifecycle_events"] = [{"event_type": "renamed"}]

    assert schema_errors("legal-entity.schema.json", instance) != []


def test_legal_entity_schema_rejects_url_path_in_official_domains():
    instance = valid_legal_entity()
    instance["official_domains"] = ["example.com/sg"]

    assert schema_errors("legal-entity.schema.json", instance) != []


def test_entity_mention_schema_requires_complete_match_provenance():
    instance = valid_entity_mention()
    instance["resolution"] = {
        "status": "matched_to_entity",
        "matched_entity_id": "example-sg",
    }

    assert schema_errors("entity-mention.schema.json", instance) != []


def test_entity_mention_schema_rejects_unresolved_with_matched_entity():
    instance = valid_entity_mention()
    instance["resolution"]["matched_entity_id"] = "example-sg"

    assert schema_errors("entity-mention.schema.json", instance) != []


def test_source_schema_requires_entity_id_for_registry_authority():
    source = {
        "schema_version": "0.1.0",
        "source_id": "example-sg-registry",
        "vendor_id": "example",
        "source_type": "other_public_source",
        "title_native": "Example registry entry",
        "source_url": "https://registry.example.test/example-sg",
        "source_language": "en",
        "source_authority_class": "public_registry",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "regulator",
            "collected_at": "2026-05-19T00:00:00Z",
            "observer": "human",
            "confidence": "high",
        },
        "not_advice": True,
    }

    assert schema_errors("source-reference.schema.json", source) != []
    source["entity_id"] = "example-sg"
    assert schema_errors("source-reference.schema.json", source) == []


def test_artifact_schema_requires_entity_ids_for_specific_entity_scope():
    artifact = {
        "schema_version": "0.1.0",
        "artifact_id": "example-cert",
        "vendor_id": "example",
        "source_id": "example-cert",
        "artifact_type": "certification_reference",
        "canonical_url": "https://example.test/cert",
        "source_language": "en",
        "entity_scope": {"scope_type": "specific_entities"},
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "hashes": {"raw_sha256": "sha256:TBD", "normalized_text_sha256": "sha256:TBD"},
        "not_advice": True,
    }

    assert schema_errors("artifact-reference.schema.json", artifact) != []
    artifact["entity_scope"]["entity_ids"] = ["example-sg"]
    assert schema_errors("artifact-reference.schema.json", artifact) == []


def test_cross_vendor_entity_reference_is_globally_resolved(monkeypatch):
    records = {
        "vendor": [
            {"vendor_id": "vendor-a", "_openva_path": "data/vendors/vendor-a/vendor.yaml"},
            {"vendor_id": "vendor-b", "_openva_path": "data/vendors/vendor-b/vendor.yaml"},
        ],
        "source": [
            {
                "source_id": "vendor-a-registry",
                "vendor_id": "vendor-a",
                "entity_id": "vendor-a-sg",
                "_openva_path": "data/vendors/vendor-a/sources/vendor-a-registry.yaml",
            },
            {
                "source_id": "vendor-b-subprocessors",
                "vendor_id": "vendor-b",
                "_openva_path": "data/vendors/vendor-b/sources/vendor-b-subprocessors.yaml",
            },
        ],
        "artifact": [],
        "observation": [],
        "change": [],
        "legal_entity": [
            {
                "entity_id": "vendor-a-sg",
                "vendor_id": "vendor-a",
                "verification_source_ids": ["vendor-a-registry"],
                "_openva_path": "data/vendors/vendor-a/legal_entities/vendor-a-sg.yaml",
            }
        ],
        "entity_mention": [
            {
                "mention_id": "vendor-b-vendor-a-sg",
                "vendor_id": "vendor-b",
                "appears_in_source_id": "vendor-b-subprocessors",
                "resolution": {
                    "status": "matched_to_entity",
                    "matched_entity_id": "vendor-a-sg",
                    "match_source_ids": ["vendor-a-registry"],
                },
                "_openva_path": "data/vendors/vendor-b/entity_mentions/vendor-b-vendor-a-sg.yaml",
            }
        ],
        "candidate_source": [],
        "unavailable_source": [],
        "field_provenance": [],
    }

    monkeypatch.setattr(validate, "records_for", lambda kind: records[kind])
    monkeypatch.setattr(validate, "records_for_optional_kind", lambda kind: records[kind])

    assert validate.validate_cross_references() == []
