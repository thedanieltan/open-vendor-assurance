import json

from jsonschema import Draft202012Validator

from tools.openva.validate import validate_adapter_record


def adapter_validator():
    schema = json.load(open("schemas/openva/adapter-normalized-record.schema.json", encoding="utf-8"))
    return Draft202012Validator(schema)


def schema_errors(record):
    return list(adapter_validator().iter_errors(record))


def test_adapter_normalized_record_schema_accepts_canonical_record():
    errors = schema_errors(
        {
            "record_class": "canonical",
            "canonical": True,
            "catalog_tier": "human_reviewed",
            "review_state": "human_reviewed",
            "advisory_boundary": "non_advisory",
        }
    )

    assert errors == []


def test_adapter_normalized_record_schema_accepts_observation_record():
    errors = schema_errors(
        {
            "record_class": "observation",
            "canonical": False,
            "catalog_tier": "observation",
            "review_state": "auto_observed",
            "advisory_boundary": "non_advisory",
        }
    )

    assert errors == []


def test_adapter_normalized_record_schema_accepts_inventory_match_record():
    errors = schema_errors(
        {
            "record_class": "inventory_match",
            "canonical": False,
            "catalog_tier": "human_reviewed",
            "review_state": "human_reviewed",
            "advisory_boundary": "non_advisory",
        }
    )

    assert errors == []


def test_adapter_normalized_record_schema_rejects_observation_as_canonical():
    errors = schema_errors(
        {
            "record_class": "observation",
            "canonical": True,
            "catalog_tier": "observation",
            "review_state": "auto_observed",
            "advisory_boundary": "non_advisory",
        }
    )

    assert errors


def test_adapter_normalized_record_schema_rejects_candidate_as_canonical():
    errors = schema_errors(
        {
            "record_class": "candidate",
            "canonical": True,
            "catalog_tier": "discovery",
            "review_state": "human_review_required",
            "advisory_boundary": "non_advisory",
        }
    )

    assert errors


def test_adapter_normalized_record_schema_rejects_inventory_match_as_canonical():
    errors = schema_errors(
        {
            "record_class": "inventory_match",
            "canonical": True,
            "catalog_tier": "human_reviewed",
            "review_state": "human_reviewed",
            "advisory_boundary": "non_advisory",
        }
    )

    assert errors


def test_adapter_normalized_record_schema_rejects_non_boundary_value():
    errors = schema_errors(
        {
            "record_class": "canonical",
            "canonical": True,
            "catalog_tier": "human_reviewed",
            "review_state": "human_reviewed",
            "advisory_boundary": "outside_boundary",
        }
    )

    assert errors


def test_validate_adapter_record_rejects_non_canonical_record_marked_canonical():
    failures = validate_adapter_record(
        {
            "record_class": "candidate",
            "canonical": True,
            "catalog_tier": "discovery",
            "review_state": "human_review_required",
            "advisory_boundary": "non_advisory",
        }
    )

    assert failures


def test_validate_adapter_record_accepts_inventory_match_output():
    failures = validate_adapter_record(
        {
            "record_class": "inventory_match",
            "canonical": False,
            "catalog_tier": "human_reviewed",
            "review_state": "human_reviewed",
            "advisory_boundary": "non_advisory",
        }
    )

    assert failures == []
