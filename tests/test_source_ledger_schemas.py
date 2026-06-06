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


def valid_unavailable_source() -> dict:
    return {
        "schema_version": "0.1.0",
        "unavailable_source_id": "example-dpa",
        "vendor_id": "example",
        "source_type": "dpa",
        "status": "not_identified",
        "reason": "distinct_public_url_not_identified",
        "reviewed_at": "2026-05-16T00:00:00Z",
        "reviewed_by": "agent",
        "next_review_after": "2026-08-16",
        "candidate_urls_checked": ["https://example.com/legal"],
        "notes": "Public DPA URL not identified in this batch.",
        "not_advice": True,
    }


def valid_reviewed_no_replacement_source() -> dict:
    record = valid_unavailable_source()
    record.update(
        {
            "truth_state": "reviewed_no_replacement_available",
            "truth_state_status": "current",
            "source_review_decision_id": "review-example-dpa",
            "reviewed_artifact_path": "maintenance/reviewed/source-review/example-dpa.json",
            "validation_report_path": "maintenance/reviewed/source-review/validation.json",
            "source_maintenance_run_id": "source-maintenance-report-12345",
            "reviewed_by": "human",
            "original_source": {
                "source_id": "example-dpa",
                "source_url": "https://example.com/legal/dpa",
                "source_type": "dpa",
                "title": "Data Processing Addendum",
                "access_class": "public_web",
                "source_authority_class": "vendor_legal_terms",
            },
            "reviewer_note": "Reviewed public materials and no replacement was available at review time.",
        }
    )
    return record


def valid_candidate_source() -> dict:
    return {
        "schema_version": "0.1.0",
        "candidate_source_id": "example-dpa",
        "vendor_id": "example",
        "source_type_candidate": "dpa",
        "candidate_url": "https://example.com/legal/dpa",
        "discovery_method": "official_domain_crawl",
        "confidence": "candidate",
        "requires_review": True,
        "discovered_at": "2026-05-16T00:00:00Z",
        "discovered_by": "agent",
        "evidence": {
            "page_title": "Data Processing Addendum",
            "matched_terms": ["data processing", "addendum"],
            "final_url": "https://example.com/legal/dpa",
            "http_status": 200,
            "content_type": "text/html",
        },
        "notes": "Candidate only; not promoted to canonical source.",
        "not_advice": True,
    }


def valid_source_reference() -> dict:
    return {
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


def test_unavailable_source_schema_accepts_reviewed_absence():
    assert_valid("unavailable-source.schema.json", valid_unavailable_source())


def test_unavailable_source_schema_requires_non_advisory_flag():
    instance = valid_unavailable_source()
    instance["not_advice"] = False

    assert_invalid("unavailable-source.schema.json", instance)


def test_unavailable_source_schema_accepts_reviewed_no_replacement_truth_state():
    assert_valid("unavailable-source.schema.json", valid_reviewed_no_replacement_source())


def test_reviewed_no_replacement_truth_state_requires_review_evidence_paths():
    instance = valid_reviewed_no_replacement_source()
    del instance["reviewed_artifact_path"]

    assert_invalid("unavailable-source.schema.json", instance)


def test_reviewed_no_replacement_truth_state_requires_original_source_context():
    instance = valid_reviewed_no_replacement_source()
    del instance["original_source"]

    assert_invalid("unavailable-source.schema.json", instance)


def test_reviewed_no_replacement_truth_state_rejects_paths_outside_reviewed_artifacts():
    instance = valid_reviewed_no_replacement_source()
    instance["validation_report_path"] = "data/vendors/example/unavailable_sources/example-dpa.yaml"

    assert_invalid("unavailable-source.schema.json", instance)


def test_superseded_unavailable_truth_state_requires_replacement_source_reference():
    instance = valid_reviewed_no_replacement_source()
    instance["truth_state_status"] = "superseded"
    instance["superseded_at"] = "2026-08-01T00:00:00Z"

    assert_invalid("unavailable-source.schema.json", instance)

    instance["superseded_by_source_id"] = "example-dpa-v2"
    assert_valid("unavailable-source.schema.json", instance)


def test_candidate_source_schema_accepts_agent_candidate():
    assert_valid("candidate-source.schema.json", valid_candidate_source())


def test_candidate_source_schema_requires_review_gate():
    instance = valid_candidate_source()
    instance["requires_review"] = False

    assert_invalid("candidate-source.schema.json", instance)


def test_source_reference_schema_accepts_without_coverage_claims():
    assert_valid("source-reference.schema.json", valid_source_reference())


def test_source_reference_schema_accepts_coverage_claims():
    instance = valid_source_reference()
    instance["coverage_claims"] = [
        {
            "role": "dpa",
            "coverage_type": "contains",
            "evidence": "The same page includes a data processing addendum section.",
        },
        {
            "role": "certification_reference",
            "coverage_type": "links_to",
            "evidence": "The page links to public certification information.",
            "target_url": "https://example.com/legal/certifications",
        },
    ]

    assert_valid("source-reference.schema.json", instance)


def test_source_reference_schema_rejects_unknown_coverage_role():
    instance = valid_source_reference()
    instance["coverage_claims"] = [
        {
            "role": "everything",
            "coverage_type": "contains",
            "evidence": "The same page includes another public source section.",
        }
    ]

    assert_invalid("source-reference.schema.json", instance)


def test_source_reference_schema_rejects_unknown_coverage_type():
    instance = valid_source_reference()
    instance["coverage_claims"] = [
        {
            "role": "dpa",
            "coverage_type": "proves",
            "evidence": "The same page includes a data processing addendum section.",
        }
    ]

    assert_invalid("source-reference.schema.json", instance)


def test_source_reference_schema_requires_coverage_evidence():
    instance = valid_source_reference()
    instance["coverage_claims"] = [{"role": "dpa", "coverage_type": "contains"}]

    assert_invalid("source-reference.schema.json", instance)
