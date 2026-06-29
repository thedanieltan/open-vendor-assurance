from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.support.assurance_fixture_repository import load_assurance_fixture_repository
from tools.openva import assurance_validation
from tools.openva.validate import build_validator_for_record_kind

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/assurance/semantic"
LAYOUT_ERROR_ROOT = ROOT / "tests/fixtures/assurance/semantic_layout_errors"


def load_case(name: str):
    return load_assurance_fixture_repository(
        FIXTURE_ROOT / name,
        validator_factory=build_validator_for_record_kind,
    )


def run_semantic_fixture_case(root: Path):
    return load_assurance_fixture_repository(
        root,
        validator_factory=build_validator_for_record_kind,
    )


def semantic_diagnostic_contract(
    diagnostic: assurance_validation.ValidationDiagnostic,
) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "record_kind": diagnostic.record_kind,
        "record_id": diagnostic.record_id,
        "instance_path": diagnostic.instance_path,
        "related_ids": list(diagnostic.related_ids),
    }


def expected_semantic_contract(expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": expected["code"],
        "record_kind": expected["record_kind"],
        "record_id": expected["record_id"],
        "instance_path": expected["instance_path"],
        "related_ids": list(expected["related_ids"]),
    }


def diagnostic_signature(diagnostic: assurance_validation.ValidationDiagnostic) -> tuple[str, str, str, str, tuple[str, ...]]:
    return (
        diagnostic.code,
        diagnostic.record_kind,
        diagnostic.record_id,
        diagnostic.instance_path,
        diagnostic.related_ids,
    )


def semantic_signatures(case_name: str) -> list[tuple[str, str, str, str, tuple[str, ...]]]:
    result = load_case(case_name)
    assert result.structural_errors == ()
    assert result.build_result is not None
    assert result.build_result.diagnostics == ()
    return [diagnostic_signature(diagnostic) for diagnostic in result.semantic_diagnostics]


@pytest.mark.parametrize("case_id, expected", [
    # --- ASSURANCE_SOURCE_UNKNOWN cases ---
    ("valid/known-source", []),
    ("valid/primary-source-in-evidence", []),
    ("invalid/unknown-source", [
        {
            "code": "ASSURANCE_SOURCE_UNKNOWN",
            "record_kind": "assurance",
            "record_id": "acme-iso-2026",
            "instance_path": "/evidence/source_ids/0",
            "related_ids": ["acme-missing-source"],
        }
    ]),
    ("invalid/mixed-known-unknown", [
        {
            "code": "ASSURANCE_SOURCE_UNKNOWN",
            "record_kind": "assurance",
            "record_id": "acme-iso-2026",
            "instance_path": "/evidence/source_ids/1",
            "related_ids": ["acme-missing-source"],
        }
    ]),
    ("invalid/multiple-unknown", [
        {
            "code": "ASSURANCE_SOURCE_UNKNOWN",
            "record_kind": "assurance",
            "record_id": "acme-iso-2026",
            "instance_path": "/evidence/source_ids/0",
            "related_ids": ["acme-missing-alpha"],
        },
        {
            "code": "ASSURANCE_SOURCE_UNKNOWN",
            "record_kind": "assurance",
            "record_id": "acme-iso-2026",
            "instance_path": "/evidence/source_ids/1",
            "related_ids": ["acme-missing-beta"],
        }
    ]),

    # --- ASSURANCE_VENDOR_UNKNOWN case ---
    ("invalid/unknown-vendor", [
        {
            "code": "ASSURANCE_VENDOR_UNKNOWN",
            "record_kind": "assurance",
            "record_id": "acme-iso-2026",
            "instance_path": "/vendor_id",
            "related_ids": ["ghost-vendor"],
        }
    ]),

    # --- ASSURANCE_SOURCE_VENDOR_MISMATCH case ---
    ("invalid/source-vendor-mismatch", [
        {
            "code": "ASSURANCE_SOURCE_VENDOR_MISMATCH",
            "record_kind": "assurance",
            "record_id": "acme-iso-2026",
            "instance_path": "/evidence/source_ids/0",
            "related_ids": ["beta-source", "beta-vendor", "acme"],
        }
    ]),

    # --- ASSURANCE_PRIMARY_SOURCE_NOT_IN_EVIDENCE_SET case ---
    ("invalid/primary-source-not-in-evidence-set", [
        {
            "code": "ASSURANCE_PRIMARY_SOURCE_NOT_IN_EVIDENCE_SET",
            "record_kind": "assurance",
            "record_id": "acme-regulatory",
            "instance_path": "/evidence/primary_source_id",
            "related_ids": ["acme-primary"],
        }
    ]),

    # --- ASSURANCE_SUPERSEDES_UNKNOWN case ---
    ("invalid/supersedes-unknown", [
        {
            "code": "ASSURANCE_SUPERSEDES_UNKNOWN",
            "record_kind": "assurance",
            "record_id": "acme-current",
            "instance_path": "/supersedes_assurance_id",
            "related_ids": ["acme-missing-prior"],
        }
    ]),

    # --- ASSURANCE_SUPERSEDES_SELF case ---
    ("invalid/supersedes-self", [
        {
            "code": "ASSURANCE_SUPERSEDES_SELF",
            "record_kind": "assurance",
            "record_id": "acme-current",
            "instance_path": "/supersedes_assurance_id",
            "related_ids": ["acme-current"],
        }
    ]),

    # --- ASSURANCE_SUPERSEDES_VENDOR_MISMATCH case ---
    ("invalid/supersedes-vendor-mismatch", [
        {
            "code": "ASSURANCE_SUPERSEDES_VENDOR_MISMATCH",
            "record_kind": "assurance",
            "record_id": "acme-current",
            "instance_path": "/supersedes_assurance_id",
            "related_ids": ["beta-prior", "beta-vendor", "acme"],
        }
    ]),

    # --- ASSURANCE_TEMPORAL_ORDER_INVALID cases ---
    ("invalid/temporal-order-invalid", [
        {
            "code": "ASSURANCE_TEMPORAL_ORDER_INVALID",
            "record_kind": "assurance",
            "record_id": "acme-attestation",
            "instance_path": "/temporal_scope/reporting_period/end",
            "related_ids": ["start=2026-12-31", "end=2026-01-01"],
        },
        {
            "code": "ASSURANCE_TEMPORAL_ORDER_INVALID",
            "record_kind": "assurance",
            "record_id": "acme-certification",
            "instance_path": "/temporal_scope/valid_until",
            "related_ids": ["valid_from=2027-01-10", "valid_until=2026-01-10"],
        },
        {
            "code": "ASSURANCE_TEMPORAL_ORDER_INVALID",
            "record_kind": "assurance",
            "record_id": "acme-contractual",
            "instance_path": "/temporal_scope/effective_until_claimed",
            "related_ids": [
                "effective_from_claimed=2026-12-31",
                "effective_until_claimed=2026-01-01",
            ],
        },
    ]),
])
def test_assurance_semantic_matrix(case_id: str, expected: list[dict[str, Any]]) -> None:
    root = Path(f"tests/fixtures/assurance/semantic/{case_id}/repository")
    result = run_semantic_fixture_case(root)

    assert not result.structural_failures
    assert not result.repository_build_diagnostics

    actual = [semantic_diagnostic_contract(d) for d in result.semantic_diagnostics]
    expected_contract = [expected_semantic_contract(e) for e in expected]

    # The validator sorts diagnostics by (record_path, instance_path, code).
    # String comparison means "/evidence/..." sorts before "/vendor_id".
    # Therefore, if a fixture emits both, the source diagnostic will appear first.
    assert actual == expected_contract


def test_known_source_has_no_semantic_diagnostics() -> None:
    assert semantic_signatures("known-source") == []


def test_unknown_source_reports_evidence_source_index_zero() -> None:
    assert semantic_signatures("unknown-source") == [
        (
            assurance_validation.ASSURANCE_SOURCE_UNKNOWN,
            "assurance",
            "unknown-assurance",
            "/evidence/source_ids/0",
            ("missing-source",),
        )
    ]


def test_mixed_known_unknown_reports_only_unknown_index() -> None:
    assert semantic_signatures("mixed-known-unknown") == [
        (
            assurance_validation.ASSURANCE_SOURCE_UNKNOWN,
            "assurance",
            "mixed-assurance",
            "/evidence/source_ids/1",
            ("missing-source",),
        )
    ]


def test_two_unknown_sources_report_two_deterministic_diagnostics() -> None:
    assert semantic_signatures("two-unknown-sources") == [
        (
            assurance_validation.ASSURANCE_SOURCE_UNKNOWN,
            "assurance",
            "two-unknown-assurance",
            "/evidence/source_ids/0",
            ("missing-a",),
        ),
        (
            assurance_validation.ASSURANCE_SOURCE_UNKNOWN,
            "assurance",
            "two-unknown-assurance",
            "/evidence/source_ids/1",
            ("missing-b",),
        ),
    ]


def test_structurally_invalid_fixture_skips_builder_and_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_build(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("builder should not run after structural failure")

    def fail_semantics(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("semantics should not run after structural failure")

    monkeypatch.setattr(assurance_validation, "build_repository_snapshot", fail_build)
    monkeypatch.setattr(assurance_validation, "validate_assurance_repository", fail_semantics)
    result = load_case("structurally-invalid")
    assert result.build_result is None
    assert result.semantic_diagnostics == ()
    assert len(result.structural_errors) == 1
    assert any(
        error.keyword == "required" and error.missing_property == "advisory_boundary"
        for error in result.structural_errors[0].errors
    )


def test_duplicate_id_skips_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_semantics(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("semantics should not run after repository build failure")

    monkeypatch.setattr(assurance_validation, "validate_assurance_repository", fail_semantics)
    result = load_case("duplicate-id")
    assert result.structural_errors == ()
    assert result.build_result is not None
    assert result.build_result.snapshot is None
    assert [diagnostic_signature(diagnostic) for diagnostic in result.build_result.diagnostics] == [
        (
            assurance_validation.REPOSITORY_DUPLICATE_ID,
            "assurance",
            "duplicate-assurance",
            "/assurance_id",
            tuple(
                sorted(
                    str(path)
                    for path in [
                        FIXTURE_ROOT / "duplicate-id/assurances/duplicate-a.json",
                        FIXTURE_ROOT / "duplicate-id/assurances/duplicate-b.json",
                    ]
                )
            ),
        )
    ]
    assert result.semantic_diagnostics == ()


def test_wrong_record_kind_in_collection_raises() -> None:
    vendor_record = assurance_validation.RepositoryRecord.from_raw(
        spec=assurance_validation.VENDOR,
        payload={
            "schema_version": "0.1.0",
            "vendor_id": "wrong-kind-vendor",
        },
    )
    with pytest.raises(TypeError, match="source collection contains vendor record"):
        assurance_validation.build_repository_snapshot(
            {
                assurance_validation.SOURCE.kind: [vendor_record],
            }
        )


def test_snapshot_mappings_and_nested_payloads_are_immutable() -> None:
    result = load_case("known-source")
    assert result.build_result is not None
    snapshot = result.build_result.snapshot
    assert snapshot is not None
    with pytest.raises(TypeError):
        snapshot.sources["another-source"] = snapshot.sources["known-source"]  # type: ignore[index]

    assurance = snapshot.assurances["known-assurance"]
    with pytest.raises(TypeError):
        assurance.payload["evidence"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        assurance.payload["evidence"]["source_ids"] = ("other-source",)  # type: ignore[index]
    assert isinstance(assurance.payload["evidence"]["source_ids"], tuple)


def test_unknown_fixture_directory_fails() -> None:
    with pytest.raises(ValueError, match="unknown fixture directory widgets"):
        load_assurance_fixture_repository(
            LAYOUT_ERROR_ROOT / "unknown-directory",
            validator_factory=build_validator_for_record_kind,
        )


def test_unsupported_fixture_file_fails() -> None:
    with pytest.raises(ValueError, match="unsupported fixture extension"):
        load_assurance_fixture_repository(
            LAYOUT_ERROR_ROOT / "unsupported-file",
            validator_factory=build_validator_for_record_kind,
        )
