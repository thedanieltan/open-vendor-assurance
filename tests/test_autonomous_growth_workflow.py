"""WP40A Issue 3: the scheduled growth workflow gates and dispatches only.

It must not itself write catalog truth or merge; it runs the controller as a
gate and dispatches the single existing mutation workflow capped at one vendor.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/autonomous-catalog-growth.yml")


def _load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_exists_and_is_scheduled():
    wf = _load()
    triggers = wf.get("on") or wf.get(True)
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert triggers["schedule"][0]["cron"]


def test_workflow_has_no_catalog_write_permissions():
    wf = _load()
    # may dispatch (actions: write) but never write contents or PRs
    assert wf["permissions"] == {"contents": "read", "actions": "write"}


def test_workflow_runs_controller_and_dispatches_single_mutation():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m tools.openva.autonomous_growth_controller" in text
    assert "promotion_plan_mode=machine-provisional-from-queue" in text
    assert "max_promotion_actions_per_pr=1" in text
    assert "gh workflow run" in text
    # gate: dispatch only happens when the controller authorises the cycle
    assert "env.GROWTH_PROCEED == 'true'" in text
    # no direct catalog mutation / merge from this workflow
    assert "gh pr merge" not in text


def test_workflow_uses_live_state_source():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github_live" in text
