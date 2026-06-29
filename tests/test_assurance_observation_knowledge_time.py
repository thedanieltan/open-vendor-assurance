from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva.schema_registry import ROOT, build_openva_validator

ASSURANCE_OBSERVATION_SCHEMA = ROOT / "schemas/openva/assurance-observation.schema.json"
INVALID_SCHEMA_OBSERVATION = (
    ROOT / "tests/fixtures/assurance/schema/invalid/observation-with-transition-state.json"
)


def load_record(path: Path) -> Any:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise AssertionError(f"unsupported fixture extension: {path}")


def base_observation() -> dict[str, Any]:
    return {
        "schema_version": "0.1.1",
        "assurance_observation_id": "example-assurance-observation",
        "assurance_id": "example-iso27001-2026",
        "vendor_id": "example-vendor",
        "observed_at": "2026-06-29T00:00:00Z",
        "recorded_at": "2026-06-29T00:00:00Z",
        "source_observation_ids": ["example-source-observation"],
        "evaluation": {
            "claim_presence": "present",
            "verification_outcome": "first_party_claim_observed",
            "reason_codes": ["authoritative_status_confirmed"],
        },
        "policy": {
            "id": "assurance-observation",
            "version": "0.1.0",
        },
        "advisory_boundary": "non_advisory",
    }


def assert_observation_valid(record: dict[str, Any]) -> None:
    validator = build_openva_validator(ASSURANCE_OBSERVATION_SCHEMA)
    assert list(validator.iter_errors(record)) == []


def assert_observation_invalid(record: dict[str, Any]) -> None:
    validator = build_openva_validator(ASSURANCE_OBSERVATION_SCHEMA)
    assert list(validator.iter_errors(record))


def assurance_observation_fixture_paths() -> list[Path]:
    paths: list[Path] = []
    for root in (ROOT / "tests/fixtures", ROOT / "examples", ROOT / "data"):
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".json", ".yaml", ".yml"}:
                continue
            record = load_record(path)
            if isinstance(record, dict) and "assurance_observation_id" in record:
                paths.append(path)
    return paths


def repository_assurance_observation_paths() -> list[Path]:
    return [
        path
        for path in assurance_observation_fixture_paths()
        if "schema" not in path.parts or "invalid" not in path.parts
    ]


def test_recorded_at_is_required() -> None:
    observation = base_observation()
    del observation["recorded_at"]

    assert_observation_invalid(observation)


def test_recorded_at_accepts_z_timestamp() -> None:
    observation = base_observation()
    observation["recorded_at"] = "2026-06-29T00:00:00Z"

    assert_observation_valid(observation)


def test_recorded_at_accepts_numeric_utc_offset() -> None:
    observation = base_observation()
    observation["recorded_at"] = "2026-06-29T08:00:00+08:00"

    assert_observation_valid(observation)


@pytest.mark.parametrize(
    "recorded_at",
    [
        "2026-06-29T00:00:00",
        "2026-06-29",
        "2026-06-29T00:00:00+0800",
        "not-a-timestamp",
        None,
    ],
)
def test_recorded_at_rejects_naive_date_only_and_malformed_values(recorded_at: object) -> None:
    observation = base_observation()
    observation["recorded_at"] = recorded_at

    assert_observation_invalid(observation)


def test_checked_in_assurance_observation_fixtures_use_migrated_schema_version() -> None:
    for path in assurance_observation_fixture_paths():
        record = load_record(path)
        assert record["schema_version"] == "0.1.1", f"{path} has unmigrated schema_version"


def test_checked_in_repository_assurance_observations_validate() -> None:
    for path in repository_assurance_observation_paths():
        record = load_record(path)
        assert_observation_valid(record)


def test_invalid_observation_fixture_failure_remains_isolated_to_transition() -> None:
    record = load_record(INVALID_SCHEMA_OBSERVATION)
    assert_observation_invalid(record)

    repaired = deepcopy(record)
    repaired.pop("transition")
    assert_observation_valid(repaired)


def test_no_canonical_assurance_observations_need_historical_backfill() -> None:
    canonical_paths = [
        path
        for root in (ROOT / "examples", ROOT / "data")
        for path in root.glob("vendors/*/assurance_observations/*.yaml")
    ]
    assert canonical_paths == []


def test_no_assurance_observation_producer_reads_system_clock() -> None:
    clock_tokens = ("datetime.now", "datetime.utcnow", "time.time", "now_iso")
    producer_paths = [
        path
        for path in (ROOT / "tools/openva").glob("*.py")
        if "assurance_observation" in path.read_text(encoding="utf-8")
    ]
    for path in producer_paths:
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in clock_tokens), path
