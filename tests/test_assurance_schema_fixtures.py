from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from tests.support.assurance_fixture_runner import (
    assert_expected_schema_errors,
    normalize_schema_errors,
)
from tools.openva.schema_registry import (
    ASSURANCE_SCHEMA_PATHS,
    ROOT,
    build_openva_schema_registry,
    build_openva_validator,
    load_schema,
)

FIXTURE_ROOT = ROOT / "tests/fixtures/assurance/schema"
VALID_ROOT = FIXTURE_ROOT / "valid"
INVALID_ROOT = FIXTURE_ROOT / "invalid"
MANIFEST_PATH = FIXTURE_ROOT / "expectations.json"

SCHEMA_BY_MANIFEST_NAME = {
    "assurance-record": ROOT / "schemas/openva/assurance-record.schema.json",
    "assurance-observation": ROOT / "schemas/openva/assurance-observation.schema.json",
    "assurance-change-event": ROOT / "schemas/openva/assurance-change-event.schema.json",
}

VOCABULARY_ID = "https://openva.dev/schemas/openva/vocabularies/assurance-v1.schema.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_paths(root: Path) -> list[Path]:
    return sorted(root.glob("*.json"))


def manifest() -> dict[str, Any]:
    return load_json(MANIFEST_PATH)


def assert_manifest_matches_invalid_fixtures(manifest_data: dict[str, Any], invalid_root: Path) -> None:
    cases = set((manifest_data.get("cases") or {}).keys())
    fixtures = {path.name for path in invalid_root.glob("*.json")}
    missing = fixtures - cases
    nonexistent = cases - fixtures
    assert not missing, f"invalid fixtures missing manifest entries: {sorted(missing)}"
    assert not nonexistent, f"manifest entries reference nonexistent fixtures: {sorted(nonexistent)}"


def refs_in(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            yield ref
        for nested in value.values():
            yield from refs_in(nested)
    elif isinstance(value, list):
        for item in value:
            yield from refs_in(item)


@pytest.mark.parametrize(
    "schema_path",
    [
        ROOT / "schemas/openva/vocabularies/assurance-v1.schema.json",
    ],
)
def test_vocabulary_schema_passes_check_schema(schema_path: Path) -> None:
    Draft202012Validator.check_schema(load_schema(schema_path))


@pytest.mark.parametrize("schema_path", ASSURANCE_SCHEMA_PATHS)
def test_assurance_schema_resources_pass_check_schema(schema_path: Path) -> None:
    Draft202012Validator.check_schema(load_schema(schema_path))


def test_external_refs_resolve_offline_for_assurance_record() -> None:
    validator = build_openva_validator(SCHEMA_BY_MANIFEST_NAME["assurance-record"])
    data = load_json(VALID_ROOT / "accredited-certification.json")
    assert list(validator.iter_errors(data)) == []


def test_valid_assurance_class_token_passes() -> None:
    registry = build_openva_schema_registry()
    validator = Draft202012Validator(
        {"$ref": f"{VOCABULARY_ID}#/$defs/assuranceClass"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    validator.validate("accredited_certification")


def test_unknown_assurance_class_token_fails() -> None:
    registry = build_openva_schema_registry()
    validator = Draft202012Validator(
        {"$ref": f"{VOCABULARY_ID}#/$defs/assuranceClass"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    assert list(validator.iter_errors("hipaa_certified"))


@pytest.mark.parametrize(
    "schema_path",
    [
        ROOT / "schemas/openva/assurance-record.schema.json",
        ROOT / "schemas/openva/assurance-observation.schema.json",
        ROOT / "schemas/openva/assurance-change-event.schema.json",
    ],
)
def test_assurance_schemas_pin_versioned_vocabulary(schema_path: Path) -> None:
    refs = list(refs_in(load_schema(schema_path)))
    assert any("vocabularies/assurance-v1.schema.json#" in ref for ref in refs)


@pytest.mark.parametrize("fixture_path", fixture_paths(VALID_ROOT), ids=lambda path: path.name)
def test_valid_assurance_record_fixtures_pass(fixture_path: Path) -> None:
    validator = build_openva_validator(SCHEMA_BY_MANIFEST_NAME["assurance-record"])
    assert list(validator.iter_errors(load_json(fixture_path))) == []


@pytest.mark.parametrize(
    "case_name,case",
    sorted(manifest()["cases"].items()),
    ids=lambda item: item[0] if isinstance(item, tuple) else str(item),
)
def test_invalid_fixtures_fail_and_match_expected_errors(
    case_name: str,
    case: dict[str, Any],
) -> None:
    validator = build_openva_validator(SCHEMA_BY_MANIFEST_NAME[case["schema"]])
    errors = list(validator.iter_errors(load_json(INVALID_ROOT / case_name)))
    assert errors
    normalized = normalize_schema_errors(errors, include_aggregate_errors=True)
    assert_expected_schema_errors(normalized, case["expected_errors"])


def test_semantic_date_order_validation_is_not_invoked() -> None:
    data = load_json(VALID_ROOT / "accredited-certification.json")
    data["temporal_scope"]["valid_from"] = "2028-01-01"
    data["temporal_scope"]["valid_until"] = "2025-01-01"
    validator = build_openva_validator(SCHEMA_BY_MANIFEST_NAME["assurance-record"])
    assert list(validator.iter_errors(data)) == []


def test_accredited_certification_identifier_must_be_non_null() -> None:
    data = load_json(VALID_ROOT / "accredited-certification.json")
    data["identifiers"] = {"certificate_number": None}
    validator = build_openva_validator(SCHEMA_BY_MANIFEST_NAME["assurance-record"])
    normalized = normalize_schema_errors(validator.iter_errors(data), include_aggregate_errors=True)
    assert any(
        error.instance_path == "/identifiers"
        and error.keyword == "anyOf"
        and "oneOf" in error.combinator_ancestry
        for error in normalized
    )


def test_transition_axis_rejects_evidence_set_shape_for_scalar_axis() -> None:
    data = load_json(INVALID_ROOT / "change-event-with-cross-axis-values.json")
    data["transition"] = {
        "axis": "instrument_state",
        "from": {"source_ids": ["example-source"]},
        "to": {"source_ids": ["example-source", "replacement-source"]},
    }
    validator = build_openva_validator(SCHEMA_BY_MANIFEST_NAME["assurance-change-event"])
    normalized = normalize_schema_errors(validator.iter_errors(data), include_aggregate_errors=True)
    assert any(error.instance_path == "/transition/from" and error.keyword == "enum" for error in normalized)
    assert any(error.instance_path == "/transition/to" and error.keyword == "enum" for error in normalized)


def test_manifest_and_invalid_fixture_names_match() -> None:
    assert_manifest_matches_invalid_fixtures(manifest(), INVALID_ROOT)


def test_missing_manifest_entry_fails(tmp_path: Path) -> None:
    invalid_root = tmp_path / "invalid"
    invalid_root.mkdir()
    (invalid_root / "orphan.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AssertionError, match="orphan.json"):
        assert_manifest_matches_invalid_fixtures({"cases": {}}, invalid_root)


def test_manifest_entry_for_nonexistent_file_fails(tmp_path: Path) -> None:
    invalid_root = tmp_path / "invalid"
    invalid_root.mkdir()
    fake_manifest = {"cases": {"ghost.json": {"schema": "assurance-record", "expected_errors": []}}}
    with pytest.raises(AssertionError, match="ghost.json"):
        assert_manifest_matches_invalid_fixtures(fake_manifest, invalid_root)


@pytest.mark.parametrize(
    "definition_name",
    [
        name
        for name, definition in load_schema(
            ROOT / "schemas/openva/vocabularies/assurance-v1.schema.json"
        )["$defs"].items()
        if "enum" in definition
    ],
)
def test_vocabulary_enums_accept_declared_tokens_and_reject_unknown(definition_name: str) -> None:
    vocabulary = load_schema(ROOT / "schemas/openva/vocabularies/assurance-v1.schema.json")
    registry = build_openva_schema_registry()
    validator = Draft202012Validator(
        {"$ref": f"{VOCABULARY_ID}#/$defs/{definition_name}"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    for token in vocabulary["$defs"][definition_name]["enum"]:
        validator.validate(token)
    assert list(validator.iter_errors(f"unknown-{definition_name}"))


def test_valid_fixtures_cover_every_assurance_class() -> None:
    observed = {load_json(path)["assurance_class"] for path in fixture_paths(VALID_ROOT)}
    assert observed == {
        "accredited_certification",
        "attestation_report",
        "regulatory_assertion",
        "contractual_capability",
    }
