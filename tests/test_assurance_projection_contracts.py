from __future__ import annotations

import json
import re
from copy import deepcopy
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import (
    ASSURANCE_SCHEMA_PATHS,
    ROOT,
    build_openva_schema_registry,
    build_openva_validator,
    load_schema,
)
from tools.openva.validate import build_validator_for_schema_kind

PROJECTION_ROOT = ROOT / "tests/fixtures/assurance/projection"
POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
CHANGE_EVENT_INVALID_FIXTURE = (
    ROOT
    / "tests/fixtures/assurance/schema/invalid/change-event-with-cross-axis-values.json"
)
NEW_SCHEMA_PATHS = [
    ROOT / "schemas/openva/vocabularies/assurance-projection-v1.schema.json",
    ROOT / "schemas/openva/assurance-projection-request.schema.json",
    ROOT / "schemas/openva/assurance-projection.schema.json",
    ROOT / "schemas/openva/assurance-projection-policy.schema.json",
]
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

MIGRATED_CHANGE_EVENT_CAUSAL_INPUTS = {
    CHANGE_EVENT_INVALID_FIXTURE: {
        "fixture": "change-event-with-cross-axis-values",
        "change_event_id": "example-assurance-change",
        "assurance_ids": ["example-iso27001-2026"],
        "assurance_observation_ids": ["example-assurance-observation"],
        "transition_axis": "verification_state",
    }
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policy() -> dict[str, Any]:
    policy = load_yaml(POLICY_PATH)
    assert isinstance(policy, dict)
    return policy


def policy_digest() -> str:
    return sha256_bytes(canonical_json(load_policy()))


def fixture_expectation_paths() -> list[Path]:
    return sorted(PROJECTION_ROOT.glob("**/expectations.json"))


def projection_repository_roots() -> list[Path]:
    return sorted(path for path in PROJECTION_ROOT.glob("**/repository") if path.is_dir())


def iter_json_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from iter_json_values(nested)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_values(item)


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    return parsed.astimezone(UTC)


def validate_with(schema_path: Path, data: Any) -> None:
    validator = build_openva_validator(schema_path)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    assert errors == []


def load_repository_records(repository_root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "vendors": {},
        "sources": {},
        "assurances": {},
        "assurance_observations": {},
        "assurance_changes": {},
    }
    id_field_by_dir = {
        "vendors": "vendor_id",
        "sources": "source_id",
        "assurances": "assurance_id",
        "assurance_observations": "assurance_observation_id",
        "assurance_changes": "change_event_id",
    }
    for directory_name, id_field in id_field_by_dir.items():
        directory = repository_root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            assert isinstance(record, dict)
            record_id = record[id_field]
            records[directory_name][record_id] = record
    return records


@pytest.mark.parametrize("schema_path", NEW_SCHEMA_PATHS)
def test_projection_schemas_pass_check_schema(schema_path: Path) -> None:
    Draft202012Validator.check_schema(load_schema(schema_path))


def test_projection_schemas_are_registered_for_offline_refs() -> None:
    registered = set(ASSURANCE_SCHEMA_PATHS)
    for schema_path in NEW_SCHEMA_PATHS:
        assert schema_path in registered


def test_projection_refs_resolve_through_offline_registry() -> None:
    registry = build_openva_schema_registry()
    for schema_path in NEW_SCHEMA_PATHS:
        schema = load_schema(schema_path)
        validator = Draft202012Validator(
            schema,
            registry=registry,
            format_checker=FormatChecker(),
        )
        Draft202012Validator.check_schema(validator.schema)


def test_projection_policy_validates_and_digest_is_canonical() -> None:
    policy = load_policy()
    validate_with(ROOT / "schemas/openva/assurance-projection-policy.schema.json", policy)
    digest = policy_digest()
    assert digest == sha256_bytes(canonical_json(policy))
    assert SHA256_PATTERN.fullmatch(digest)


@pytest.mark.parametrize("expectation_path", fixture_expectation_paths(), ids=lambda path: str(path.parent.relative_to(PROJECTION_ROOT)))
def test_fixture_requests_use_actual_policy_digest(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    request = expectation["request"]
    validate_with(ROOT / "schemas/openva/assurance-projection-request.schema.json", request)
    assert request["policy"]["digest"] == policy_digest()


@pytest.mark.parametrize("repository_root", projection_repository_roots(), ids=lambda path: str(path.parent.relative_to(PROJECTION_ROOT)))
def test_projection_fixture_records_validate_and_cross_references_resolve(repository_root: Path) -> None:
    records = load_repository_records(repository_root)
    for record in records["vendors"].values():
        build_validator_for_schema_kind("vendor").validate(record)
    for record in records["sources"].values():
        build_validator_for_schema_kind("source").validate(record)
        assert record["vendor_id"] in records["vendors"]
    for record in records["assurances"].values():
        build_validator_for_schema_kind("assurance").validate(record)
        assert record["vendor_id"] in records["vendors"]
        for source_id in record["evidence"]["source_ids"]:
            assert source_id in records["sources"]
        supersedes = record.get("supersedes_assurance_id")
        if isinstance(supersedes, str) and "semantic-invalid" not in repository_root.parts:
            assert supersedes in records["assurances"]
    for record in records["assurance_observations"].values():
        build_validator_for_schema_kind("assurance_observation").validate(record)
        assert record["assurance_id"] in records["assurances"]
    for record in records["assurance_changes"].values():
        build_validator_for_schema_kind("assurance_change").validate(record)
        assert record["assurance_id"] in records["assurances"]


@pytest.mark.parametrize("repository_root", projection_repository_roots(), ids=lambda path: str(path.parent.relative_to(PROJECTION_ROOT)))
def test_every_projection_fixture_assurance_has_valid_recorded_at(repository_root: Path) -> None:
    records = load_repository_records(repository_root)
    for record in records["assurances"].values():
        recorded_at = record.get("recorded_at")
        assert isinstance(recorded_at, str)
        parse_datetime(recorded_at)


@pytest.mark.parametrize(
    "expectation_path",
    sorted((PROJECTION_ROOT / "projection-valid").glob("*/expectations.json")),
    ids=lambda path: path.parent.name,
)
def test_projection_valid_expected_envelopes_validate(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    assert expectation["expected_result"] == "projection"
    assert expectation["expected_axes"] == expectation["expected_projection"]["axes"]
    validate_with(
        ROOT / "schemas/openva/assurance-projection.schema.json",
        expectation["expected_projection"],
    )


@pytest.mark.parametrize(
    "expectation_path",
    sorted((PROJECTION_ROOT / "semantic-invalid").glob("*/expectations.json")),
    ids=lambda path: path.parent.name,
)
def test_semantic_invalid_expectation_envelopes_validate(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    schema = {
        "type": "object",
        "required": ["fixture", "request", "expected_result", "expected_diagnostics"],
        "properties": {
            "fixture": {"type": "string", "minLength": 1},
            "request": {"type": "object"},
            "expected_result": {"const": "projection_input_invalid"},
            "expected_diagnostics": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["code", "record_ids"],
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "record_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }
    Draft202012Validator(schema).validate(expectation)


def test_no_projection_fixture_uses_placeholder_or_fabricated_hash_shape() -> None:
    for expectation_path in fixture_expectation_paths():
        expectation = load_json(expectation_path)
        for value in iter_json_values(expectation):
            if isinstance(value, str) and value.startswith("sha256:"):
                assert SHA256_PATTERN.fullmatch(value)
                assert value != "sha256:" + "0" * 64
                assert "placeholder" not in value


def test_migrated_change_event_input_digest_is_deterministic() -> None:
    for path, causal_inputs in MIGRATED_CHANGE_EVENT_CAUSAL_INPUTS.items():
        record = load_json(path)
        assert record["input_digest"] == sha256_bytes(canonical_json(causal_inputs))

    noop_expectation = load_json(PROJECTION_ROOT / "semantic-no-op-rebuild/expectations.json")
    causal_inputs_by_path = noop_expectation["change_event_causal_inputs"]
    for relative_path, causal_inputs in causal_inputs_by_path.items():
        record = load_yaml(PROJECTION_ROOT / "semantic-no-op-rebuild" / relative_path)
        assert record["input_digest"] == sha256_bytes(canonical_json(causal_inputs))


def test_projection_change_event_bitemporal_invariants() -> None:
    for repository_root in projection_repository_roots():
        records = load_repository_records(repository_root)
        for change_event in records["assurance_changes"].values():
            knowledge_cutoff = parse_datetime(change_event["knowledge_cutoff"])
            detected_at = parse_datetime(change_event["detected_at"])
            assert detected_at >= knowledge_cutoff

            for assurance_id in change_event["caused_by"].get("assurance_ids", []):
                assurance_recorded_at = parse_datetime(records["assurances"][assurance_id]["recorded_at"])
                assert knowledge_cutoff >= assurance_recorded_at
            for observation_id in change_event["caused_by"].get("assurance_observation_ids", []):
                observation_recorded_at = parse_datetime(
                    records["assurance_observations"][observation_id]["recorded_at"]
                )
                assert knowledge_cutoff >= observation_recorded_at


def test_semantic_no_op_rebuild_projections_differ_only_by_projected_at() -> None:
    expectation = load_json(PROJECTION_ROOT / "semantic-no-op-rebuild/expectations.json")
    projection_a = expectation["projection_a"]
    projection_b = expectation["projection_b"]
    validate_with(ROOT / "schemas/openva/assurance-projection.schema.json", projection_a)
    validate_with(ROOT / "schemas/openva/assurance-projection.schema.json", projection_b)

    assert projection_a["projected_at"] != projection_b["projected_at"]
    comparable_a = {key: value for key, value in projection_a.items() if key != "projected_at"}
    comparable_b = {key: value for key, value in projection_b.items() if key != "projected_at"}
    assert comparable_a == comparable_b


@pytest.mark.parametrize(
    "case_name,updates",
    [
        ("standalone-with-predecessor", {"topology": "standalone", "predecessor_assurance_id": "acme-prior"}),
        ("standalone-with-successor", {"topology": "standalone", "successor_assurance_ids": ["acme-next"]}),
        ("chain-root-with-predecessor", {"topology": "chain_root", "predecessor_assurance_id": "acme-prior"}),
        ("chain-root-without-successor", {"topology": "chain_root", "successor_assurance_ids": []}),
        (
            "chain-intermediate-without-predecessor",
            {"topology": "chain_intermediate", "predecessor_assurance_id": None},
        ),
        ("chain-intermediate-without-successor", {"topology": "chain_intermediate", "successor_assurance_ids": []}),
        ("chain-tip-without-predecessor", {"topology": "chain_tip", "predecessor_assurance_id": None}),
        ("chain-tip-with-successor", {"topology": "chain_tip", "successor_assurance_ids": ["acme-next"]}),
        ("current-chain-root", {"topology": "chain_root", "successor_assurance_ids": ["acme-next"], "value": "current"}),
        ("superseded-standalone", {"topology": "standalone", "value": "superseded"}),
    ],
)
def test_supersession_topology_contradictions_are_rejected(
    case_name: str,
    updates: dict[str, Any],
) -> None:
    expectation = load_json(PROJECTION_ROOT / "semantic-no-op-rebuild/expectations.json")
    projection = deepcopy(expectation["projection_a"])
    projection["axes"]["supersession_state"].update(updates)

    validator = build_openva_validator(ROOT / "schemas/openva/assurance-projection.schema.json")
    assert list(validator.iter_errors(projection)), case_name


def test_legacy_vocabulary_deprecates_only_superseded_instrument_state() -> None:
    vocabulary = load_schema(ROOT / "schemas/openva/vocabularies/assurance-v1.schema.json")
    deprecated = sorted(
        name
        for name, definition in vocabulary["$defs"].items()
        if isinstance(definition, dict) and definition.get("deprecated") is True
    )
    assert deprecated == ["instrumentState"]
