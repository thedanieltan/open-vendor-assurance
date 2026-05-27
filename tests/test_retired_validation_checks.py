from pathlib import Path

RETIRED_VALIDATE_CONTEXT = "validate / validate"

REQUIRED_VALIDATE_CONTEXTS = [
    "validate / repository-integrity",
    "validate / workflow-operating-model",
    "validate / catalog-growth",
    "validate / source-maintenance",
    "validate / catalog-quality",
    "validate / release-site",
    "validate / full-suite",
]

OPERATIONAL_LAUNCH_DOCS = [
    Path("docs/public-launch-cutover.md"),
    Path("docs/v0.1.0-public-launch-readiness.md"),
    Path("docs/v0.1.0-release-candidate.md"),
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operational_launch_docs_do_not_require_retired_validate_context():
    for path in OPERATIONAL_LAUNCH_DOCS:
        assert RETIRED_VALIDATE_CONTEXT not in read(path), path


def test_branch_protection_doc_lists_partitioned_validate_contexts():
    text = read(Path("docs/ci-and-branch-protection.md"))

    for context in REQUIRED_VALIDATE_CONTEXTS:
        assert context in text

    assert "do not keep that old status context as a required branch-protection check" in text
