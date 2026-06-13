"""WP38a quarantine workflow wiring tests (YAML parse + step contracts)."""

from __future__ import annotations

from pathlib import Path

import yaml

AUTOMERGE = Path(".github/workflows/agent-automerge.yml")
PROMOTION = Path(".github/workflows/candidate-promotion-pr.yml")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def job_steps(workflow: dict, job: str) -> list[dict]:
    return workflow["jobs"][job]["steps"]


def step(steps: list[dict], name: str) -> dict:
    return next(s for s in steps if s.get("name") == name)


def test_agent_automerge_has_quarantine_job_requiring_both_labels():
    workflow = load(AUTOMERGE)
    assert "quarantine" in workflow["jobs"]
    condition = workflow["jobs"]["quarantine"]["if"]
    assert "quarantine" in condition
    assert "automerge:quarantine" in condition


def test_agent_automerge_quarantine_job_gates_before_merge():
    steps = job_steps(load(AUTOMERGE), "quarantine")
    names = [s.get("name") for s in steps]
    check = step(steps, "Check quarantine automerge eligibility")
    assert "python -m tools.openva.quarantine_automerge check" in check["run"]
    drift = step(steps, "Refuse generated drift")
    assert drift["run"] == "git diff --exit-code openva-pack.json indexes/ dist/"
    for required in (
        "Check quarantine automerge eligibility",
        "Refuse generated drift",
        "Run source-intelligence release gate (pr profile)",
        "Run quarantine tests",
    ):
        assert names.index(required) < names.index("Enable GitHub native auto-merge")


def test_promotion_workflow_has_quarantine_job():
    workflow = load(PROMOTION)
    assert "source-quarantine" in workflow["jobs"]
    text = PROMOTION.read_text(encoding="utf-8")
    assert "python -m tools.openva.source_quarantine select" in text
    assert "python -m tools.openva.source_quarantine quarantine" in text
    assert "--add-label quarantine" in text
    assert "--add-label automerge:quarantine" in text
    assert "machine_provisional_controller ready" in text
    assert "--decision quarantine" in text
    assert "secrets.OPENVA_AUTOMERGE_TOKEN || github.token" in text
    assert "gh label create quarantine" in text
    assert "gh label create automerge:quarantine" in text
    # quarantine is an explicit dispatch mode.
    options = (workflow.get(True) or workflow.get("on"))["workflow_dispatch"]["inputs"]["promotion_plan_mode"]["options"]
    assert "quarantine" in options


def test_quarantine_job_runs_on_schedule():
    workflow = load(PROMOTION)
    triggers = workflow.get(True) or workflow.get("on")
    assert "schedule" in triggers
    quarantine_if = workflow["jobs"]["source-quarantine"]["if"]
    assert "schedule" in quarantine_if
    assert "quarantine" in quarantine_if
