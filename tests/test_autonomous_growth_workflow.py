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
    # WP-OPENVA-CANDIDATE-ACTIVATION-01 adds an event trigger on the candidate
    # store so a newly-merged candidate enters the same gated decision path.
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule", "push"}
    assert triggers["schedule"][0]["cron"]
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["push"]["paths"] == ["maintenance/candidates/*.json"]


def test_workflow_has_no_catalog_write_permissions():
    wf = _load()
    # may dispatch (actions: write) but never write contents or PRs
    assert wf["permissions"] == {"contents": "read", "actions": "write"}


def test_workflow_runs_controller_and_dispatches_candidate_bound_mutation():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m tools.openva.autonomous_growth_controller" in text
    # eligibility is recomputed (never trusting the stored state) and each
    # eligible candidate carries its bound path
    assert "candidate_activation collect-eligible" in text
    # the controller-selected candidate is dispatched with its full binding
    assert "promotion_plan_mode=candidate-bound" in text
    assert "max_promotion_actions_per_pr=1" in text
    for field in ("candidate_id", "candidate_path", "content_digest", "selected_vendor", "candidate_origin"):
        assert field in text
    assert "gh workflow run" in text
    # gate: dispatch only happens when the controller authorises the cycle
    assert "env.GROWTH_PROCEED == 'true'" in text
    # no direct catalog mutation / merge from this workflow
    assert "gh pr merge" not in text


def test_workflow_uses_live_state_source():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github_live" in text


def test_growth_lane_capacity_counts_only_growth_mutation_prs():
    text = WORKFLOW.read_text(encoding="utf-8")
    lane_query = text.split('OPEN_PRS_JSON="', 1)[1].split('OPEN_COUNT="', 1)[0]

    # These are the branch families emitted by candidate-promotion-pr.yml for
    # catalog growth. Discovery ledgers, observation ledgers, quarantine, and
    # unrelated agent work must not consume catalog-growth lane capacity.
    assert 'startswith("agent-candidate-bound-")' in lane_query
    assert 'startswith("agent-candidate-promotion-")' in lane_query
    assert 'startswith("agent-")' not in lane_query


def test_global_bot_budget_counts_only_bot_owned_agent_prs():
    text = WORKFLOW.read_text(encoding="utf-8")
    budget_block = text.split("# Global bot PR budgets", 1)[1].split("# Global hold", 1)[0]

    # Preserve the global bot PR limits, but do not charge maintainer/human PRs
    # against them. Bot-created operational branches use the agent-* convention.
    assert budget_block.count('startswith("agent-")') == 2
    assert budget_block.count("--json number,headRefName --limit 100") == 2
