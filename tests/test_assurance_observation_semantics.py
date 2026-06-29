from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.support.assurance_fixture_repository import load_assurance_fixture_repository
from tools.openva import assurance_validation
from tools.openva.validate import build_validator_for_record_kind

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/assurance/verification/semantic"


def run_case(name: str):
    return load_assurance_fixture_repository(
        FIXTURE_ROOT / name / "repository",
        validator_factory=build_validator_for_record_kind,
    )


def semantic_contract(diagnostic: assurance_validation.ValidationDiagnostic) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "record_kind": diagnostic.record_kind,
        "record_id": diagnostic.record_id,
        "instance_path": diagnostic.instance_path,
        "related_ids": list(diagnostic.related_ids),
    }


@pytest.mark.parametrize(
    "case_id,expected",
    [
        (
            "invalid/unknown-assurance-reference",
            [
                {
                    "code": "ASSURANCE_OBSERVATION_ASSURANCE_UNKNOWN",
                    "record_kind": "assurance_observation",
                    "record_id": "unknown-assurance-observation",
                    "instance_path": "/assurance_id",
                    "related_ids": ["missing-assurance"],
                }
            ],
        ),
        (
            "invalid/observation-vendor-mismatch",
            [
                {
                    "code": "ASSURANCE_OBSERVATION_VENDOR_MISMATCH",
                    "record_kind": "assurance_observation",
                    "record_id": "mismatched-vendor-observation",
                    "instance_path": "/vendor_id",
                    "related_ids": ["acme-iso-2026", "beta", "acme"],
                }
            ],
        ),
    ],
)
def test_assurance_observation_semantic_diagnostics(
    case_id: str,
    expected: list[dict[str, Any]],
) -> None:
    result = run_case(case_id)

    assert not result.structural_failures
    assert not result.repository_build_diagnostics
    actual = [semantic_contract(diagnostic) for diagnostic in result.semantic_diagnostics]
    assert actual == expected
