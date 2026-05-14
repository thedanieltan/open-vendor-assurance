from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_agent_control_plane_docs_exist():
    required_paths = [
        "docs/agent-control-plane.md",
        "docs/agent-runbook.md",
        "prompts/catalog-curator-agent.md",
        "prompts/source-refinement-agent.md",
        "prompts/observation-review-agent.md",
        "catalog-batches/backlog/README.md",
    ]

    for path in required_paths:
        assert (ROOT / path).exists(), path


def test_agent_control_plane_defines_agent_classes_and_human_gates():
    text = read("docs/agent-control-plane.md")

    for phrase in [
        "Catalog curator agent",
        "Source refinement agent",
        "Observation review agent",
        "Backlog curator agent",
        "Release readiness agent",
        "Human-gated",
        "merging to main",
        "schema changes",
        "workflow changes",
        "writing ambiguous observations",
    ]:
        assert phrase in text


def test_agent_control_plane_preserves_non_advisory_boundary():
    text = read("docs/agent-control-plane.md")

    for prohibited_claim in [
        "compliant",
        "safe",
        "approved",
        "recommended",
        "low risk",
        "high risk",
        "certified by OpenVA",
    ]:
        assert prohibited_claim in text

    assert "Agents must not describe vendors or sources as" in text
    assert "Vendor publishes a public security page." in text


def test_agent_runbook_has_phase_and_branch_safety_steps():
    text = read("docs/agent-runbook.md")

    for phrase in [
        "Confirm the assigned phase label is free",
        "Do not use a phase label that is already assigned",
        "git checkout main",
        "git pull origin main",
        "Agents must never force-push over another agent's branch",
    ]:
        assert phrase in text


def test_catalog_curator_prompt_limits_catalog_scope():
    text = read("prompts/catalog-curator-agent.md")

    for allowed in [
        "catalog-batches/**",
        "data/vendors/**",
        "indexes/**",
        "openva-pack.json",
    ]:
        assert allowed in text

    for blocked in [
        "schemas/**",
        "tools/**",
        "tests/**",
        ".github/**",
        "README.md",
    ]:
        assert blocked in text


def test_source_and_observation_prompts_do_not_allow_mutating_reports_by_default():
    source_text = read("prompts/source-refinement-agent.md")
    observation_text = read("prompts/observation-review-agent.md")

    assert "Open a catalog PR only when the replacement is clear" in source_text
    assert "Do not write ambiguous observations by default" in source_text
    assert "You must not:" in observation_text
    assert "write observation records" in observation_text
    assert "update vendor/source/artifact records" in observation_text


def test_backlog_readme_marks_backlog_as_planning_not_catalog_records():
    text = read("catalog-batches/backlog/README.md")

    assert "Backlog files are not generated catalog records" in text
    assert "A backlog candidate becomes a catalog batch only when a maintainer assigns a phase label" in text
    assert "Do not include:" in text
    assert "vendor scores" in text
