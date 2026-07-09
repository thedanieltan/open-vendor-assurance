from jsonschema import Draft202012Validator

from tools.openva.indexes import build_indexes
from tools.openva import validate as validate_module
from tools.openva.validate import (
    validate_all,
    validate_coverage_claims,
    validate_quality_gates,
    validate_registration_number_quorum,
)
from tools.openva.schema_registry import load_schema


def test_resolver_result_pack_schema_is_valid_standalone_schema():
    schema = load_schema(validate_module.ROOT / "schemas/openva/resolver-result-pack.schema.json")

    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "https://openva.dev/schemas/resolver-result-pack.schema.json"
    assert schema["$defs"]["resultRow"]["properties"]["result_pack_version"] == {"const": "1.0.0"}
    source = schema["$defs"]["sourceResult"]
    assert "candidate_basis" in source["required"]
    assert "verification_basis" in source["required"]
    assert source["properties"]["candidate_basis"]["enum"] == [
        "community_hint",
        "vendor_asserted",
        "cached_locator",
        "direct_input",
        "none",
    ]
    assert source["properties"]["verification_basis"]["enum"] == [
        "not_checked",
        "verified_live",
        "live_unavailable",
        "live_gated",
        "live_not_found",
    ]


def test_build_indexes_passes():
    assert build_indexes() == 0


def test_validate_all_passes():
    assert validate_all() == 0


def source_record(**overrides):
    record = {
        "_openva_path": "data/vendors/example/sources/example-legal.yaml",
        "schema_version": "0.1.0",
        "source_id": "example-legal",
        "vendor_id": "example",
        "source_type": "terms_of_service",
        "title_native": "Example Legal Terms",
        "source_url": "https://example.com/legal",
        "source_language": "en",
        "source_authority_class": "vendor_legal_terms",
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
    record.update(overrides)
    return record


def legal_entity_record(**overrides):
    record = {
        "_openva_path": "data/vendors/example/legal_entities/example-pte-ltd.yaml",
        "schema_version": "0.1.0",
        "entity_id": "example-pte-ltd",
        "vendor_id": "example",
        "legal_name": "Example Pte. Ltd.",
        "jurisdiction": "SG",
        "registration_number": "202612345A",
        "verification_source_ids": ["example-registry", "example-terms"],
    }
    record.update(overrides)
    return record


def official_registry_source(**overrides):
    record = source_record(
        _openva_path="data/vendors/example/sources/example-registry.yaml",
        source_id="example-registry",
        source_type="other_public_source",
        source_authority_class="public_registry",
        entity_id="example-pte-ltd",
        registration_number="202612345A",
        source_url="https://registry.example/entities/202612345A",
    )
    record.update(overrides)
    return record


def corroborating_entity_source(**overrides):
    record = source_record(
        _openva_path="data/vendors/example/sources/example-terms.yaml",
        source_id="example-terms",
        source_type="terms_of_service",
        source_authority_class="vendor_legal_terms",
        entity_id="example-pte-ltd",
        source_url="https://example.com/legal/terms",
    )
    record.update(overrides)
    return record


def test_coverage_claim_evidence_rejects_prohibited_advisory_wording():
    source = source_record(
        coverage_claims=[
            {
                "role": "dpa",
                "coverage_type": "contains",
                "evidence": "The page says this is safe for regulated workloads.",
            }
        ]
    )

    failures = validate_coverage_claims(
        source["_openva_path"],
        source,
        {source["source_id"]: source},
        ["safe"],
    )

    assert "coverage_claims[0].evidence prohibited advisory wording detected: safe" in failures[0]


def test_links_to_coverage_claim_requires_target():
    source = source_record(
        coverage_claims=[
            {
                "role": "certification_reference",
                "coverage_type": "links_to",
                "evidence": "The page links to public certification information.",
            }
        ]
    )

    failures = validate_coverage_claims(
        source["_openva_path"],
        source,
        {source["source_id"]: source},
        [],
    )

    assert any("links_to requires target_url or target_source_id" in failure for failure in failures)


def test_duplicate_coverage_claim_role_fails():
    source = source_record(
        coverage_claims=[
            {"role": "dpa", "coverage_type": "contains", "evidence": "The page includes a DPA section."},
            {"role": "dpa", "coverage_type": "links_to", "evidence": "The page links to DPA information.", "target_url": "https://example.com/dpa"},
        ]
    )

    failures = validate_coverage_claims(
        source["_openva_path"],
        source,
        {source["source_id"]: source},
        [],
    )

    assert any("duplicate coverage_claims role dpa" in failure for failure in failures)


def test_coverage_claim_target_source_id_must_exist_and_match_vendor():
    source = source_record(
        coverage_claims=[
            {
                "role": "dpa",
                "coverage_type": "links_to",
                "evidence": "The page links to a DPA source.",
                "target_source_id": "missing-source",
            }
        ]
    )
    other_vendor_source = source_record(source_id="other-dpa", vendor_id="other", source_url="https://other.example/dpa")

    missing_failures = validate_coverage_claims(
        source["_openva_path"],
        source,
        {source["source_id"]: source},
        [],
    )
    source["coverage_claims"][0]["target_source_id"] = "other-dpa"
    vendor_failures = validate_coverage_claims(
        source["_openva_path"],
        source,
        {source["source_id"]: source, "other-dpa": other_vendor_source},
        [],
    )

    assert any("must reference an existing source" in failure for failure in missing_failures)
    assert any("must match source vendor_id" in failure for failure in vendor_failures)


def test_registration_number_quorum_passes_for_scoped_entity_evidence():
    failures = validate_registration_number_quorum(
        "data/vendors/example/legal_entities/example-pte-ltd.yaml",
        legal_entity_record(),
        [official_registry_source(), corroborating_entity_source()],
    )

    assert failures == []


def test_registration_number_quorum_fails_for_registry_only():
    failures = validate_registration_number_quorum(
        "data/vendors/example/legal_entities/example-pte-ltd.yaml",
        legal_entity_record(verification_source_ids=["example-registry"]),
        [official_registry_source()],
    )

    assert failures == [
        "data/vendors/example/legal_entities/example-pte-ltd.yaml: "
        "registration_number evidence quorum failed: corroborating_source_missing"
    ]


def test_registration_number_quorum_is_skipped_when_registration_number_absent():
    failures = validate_registration_number_quorum(
        "data/vendors/example/legal_entities/example-pte-ltd.yaml",
        legal_entity_record(registration_number=None),
        [official_registry_source()],
    )

    assert failures == []


def test_duplicate_source_url_for_same_vendor_fails(monkeypatch):
    first = source_record(source_id="example-legal", source_url="https://example.com/legal")
    second = source_record(
        _openva_path="data/vendors/example/sources/example-terms.yaml",
        source_id="example-terms",
        source_type="dpa",
        source_url="https://example.com/legal/",
    )

    def records_for(kind):
        if kind == "vendor":
            return [
                {
                    "_openva_path": "data/vendors/example/vendor.yaml",
                    "vendor_id": "example",
                    "official_domains": ["example.com"],
                    "regions_served": [],
                    "vendor_categories": [],
                }
            ]
        if kind == "source":
            return [first, second]
        return []

    monkeypatch.setattr(validate_module, "records_for", records_for)
    monkeypatch.setattr(validate_module, "records_for_optional_kind", lambda _kind: [])
    monkeypatch.setattr(validate_module, "load_region_tags", lambda: set())
    monkeypatch.setattr(validate_module, "load_vendor_category_tags", lambda: set())
    monkeypatch.setattr(validate_module, "load_prohibited_terms", lambda: [])
    monkeypatch.setattr(validate_module, "load_official_publisher_exceptions", lambda: set())

    failures = validate_quality_gates()

    assert any("duplicate source_url for vendor example: https://example.com/legal" in failure for failure in failures)


def test_quality_gates_enforce_registration_number_quorum(monkeypatch):
    def records_for(kind):
        if kind == "vendor":
            return [
                {
                    "_openva_path": "data/vendors/example/vendor.yaml",
                    "vendor_id": "example",
                    "official_domains": ["example.com"],
                    "regions_served": [],
                    "vendor_categories": [],
                }
            ]
        if kind == "source":
            return [official_registry_source()]
        if kind == "legal_entity":
            return [legal_entity_record(verification_source_ids=["example-registry"])]
        return []

    monkeypatch.setattr(validate_module, "records_for", records_for)
    monkeypatch.setattr(validate_module, "records_for_optional_kind", lambda _kind: [])
    monkeypatch.setattr(validate_module, "load_region_tags", lambda: set())
    monkeypatch.setattr(validate_module, "load_vendor_category_tags", lambda: set())
    monkeypatch.setattr(validate_module, "load_prohibited_terms", lambda: [])
    monkeypatch.setattr(validate_module, "load_official_publisher_exceptions", lambda: set())

    failures = validate_quality_gates()

    assert any("registration_number evidence quorum failed: corroborating_source_missing" in failure for failure in failures)
