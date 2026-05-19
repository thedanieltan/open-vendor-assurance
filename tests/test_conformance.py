from pathlib import Path

from tools.openva.conformance import validate_pack_dir
from tools.openva.indexes import ROOT

FIXTURES = ROOT / "fixtures" / "packs"


def test_minimal_valid_fixture_passes_conformance():
    assert validate_pack_dir(FIXTURES / "minimal-valid") == []


def test_valid_bot_protected_observation_fixture_passes_conformance():
    assert validate_pack_dir(FIXTURES / "valid-bot-protected-observation") == []


def test_valid_brand_only_fallback_fixture_passes_conformance():
    assert validate_pack_dir(FIXTURES / "valid-brand-only-fallback") == []


def test_missing_guarantee_fixture_fails_conformance():
    failures = validate_pack_dir(FIXTURES / "invalid-missing-guarantee")

    assert any("non_advisory" in failure for failure in failures)


def test_unsafe_url_fixture_fails_conformance():
    failures = validate_pack_dir(FIXTURES / "invalid-unsafe-url")

    assert any("source_url" in failure and "localhost" in failure for failure in failures)


def test_advisory_wording_fixture_fails_conformance():
    failures = validate_pack_dir(FIXTURES / "invalid-advisory-wording")

    assert any("prohibited advisory wording" in failure and "recommended" in failure for failure in failures)


def test_missing_pack_file_fails_conformance(tmp_path: Path):
    failures = validate_pack_dir(tmp_path)

    assert failures == [f"{tmp_path / 'openva-pack.json'}: missing openva-pack.json"]
