from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_public_launch_readiness_record_exists_and_is_linked():
    assert Path("docs/v0.1.0-public-launch-readiness.md").is_file()
    assert "docs/v0.1.0-public-launch-readiness.md" in read("docs/index.md")


def test_public_launch_readiness_records_final_dry_run_results():
    text = read("docs/v0.1.0-public-launch-readiness.md")

    for phrase in [
        "release-candidate-ready",
        "OpenVA validation passed.",
        "123 passed.",
        "Release smoke test passed.",
        "no tracked Python bytecode files",
    ]:
        assert phrase in text


def test_public_launch_readiness_records_observation_backlog_as_non_blocking():
    text = read("docs/v0.1.0-public-launch-readiness.md")

    for phrase in [
        "Total observed sources: 58",
        "Human review required: 36",
        "bot_protected: 26",
        "fetch_failed: 9",
        "size_limited: 1",
        "non-blocking source-quality backlog",
    ]:
        assert phrase in text


def test_public_launch_readiness_keeps_cutover_manual():
    text = read("docs/v0.1.0-public-launch-readiness.md")

    for phrase in [
        "does not tag a release",
        "does not publish a release",
        "change repository visibility",
        "manual maintainer decisions",
        "final release/tag/visibility decision is manual",
    ]:
        assert phrase in text


def test_public_launch_readiness_preserves_launch_boundaries():
    text = read("docs/v0.1.0-public-launch-readiness.md")

    for phrase in [
        "public-source-only, metadata-first",
        "unsafe URLs",
        "private material exposure",
        "advisory wording",
        "workflow permission escalation",
        "compliance database",
        "vendor risk scoring system",
    ]:
        assert phrase in text
