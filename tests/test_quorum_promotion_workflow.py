"""WP37 quorum-promotion workflow wiring tests (YAML parse + step contracts)."""

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


def test_agent_automerge_has_quorum_promotion_job_requiring_both_labels():
    workflow = load(AUTOMERGE)
    assert "quorum-promotion" in workflow["jobs"]
    condition = workflow["jobs"]["quorum-promotion"]["if"]
    assert "quorum-promotion" in condition
    assert "automerge:quorum-promotion" in condition


def test_agent_automerge_quorum_job_gates_before_merge():
    steps = job_steps(load(AUTOMERGE), "quorum-promotion")
    names = [s.get("name") for s in steps]
    check = step(steps, "Check quorum-promotion automerge eligibility")
    assert "python -m tools.openva.quorum_promotion_automerge check" in check["run"]
    drift = step(steps, "Refuse generated drift")
    assert drift["run"] == "git diff --exit-code openva-pack.json indexes/ dist/"
    gate = step(steps, "Run source-intelligence release gate (pr profile)")
    assert "release_gates check --profile pr" in gate["run"]
    for required in (
        "Check quorum-promotion automerge eligibility",
        "Refuse generated drift",
        "Run source-intelligence release gate (pr profile)",
        "Run quorum-promotion tests",
    ):
        assert names.index(required) < names.index("Enable GitHub native auto-merge")


def test_candidate_promotion_has_quorum_promotion_job_with_quorum_and_controller():
    workflow = load(PROMOTION)
    assert "quorum-promotion" in workflow["jobs"]
    text = PROMOTION.read_text(encoding="utf-8")
    # Promotion mode is an explicit dispatch option (YAML parses the `on:` key as
    # the boolean True, so read the options off the parsed mapping under it).
    options = workflow[True]["workflow_dispatch"]["inputs"]["promotion_plan_mode"]["options"]
    assert "quorum-promotion" in options
    # Selection + status-only apply via the quorum_promotion module.
    assert "python -m tools.openva.quorum_promotion select" in text
    assert "python -m tools.openva.quorum_promotion promote" in text
    # Marker label applied directly; merge label only via the not_before controller.
    assert "--add-label quorum-promotion" in text
    assert "--add-label automerge:quorum-promotion" in text
    assert "machine_provisional_controller ready" in text
    assert "--decision promote" in text
    # The PR-opening step uses the workflow-triggering token so the merge lane fires.
    assert "secrets.OPENVA_AUTOMERGE_TOKEN || github.token" in text
    # Labels are self-provisioned so the lane needs no manual setup.
    assert "gh label create quorum-promotion" in text
    assert "gh label create automerge:quorum-promotion" in text
