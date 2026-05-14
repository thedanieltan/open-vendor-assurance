from pathlib import Path

from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, SCHEMA_VERSION

REQUIRED_RELEASE_COMMANDS = [
    "python -m tools.openva.validate build-indexes",
    "python -m tools.openva.validate validate",
    "pytest -q",
    "python -m tools.openva.conformance fixtures/packs/minimal-valid",
    "python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation",
]


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_v010_release_candidate_doc_exists_and_mentions_current_identifiers():
    text = read("docs/v0.1.0-release-candidate.md")

    assert "v0.1.0" in text
    assert "package version: 0.1.0" in text
    assert f"record schema_version: {SCHEMA_VERSION}" in text
    assert f"profileId: {EXPORT_PROFILE_ID}" in text
    assert f"schemaVersion: {EXPORT_SCHEMA_VERSION}" in text
    assert "packId: open-vendor-assurance" in text


def test_release_candidate_doc_includes_required_commands():
    text = read("docs/v0.1.0-release-candidate.md")

    for command in REQUIRED_RELEASE_COMMANDS:
        assert command in text
    assert "git diff --exit-code openva-pack.json indexes/" in text


def test_release_candidate_doc_preserves_scope_exclusions():
    text = read("docs/v0.1.0-release-candidate.md").lower()

    for phrase in [
        "raw vendor document mirrors",
        "private or gated materials",
        "authenticated trust-center materials",
        "customer-specific or bespoke agreements",
        "vendor-risk advice",
        "vendor approval",
        "risk scoring",
    ]:
        assert phrase in text


def test_public_launch_cutover_doc_has_positioning_and_sequence():
    text = read("docs/public-launch-cutover.md")

    assert "public-source-only, metadata-first registry" in text
    assert "Before changing repository visibility" in text
    assert "Visibility cutover" in text
    assert "Launch announcement template" in text
    assert "Emergency rollback posture" in text


def test_public_launch_cutover_doc_avoids_advisory_positioning():
    text = read("docs/public-launch-cutover.md").lower()

    for phrase in [
        "do not use these descriptions",
        "compliance database",
        "vendor risk scoring system",
        "certification authority",
        "procurement recommendation engine",
        "does not provide legal",
    ]:
        assert phrase in text


def test_docs_index_links_release_candidate_and_cutover_docs():
    text = read("docs/index.md")

    assert "docs/v0.1.0-release-candidate.md" in text
    assert "docs/public-launch-cutover.md" in text
