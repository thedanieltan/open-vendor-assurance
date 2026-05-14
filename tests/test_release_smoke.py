from tools.openva import release_smoke
from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, SCHEMA_VERSION


def test_release_smoke_docs_exist():
    assert release_smoke.check_docs_exist() == []


def test_release_smoke_pack_identifiers_match_current_contract():
    assert release_smoke.check_pack_identifiers() == []


def test_release_smoke_docs_contain_required_commands_and_identifiers():
    assert release_smoke.check_release_docs() == []


def test_release_smoke_conformance_fixtures_pass():
    assert release_smoke.check_conformance_fixtures() == []


def test_release_smoke_required_constants_are_expected():
    assert SCHEMA_VERSION == "0.1.0"
    assert EXPORT_PROFILE_ID == "openva.public-metadata.v1"
    assert EXPORT_SCHEMA_VERSION == "openva-export-pack.v1"


def test_release_smoke_detects_missing_docs(monkeypatch):
    monkeypatch.setattr(release_smoke, "REQUIRED_RELEASE_DOCS", ["missing-release-doc.md"])

    assert release_smoke.check_docs_exist() == ["missing-release-doc.md: required release document is missing"]


def test_release_smoke_detects_missing_doc_command(monkeypatch):
    monkeypatch.setattr(release_smoke, "REQUIRED_RELEASE_COMMANDS", ["missing-release-command"])

    assert release_smoke.check_release_docs() == ["release docs: missing required command `missing-release-command`"]


def test_release_smoke_can_run_without_git_diff_check(monkeypatch):
    monkeypatch.setattr(release_smoke, "validate_all", lambda: 0)
    assert release_smoke.run_release_smoke(check_git_diff=False) == []


def test_release_smoke_reports_validator_failure(monkeypatch):
    monkeypatch.setattr(release_smoke, "validate_all", lambda: 1)

    failures = release_smoke.run_release_smoke(check_git_diff=False)

    assert "python -m tools.openva.validate validate failed" in failures
