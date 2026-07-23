"""The scheduled-workflow surface stays declared and within its runs/week budget.

WP-OPENVA-WORKFLOW-SCHEDULE-BUDGET-01.

Complements the workflow-inventory contract (which pins trigger types) by pinning schedule
*frequency*. Fails closed on an undeclared scheduled workflow, a silent cron change, a
per-workflow over-budget, or an aggregate over-budget.
"""

from __future__ import annotations

import copy

import pytest

from tools.openva import workflow_schedule_budget as budget


def test_committed_schedule_surface_is_declared_and_within_budget():
    assert budget.check() == []


def test_every_scheduled_workflow_is_declared():
    declared = {entry["name"] for entry in budget.load_contract()["workflows"]}
    assert set(budget.scheduled_workflows()) <= declared


def test_runs_per_week_matches_known_cadences():
    assert budget.runs_per_week("*/10 * * * *") == pytest.approx(1008)
    assert budget.runs_per_week("17 23 * * *") == pytest.approx(7)
    assert budget.runs_per_week("17 8 * * 1,3,5") == pytest.approx(3)
    assert budget.runs_per_week("41 6 * * 1") == pytest.approx(1)
    assert budget.runs_per_week("0 3 * * 0") == pytest.approx(1)


def _write_contract(tmp_path, contract):
    import yaml

    path = tmp_path / "workflow-schedule-budget.yaml"
    path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return path


def test_fails_closed_when_a_scheduled_workflow_is_undeclared(tmp_path):
    contract = copy.deepcopy(budget.load_contract())
    contract["workflows"] = [e for e in contract["workflows"] if e["name"] != "agent-automerge.yml"]
    problems = budget.check(_write_contract(tmp_path, contract))
    assert any("agent-automerge.yml" in p and "not declared" in p for p in problems)


def test_fails_closed_on_silent_cron_change(tmp_path):
    contract = copy.deepcopy(budget.load_contract())
    for entry in contract["workflows"]:
        if entry["name"] == "agent-automerge.yml":
            entry["crons"] = ["*/30 * * * *"]  # contract claims a slower cadence than reality
    problems = budget.check(_write_contract(tmp_path, contract))
    assert any("agent-automerge.yml" in p and "do not match" in p for p in problems)


def test_fails_closed_when_a_workflow_exceeds_its_ceiling(tmp_path):
    contract = copy.deepcopy(budget.load_contract())
    for entry in contract["workflows"]:
        if entry["name"] == "agent-automerge.yml":
            entry["max_runs_per_week"] = 10  # far below its real ~1008/week
    problems = budget.check(_write_contract(tmp_path, contract))
    assert any("agent-automerge.yml" in p and "exceeds declared ceiling" in p for p in problems)


def test_fails_closed_when_aggregate_exceeds_budget(tmp_path):
    contract = copy.deepcopy(budget.load_contract())
    contract["aggregate_max_runs_per_week"] = 100  # below the real ~1035/week total
    problems = budget.check(_write_contract(tmp_path, contract))
    assert any("aggregate" in p and "exceeds the declared budget" in p for p in problems)
