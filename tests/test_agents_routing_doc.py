"""WP40C AGENTS.md routing regression.

The root routing document must exist, route to canonical files that exist, and
declare the autonomous (non-human-approval) operating model with its stop
conditions. This locks the routing surface so it cannot silently rot.
"""

from __future__ import annotations

import re
from pathlib import Path

AGENTS = Path("AGENTS.md")

REQUIRED_CANONICAL_FILES = [
    "config/bot-constitution.yaml",
    "docs/operations/contracts/bot-authority.yaml",
    "docs/operations/contracts/bot-queue-policy.yaml",
    "docs/operations/contracts/bot-work-priority.yaml",
    "config/release-gates.yaml",
    "config/machine-evidence-thresholds.yaml",
    "config/automerge-policy.yaml",
    "docs/operations/contracts/workflow-inventory.yaml",
    "schemas/openva/candidate-record.schema.json",
    "tools/openva/submission_bridge.py",
    "tools/openva/source_repair_classifier.py",
    "tools/openva/rollback_eligibility.py",
    "tools/openva/work_priority.py",
]

REQUIRED_SECTIONS = [
    "Repository purpose",
    "Prohibited actions",
    "Canonical contracts",
    "Required reading by task type",
    "Permitted paths",
    "Required tests",
    "Stop conditions",
    "Documentation conflict order",
]


def test_agents_md_exists():
    assert AGENTS.exists(), "root AGENTS.md must exist"


def test_agents_md_has_required_sections():
    text = AGENTS.read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in text, f"AGENTS.md missing section: {section}"


def test_referenced_canonical_files_exist():
    text = AGENTS.read_text(encoding="utf-8")
    for ref in REQUIRED_CANONICAL_FILES:
        assert ref in text, f"AGENTS.md should route to {ref}"
        assert Path(ref).exists(), f"AGENTS.md routes to missing file {ref}"


def test_every_markdown_link_target_in_repo_exists():
    text = AGENTS.read_text(encoding="utf-8")
    # capture inline links like [label](path) that point at repo paths
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith("http") or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        assert Path(path).exists(), f"AGENTS.md links to missing path {path}"


def test_declares_autonomous_no_human_approval_model():
    text = AGENTS.read_text(encoding="utf-8").lower()
    assert "do not require human approval" in text or "does not require human approval" in text or "no human approval" in text.replace("require human approval", "no human approval")
    # fail-closed states must be named
    for state in ("deferred", "rejected", "quarantined", "rolled_back"):
        assert state in text
    # conflict order must put machine-readable authority contracts first
    assert "machine-readable authority contracts" in text


def test_conflict_order_is_authority_first():
    text = AGENTS.read_text(encoding="utf-8")
    order_section = text.split("Documentation conflict order", 1)[1]
    authority = order_section.index("authority contracts")
    narrative = order_section.index("narrative documentation")
    assert authority < narrative
