from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.openva.schema_registry import ROOT, build_openva_validator

ASSURANCE_RECORD_SCHEMA = ROOT / "schemas/openva/assurance-record.schema.json"
FIXTURE_ROOT = ROOT / "tests/fixtures/assurance/schema"
VALID_ROOT = FIXTURE_ROOT / "valid"
INVALID_ROOT = FIXTURE_ROOT / "invalid"
MANIFEST_PATH = FIXTURE_ROOT / "expectations.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def assurance_record_fixture_paths() -> list[Path]:
    manifest = load_json(MANIFEST_PATH)
    paths = list(VALID_ROOT.glob("*.json"))
    paths.extend(
        INVALID_ROOT / name
        for name, case in manifest["cases"].items()
        if case["schema"] == "assurance-record"
    )
    return sorted(paths)


def valid_record() -> dict[str, Any]:
    return load_json(VALID_ROOT / "accredited-certification.json")


def assert_record_invalid(record: dict[str, Any]) -> None:
    validator = build_openva_validator(ASSURANCE_RECORD_SCHEMA)
    assert list(validator.iter_errors(record))


def test_valid_assurance_with_recorded_at() -> None:
    validator = build_openva_validator(ASSURANCE_RECORD_SCHEMA)
    assert list(validator.iter_errors(valid_record())) == []


def test_missing_recorded_at_rejected() -> None:
    record = valid_record()
    del record["recorded_at"]

    assert_record_invalid(record)


def test_null_recorded_at_rejected() -> None:
    record = valid_record()
    record["recorded_at"] = None

    assert_record_invalid(record)


@pytest.mark.parametrize(
    "recorded_at",
    [
        "2026-01-12",
        "2026-01-12T10:30:00",
        "not-a-timestamp",
    ],
)
def test_invalid_recorded_at_shapes_rejected(recorded_at: str) -> None:
    record = valid_record()
    record["recorded_at"] = recorded_at

    assert_record_invalid(record)


def test_all_assurance_record_fixtures_have_recorded_at() -> None:
    for fixture_path in assurance_record_fixture_paths():
        record = load_json(fixture_path)
        assert "recorded_at" in record, f"{fixture_path} missing recorded_at"
        assert record["recorded_at"] is not None, f"{fixture_path} has null recorded_at"


def test_all_migrated_valid_fixtures_validate() -> None:
    validator = build_openva_validator(ASSURANCE_RECORD_SCHEMA)
    for fixture_path in sorted(VALID_ROOT.glob("*.json")):
        assert list(validator.iter_errors(load_json(fixture_path))) == []


def test_migrated_invalid_fixtures_do_not_fail_only_for_recorded_at() -> None:
    validator = build_openva_validator(ASSURANCE_RECORD_SCHEMA)
    for fixture_path in assurance_record_fixture_paths():
        record = load_json(fixture_path)
        mutated = deepcopy(record)
        mutated["recorded_at"] = record["recorded_at"]
        errors = list(validator.iter_errors(mutated))
        if fixture_path.parent == VALID_ROOT:
            assert errors == []
        else:
            assert errors, f"{fixture_path} should remain invalid for its intended case"
