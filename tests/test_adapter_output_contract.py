import json

from jsonschema import Draft202012Validator


def test_adapter_normalized_record_schema_accepts_canonical_record():
    schema = json.load(open("schemas/openva/adapter-normalized-record.schema.json", encoding="utf-8"))
    validator = Draft202012Validator(schema)

    errors = list(
        validator.iter_errors(
            {
                "record_class": "canonical",
                "canonical": True,
                "advisory_boundary": "non_advisory",
            }
        )
    )

    assert errors == []


def test_adapter_normalized_record_schema_rejects_candidate_as_canonical():
    schema = json.load(open("schemas/openva/adapter-normalized-record.schema.json", encoding="utf-8"))
    validator = Draft202012Validator(schema)

    errors = list(
        validator.iter_errors(
            {
                "record_class": "candidate",
                "canonical": True,
                "advisory_boundary": "non_advisory",
            }
        )
    )

    assert errors
