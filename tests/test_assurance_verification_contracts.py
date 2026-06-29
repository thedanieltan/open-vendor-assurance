from __future__ import annotations

import json
import re
from collections.abc import Iterable
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

VERIFICATION_ROOT = ROOT / "tests/fixtures/assurance/verification"
CONTRACT_ROOT = VERIFICATION_ROOT / "contracts"
POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
NEW_SCHEMA_PATHS = [
    ROOT / "schemas/openva/vocabularies/assurance-intelligence-v1.schema.json",
    ROOT / "schemas/openva/assurance-verification-request.schema.json",
    ROOT / "schemas/openva/assurance-verification-state.schema.json",
    ROOT / "schemas/openva/assurance-verification-policy.schema.json",
]
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def expectation_paths() -> list[Path]:
    return sorted(CONTRACT_ROOT.glob("*/expectations.json"))


def iter_json_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from iter_json_values(nested)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_values(item)


def validate_with(schema_path: Path, data: Any) -> None:
    validator = build_openva_validator(schema_path)
    assert list(validator.iter_errors(data)) == []


def repository_records(repository_root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "vendors": {},
        "sources": {},
        "source_observations": {},
        "assurances": {},
        "assurance_observations": {},
    }
    id_fields = {
        "vendors": "vendor_id",
        "sources": "source_id",
        "source_observations": "observation_id",
        "assurances": "assurance_id",
        "assurance_observations": "assurance_observation_id",
    }
    for directory_name, id_field in id_fields.items():
        directory = repository_root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            assert isinstance(record, dict)
            records[directory_name][record[id_field]] = record
    return records


@pytest.mark.parametrize("schema_path", NEW_SCHEMA_PATHS)
def test_verification_schemas_pass_check_schema(schema_path: Path) -> None:
    Draft202012Validator.check_schema(load_schema(schema_path))


def test_verification_schemas_are_registered_for_offline_refs() -> None:
    registered = set(ASSURANCE_SCHEMA_PATHS)
    for schema_path in NEW_SCHEMA_PATHS:
        assert schema_path in registered


def test_verification_refs_resolve_through_offline_registry() -> None:
    registry = build_openva_schema_registry()
    for schema_path in NEW_SCHEMA_PATHS:
        schema = load_schema(schema_path)
        validator = Draft202012Validator(
            schema,
            registry=registry,
            format_checker=FormatChecker(),
        )
        Draft202012Validator.check_schema(validator.schema)


def test_verification_policy_validates_and_digest_is_canonical() -> None:
    policy = load_policy()
    validate_with(ROOT / "schemas/openva/assurance-verification-policy.schema.json", policy)
    digest = policy_digest()
    assert digest == sha256_bytes(canonical_json(policy))
    assert SHA256_PATTERN.fullmatch(digest)


@pytest.mark.parametrize("expectation_path", expectation_paths(), ids=lambda path: path.parent.name)
def test_fixture_requests_use_actual_policy_digest(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    request = expectation["request"]
    validate_with(ROOT / "schemas/openva/assurance-verification-request.schema.json", request)
    assert request["policy"]["digest"] == policy_digest()


@pytest.mark.parametrize("expectation_path", expectation_paths(), ids=lambda path: path.parent.name)
def test_expected_verification_state_envelopes_validate(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    assert expectation["expected_result"] == "verification_state"
    validate_with(
        ROOT / "schemas/openva/assurance-verification-state.schema.json",
        expectation["expected_state"],
    )


@pytest.mark.parametrize("expectation_path", expectation_paths(), ids=lambda path: path.parent.name)
def test_verification_fixture_repository_records_validate(expectation_path: Path) -> None:
    records = repository_records(expectation_path.parent / "repository")
    for record in records["vendors"].values():
        build_validator_for_schema_kind("vendor").validate(record)
    for record in records["sources"].values():
        build_validator_for_schema_kind("source").validate(record)
        assert record["vendor_id"] in records["vendors"]
    for record in records["source_observations"].values():
        build_validator_for_schema_kind("observation").validate(record)
        assert record["source_id"] in records["sources"]
    for record in records["assurances"].values():
        build_validator_for_schema_kind("assurance").validate(record)
        assert record["vendor_id"] in records["vendors"]
    for record in records["assurance_observations"].values():
        build_validator_for_schema_kind("assurance_observation").validate(record)
        assert record["assurance_id"] in records["assurances"]


@pytest.mark.parametrize("expectation_path", expectation_paths(), ids=lambda path: path.parent.name)
def test_verification_reason_and_provenance_constraints(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    state = expectation["expected_state"]
    target_id = expectation["request"]["assurance_id"]

    assert state["determination"] == "determined"
    assert state["reason_codes"]
    assert state["caused_by"]["assurance_ids"] == [target_id]
    assert state["caused_by"]["source_observation_ids"] == []

    if state["value"] == "no_conclusion":
        assert state["caused_by"]["assurance_observation_ids"] == []
    else:
        assert state["caused_by"]["assurance_observation_ids"]


def test_future_recorded_observation_is_excluded_from_normative_provenance() -> None:
    expectation = load_json(CONTRACT_ROOT / "future-recorded-observation-excluded/expectations.json")
    assert expectation["expected_state"]["value"] == "no_conclusion"
    assert expectation["expected_state"]["caused_by"]["assurance_observation_ids"] == []


def test_lower_authority_observations_are_not_cited_when_higher_tier_decides() -> None:
    expectation = load_json(
        CONTRACT_ROOT / "higher-authority-support-over-lower-contradiction/expectations.json"
    )
    assert expectation["expected_state"]["value"] == "confirmed"
    assert expectation["expected_state"]["caused_by"]["assurance_observation_ids"] == [
        "authoritative-support"
    ]


def test_source_health_failure_does_not_change_verification_contract() -> None:
    expectation_path = CONTRACT_ROOT / "source-health-failure-does-not-affect-verification/expectations.json"
    expectation = load_json(expectation_path)
    records = repository_records(expectation_path.parent / "repository")
    source_observation = next(iter(records["source_observations"].values()))
    assert source_observation["result"] == "fetch_failed"
    assert source_observation["source_health"]["status"] == "unreachable"
    assert expectation["expected_state"]["value"] == "confirmed"


def test_verification_fixtures_use_no_placeholder_hashes() -> None:
    for expectation_path in expectation_paths():
        expectation = load_json(expectation_path)
        for value in iter_json_values(expectation):
            if isinstance(value, str) and value.startswith("sha256:"):
                assert SHA256_PATTERN.fullmatch(value)
                assert value != "sha256:" + "0" * 64


def test_lifecycle_projection_profile_remains_two_axis() -> None:
    projection_schema = load_schema(ROOT / "schemas/openva/assurance-projection.schema.json")
    implemented_axes = projection_schema["properties"]["implemented_axes"]["prefixItems"]
    assert implemented_axes == [
        {"const": "instrument_state"},
        {"const": "supersession_state"},
    ]
    assert projection_schema["properties"]["implemented_axes"]["minItems"] == 2
    assert projection_schema["properties"]["implemented_axes"]["maxItems"] == 2
    assert set(projection_schema["properties"]["axes"]["properties"]) == {
        "instrument_state",
        "supersession_state",
    }
