"""WP38b rollback workflow wiring tests (YAML parse + step contracts)."""

from __future__ import annotations

from pathlib import Path

import yaml

AUTOMERGE = Path(".github/workflows/agent-automerge.yml")
PROMOTION = Path(".github/workflows/candidate-promotion-pr.yml")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def step(steps: list[dict], name: str) -> dict:
    return next(s for s in steps if s.get("name") == name)


def test_agent_automerge_has_rollback_job_requiring_both_labels():
    workflow = load(AUTOMERGE)
    assert "rollback" in workflow["jobs"]
    condition = workflow["jobs"]["rollback"]["if"]
    assert "rollback" in condition
    assert "automerge:rollback" in condition


def test_agent_automerge_rollback_job_gates_before_merge():
    steps = load(AUTOMERGE)["jobs"]["rollback"]["steps"]
    names = [s.get("name") for s in steps]
    check = step(steps, "Check rollback automerge eligibility")
    assert "python -m tools.openva.rollback_automerge check" in check["run"]
    drift = step(steps, "Refuse generated drift")
    assert drift["run"] == "git diff --exit-code openva-pack.json indexes/ dist/"
    for required in (
        "Check rollback automerge eligibility",
        "Refuse generated drift",
        "Run source-intelligence release gate (pr profile)",
        "Run rollback tests",
    ):
        assert names.index(required) < names.index("Enable GitHub native auto-merge")


def test_promotion_workflow_has_rollback_job_dispatch_only():
    workflow = load(PROMOTION)
    assert "source-rollback" in workflow["jobs"]
    cond = workflow["jobs"]["source-rollback"]["if"]
    # Level-5 rollback is deliberate: dispatch-only, never scheduled.
    assert "workflow_dispatch" in cond
    assert "schedule" not in cond
    text = PROMOTION.read_text(encoding="utf-8")
    assert "python -m tools.openva.rollback rollback" in text
    assert "--add-label rollback" in text
    assert "--add-label automerge:rollback" in text
    assert "machine_provisional_controller ready" in text
    assert "--decision rollback" in text
    assert "secrets.OPENVA_AUTOMERGE_TOKEN || github.token" in text
    assert "gh label create rollback" in text
    options = (workflow.get(True) or workflow.get("on"))["workflow_dispatch"]["inputs"]["promotion_plan_mode"]["options"]
    assert "rollback" in options
    assert "rollback_decision_id" in (workflow.get(True) or workflow.get("on"))["workflow_dispatch"]["inputs"]
