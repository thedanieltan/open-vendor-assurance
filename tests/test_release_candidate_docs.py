from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


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
