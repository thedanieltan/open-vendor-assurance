"""WP40A Issue 10: documentation states the autonomous model and cannot revert.

These regression checks keep the narrative docs aligned with the autonomous
catalog architecture: routine catalog records do not require human approval, the
full lifecycle (including the fail-closed states) is named, and human review is
retained only for code / schema / workflow / policy / authority changes.
"""

from __future__ import annotations

from pathlib import Path

README = Path("README.md")
GOVERNANCE = Path("GOVERNANCE.md")
SUBMISSION_INTAKE = Path("docs/submission-intake.md")
AUTONOMY_POLICY = Path("docs/catalog-autonomy-policy.md")

LIFECYCLE_STATES = (
    "machine_provisional",
    "active",
    "deferred",
    "rejected",
    "quarantined",
    "rolled_back",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_governance_does_not_blanket_require_human_review_for_new_vendors():
    text = _read(GOVERNANCE)
    # the superseded blanket list item must be gone
    assert "- new vendors;" not in text
    # and the autonomous operation must be stated
    assert "Routine catalog growth and maintenance run" in text
    assert "do **not** require human approval" in text or "do not require human approval" in text


def test_governance_retains_human_review_for_governed_change_classes():
    text = _read(GOVERNANCE).lower()
    for change in ("code changes", "schema changes", "workflow changes", "policy thresholds", "permissions"):
        assert change in text
    assert "authority" in text


def test_governance_names_fail_closed_states():
    text = _read(GOVERNANCE)
    for state in ("deferred", "rejected", "quarantined", "rolled_back"):
        assert state in text


def test_readme_states_autonomous_model_and_lifecycle():
    text = _read(README)
    assert "autonomous" in text.lower()
    assert "without human approval" in text.lower()
    for state in LIFECYCLE_STATES:
        assert state in text, f"README missing lifecycle state {state}"
    # README must not claim routine catalog changes are review-gated
    assert "catalog changes remain review-gated" not in text


def test_submission_intake_describes_shared_autonomous_lifecycle():
    text = _read(SUBMISSION_INTAKE)
    assert "candidate-record.schema.json" in text
    assert "machine_provisional" in text
    assert "submission_bridge.py" in text
    # no maintainer-gates-routine-submission claim
    assert "A maintainer triages the claim." not in text


def test_autonomy_policy_exists_and_is_referenced():
    assert AUTONOMY_POLICY.exists()
    assert "catalog-autonomy-policy.md" in _read(README) or "catalog-autonomy-policy.md" in _read(GOVERNANCE)
