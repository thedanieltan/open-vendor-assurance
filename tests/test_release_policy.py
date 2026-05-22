import re

from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, SCHEMA_VERSION


def test_export_profile_and_schema_constants_are_current():
    assert EXPORT_PROFILE_ID == "openva.public-metadata.v1"
    assert EXPORT_SCHEMA_VERSION == "openva-export-pack.v1"
    assert SCHEMA_VERSION == "0.1.0"


def test_versioning_policy_mentions_current_export_contract():
    text = open("docs/versioning-policy.md", encoding="utf-8").read()

    assert EXPORT_PROFILE_ID in text
    assert EXPORT_SCHEMA_VERSION in text
    assert SCHEMA_VERSION in text


def test_release_policy_preserves_non_advisory_boundary():
    text = open("docs/release-policy.md", encoding="utf-8").read().lower()

    assert "not legal" in text
    assert "does not provide legal" in text
    assert "raw vendor documents are not release artifacts by default" in text


def test_release_checklist_includes_required_commands():
    text = open("docs/release-checklist.md", encoding="utf-8").read()

    required_commands = [
        "python -m tools.openva.validate build-indexes",
        "python -m tools.openva.validate validate",
        "pytest -q",
        "python -m tools.openva.conformance fixtures/packs/minimal-valid",
        "python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation",
    ]
    for command in required_commands:
        assert command in text


def test_release_tags_are_semver_like():
    text = open("docs/release-checklist.md", encoding="utf-8").read()

    assert re.search(r"v0\.1\.0", text)
    assert re.search(r"v0\.1\.1", text)
    assert re.search(r"v0\.2\.0", text)


def test_deterministic_pack_timestamp_docs_preserve_freshness_boundary():
    text = "\n".join(
        [
            open("docs/versioning-policy.md", encoding="utf-8").read(),
            open("docs/release-downloads.md", encoding="utf-8").read(),
            open("docs/openva-match-service-contract.md", encoding="utf-8").read(),
            open("README.md", encoding="utf-8").read(),
        ]
    )

    for phrase in [
        "deterministic rebuilds",
        "not a catalog freshness signal",
        "provenance.collected_at",
        "detected_at",
        "observed_at",
        "release tag or repository commit SHA",
    ]:
        assert phrase in text
