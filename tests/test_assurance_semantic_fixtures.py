from __future__ import annotations

from pathlib import Path

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
