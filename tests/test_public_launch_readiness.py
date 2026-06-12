from pathlib import Path

REQUIRED_DOCS = [
    "README.md",
    "DISCLAIMER.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "MAINTAINERS.md",
    "SECURITY.md",
    "docs/index.md",
    "docs/public-launch-checklist.md",
    "docs/roadmap.md",
    "docs/triage-policy.md",
    "docs/first-good-issue-policy.md",
    "docs/versioning-policy.md",
    "docs/release-policy.md",
    "docs/release-checklist.md",
    "docs/consumer-conformance-fixtures.md",
]


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_public_launch_docs_exist():
    for path in REQUIRED_DOCS:
        assert Path(path).exists(), path


def test_readme_has_public_launch_start_here_navigation():
    text = read("README.md")

    assert "## Start here" in text
    assert "docs/consumer-conformance-fixtures.md" in text
    assert "docs/versioning-policy.md" in text
    assert "docs/release-policy.md" in text
    assert "docs/public-launch-checklist.md" in text
    assert "docs/triage-policy.md" in text
    assert "docs/index.md" not in text or "docs/index.md" in read("docs/index.md")


def test_readme_preserves_non_advisory_public_source_boundary():
    text = read("README.md").lower()

    assert "public-source-only" in text
    assert "metadata-first" in text
    assert "not a legal" in text
    assert "vendor-risk advice" in text
    assert "raw document mirroring" in text
    assert "anti-bot bypass" in text
    assert "authenticated trust-center" in text


def test_docs_index_links_launch_and_consumer_docs():
    text = read("docs/index.md")

    expected = [
        "docs/public-launch-checklist.md",
        "docs/roadmap.md",
        "docs/triage-policy.md",
        "docs/catalog-agent-protocol.md",
        "docs/observation-result-taxonomy.md",
        "docs/source-trust/observation-retention-policy.md",
        "docs/source-trust/SOURCE_TRUST_OPERATIONS_RUNBOOK.md",
        "docs/consumer-conformance-fixtures.md",
        "docs/versioning-policy.md",
        "docs/release-policy.md",
        "docs/release-checklist.md",
    ]
    for item in expected:
        assert item in text


def test_source_observation_retention_policy_documents_retention_strategy():
    # WP32 amended the earlier full-deferral posture: full per-run
    # observations stay artifact-only; only a compact change-event ledger is
    # committed, via reviewed PRs.
    text = read("docs/source-trust/observation-retention-policy.md")

    for phrase in [
        "Full per-run observation records remain artifact-only.",
        "compact, append-only",
        "Only **events** are committed",
        "bounded by the\n  actual change rate",
        "maintenance/source-observations/events/YYYY-MM.ndjson",
        "only through reviewed pull requests",
        "Workflows never commit\n  ledger files",
        "latest-source-health.json",
        "public/source-health-snapshot.json",
        "The site falls back to `Not yet verified` labels",
        "Change release gate behavior.",
        "Mutate catalog data.",
    ]:
        assert phrase in text


def test_source_trust_operations_runbook_documents_operating_policy():
    text = read("docs/source-trust/SOURCE_TRUST_OPERATIONS_RUNBOOK.md")
    index = read("docs/index.md")

    assert "docs/source-trust/SOURCE_TRUST_OPERATIONS_RUNBOOK.md" in index
    for phrase in [
        "source-refinement",
        "automerge:p0-source-repair",
        "source-repair-pr-cleanup",
        "Confirmed P0 repair",
        "Layer 2C quality fixes",
        "Quality refinement is human reviewed only",
        "max 10 records per PR",
        "5-10 records per batch",
        "release-candidate",
        "defaults to `enforce`",
    ]:
        assert phrase in text


def test_launch_checklist_has_required_validation_commands():
    text = read("docs/public-launch-checklist.md") + "\n" + read("README.md")

    commands = [
        "python -m tools.openva.validate build-indexes",
        "python -m tools.openva.validate validate",
        "pytest -q",
        "python -m tools.openva.conformance fixtures/packs/minimal-valid",
        "python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation",
    ]
    for command in commands:
        assert command in text


def test_disclaimer_and_readme_align_on_no_advice_boundary():
    disclaimer = read("DISCLAIMER.md").lower()
    readme = read("README.md").lower()

    for phrase in [
        "legal",
        "compliance",
        "procurement",
        "security",
        "kyc",
        "aml",
        "vendor-risk",
    ]:
        assert phrase in disclaimer
        assert phrase in readme


def test_public_launch_copy_positions_v010_as_infrastructure_launch():
    text = "\n".join(
        read(path).lower()
        for path in [
            "README.md",
            "docs/public-launch-checklist.md",
            "docs/v0.1.0-public-launch-readiness.md",
            "docs/roadmap.md",
            "docs/release-downloads.md",
        ]
    )

    for phrase in [
        "infrastructure launch",
        "seed dataset",
        "not a completeness claim",
        "does not operate a public upload service",
        "optional self-hosted match service",
    ]:
        assert phrase in text
