"""Unit tests for the discovery -> strict-growth promotion bridge gates.

Two fail-closed gates are proven here:

* ``evaluate_run_eligibility`` (the authority boundary): only a successful
  ``catalog-growth-discovery`` run on ``main`` is eligible, and on the automatic
  ``workflow_run`` path the upstream discovery run must itself have been ``schedule``
  triggered -- a manually dispatched discovery run must not cause automatic promotion.
  The explicit ``workflow_dispatch`` recovery path is an intentional operator action.
* ``decide_dispatch`` (the runtime gate): dispatch only on a strict-growth plan with
  eligible actions, with deterministic ordering invalid plan -> zero actions ->
  global hold -> active promotion run -> open growth PR -> authorised dispatch.

The dispatched target is always the single existing mutation workflow in
strict-growth-latest mode; this module never opens a PR or writes catalog state.
"""

from __future__ import annotations

import json

from tools.openva.discovery_promotion_bridge import (
    DISPATCH_MODE,
    MUTATION_WORKFLOW,
    decide_dispatch,
    evaluate_run_eligibility,
    main,
    parse_bool,
)


def _plan(action_count: int = 3, cap: int | None = 10, report_type: str = "strict_growth_promotion_plan") -> dict:
    summary: dict = {"action_count": action_count}
    if cap is not None:
        summary["max_promotion_actions_per_pr"] = cap
    return {"report_type": report_type, "summary": summary}


def _eligibility(**overrides):
    base = dict(
        bridge_event="workflow_run",
        upstream_event="schedule",
        workflow_name="catalog-growth-discovery",
        conclusion="success",
        head_branch="main",
    )
    base.update(overrides)
    return evaluate_run_eligibility(**base)


# ---------------------------------------------------------------------------
# Finding 1: run eligibility / upstream event-type authority boundary
# ---------------------------------------------------------------------------


def test_scheduled_success_main_is_eligible_for_bridge_evaluation():
    decision = _eligibility(bridge_event="workflow_run", upstream_event="schedule")

    assert decision["eligible"] is True
    assert decision["reason"] == "scheduled_discovery_eligible"


def test_manual_discovery_through_workflow_run_does_not_auto_dispatch():
    # A manually dispatched discovery run completes and triggers the bridge via
    # workflow_run -> must NOT be eligible for automatic promotion.
    decision = _eligibility(bridge_event="workflow_run", upstream_event="workflow_dispatch")

    assert decision["eligible"] is False
    assert decision["reason"] == "upstream_not_scheduled"


def test_failed_discovery_is_not_eligible():
    decision = _eligibility(conclusion="failure")

    assert decision["eligible"] is False
    assert decision["reason"] == "discovery_not_successful"


def test_cancelled_discovery_is_not_eligible():
    decision = _eligibility(conclusion="cancelled")

    assert decision["eligible"] is False
    assert decision["reason"] == "discovery_not_successful"


def test_non_main_discovery_is_not_eligible():
    decision = _eligibility(head_branch="feature/x")

    assert decision["eligible"] is False
    assert decision["reason"] == "discovery_not_main"


def test_foreign_workflow_is_not_eligible():
    decision = _eligibility(workflow_name="some-other-workflow")

    assert decision["eligible"] is False
    assert decision["reason"] == "foreign_workflow"


def test_explicit_bridge_dispatch_with_valid_run_is_allowed():
    # Operator recovery path: an exact, successful, main discovery run is allowed
    # regardless of how the discovery run itself was triggered.
    for upstream in ("schedule", "workflow_dispatch"):
        decision = _eligibility(bridge_event="workflow_dispatch", upstream_event=upstream)
        assert decision["eligible"] is True, upstream
        assert decision["reason"] == "manual_bridge_dispatch"


def test_manual_bridge_dispatch_still_validates_conclusion_and_branch():
    assert _eligibility(bridge_event="workflow_dispatch", conclusion="failure")["eligible"] is False
    assert _eligibility(bridge_event="workflow_dispatch", head_branch="feature/x")["eligible"] is False


def test_unknown_bridge_event_fails_closed():
    decision = _eligibility(bridge_event="push")

    assert decision["eligible"] is False
    assert decision["reason"] == "unsupported_bridge_event"


def test_eligibility_is_deterministic():
    assert _eligibility() == _eligibility()


# ---------------------------------------------------------------------------
# Finding 2: dispatch decision incl. active promotion-run dedup
# ---------------------------------------------------------------------------


def test_dispatch_when_eligible_actions_and_no_blocks():
    decision = decide_dispatch(_plan(action_count=2, cap=10), hold_active=False, open_growth_pr_count=0)

    assert decision["dispatch"] is True
    assert decision["reason"] == "promotion_dispatch_authorised"
    assert decision["mode"] == DISPATCH_MODE == "strict-growth-latest"
    assert decision["mutation_workflow"] == MUTATION_WORKFLOW == "candidate-promotion-pr.yml"
    assert decision["action_count"] == 2
    assert decision["max_promotion_actions_per_pr"] == 10
    assert decision["active_promotion_run_count"] == 0
    assert decision["evidence_is_dispatch_signal_only"] is True
    assert decision["not_advice"] is True


def test_no_dispatch_on_zero_action_plan():
    decision = decide_dispatch(_plan(action_count=0), hold_active=False, open_growth_pr_count=0)

    assert decision["dispatch"] is False
    assert decision["reason"] == "no_eligible_actions"


def test_no_dispatch_on_non_strict_growth_plan():
    decision = decide_dispatch(_plan(report_type="promotion_plan", action_count=5), hold_active=False, open_growth_pr_count=0)

    assert decision["dispatch"] is False
    assert decision["reason"] == "invalid_plan"
    assert decision["action_count"] == 0


def test_no_dispatch_while_global_hold_active():
    decision = decide_dispatch(_plan(action_count=4), hold_active=True, open_growth_pr_count=0)

    assert decision["dispatch"] is False
    assert decision["reason"] == "global_hold_active"


def test_queued_promotion_run_blocks_dispatch():
    decision = decide_dispatch(
        _plan(action_count=4), hold_active=False, open_growth_pr_count=0, active_promotion_run_count=1
    )

    assert decision["dispatch"] is False
    assert decision["reason"] == "promotion_workflow_active"
    assert decision["active_promotion_run_count"] == 1


def test_in_progress_promotion_run_blocks_dispatch():
    # The workflow counts queued + in_progress runs into one count; any active run blocks.
    decision = decide_dispatch(
        _plan(action_count=4), hold_active=False, open_growth_pr_count=0, active_promotion_run_count=2
    )

    assert decision["dispatch"] is False
    assert decision["reason"] == "promotion_workflow_active"


def test_completed_promotion_runs_do_not_block():
    # Completed runs are not counted (the workflow only counts queued/in_progress), so a
    # zero active count lets an otherwise-eligible plan dispatch.
    decision = decide_dispatch(
        _plan(action_count=4), hold_active=False, open_growth_pr_count=0, active_promotion_run_count=0
    )

    assert decision["dispatch"] is True
    assert decision["reason"] == "promotion_dispatch_authorised"


def test_no_dispatch_when_growth_pr_already_open():
    decision = decide_dispatch(_plan(action_count=4), hold_active=False, open_growth_pr_count=1)

    assert decision["dispatch"] is False
    assert decision["reason"] == "open_growth_pr_exists"


def test_active_run_plus_open_pr_yields_deterministic_active_reason():
    # Both block; deterministic ordering puts active promotion run before open PR.
    decision = decide_dispatch(
        _plan(action_count=4), hold_active=False, open_growth_pr_count=1, active_promotion_run_count=1
    )

    assert decision["dispatch"] is False
    assert decision["reason"] == "promotion_workflow_active"


def test_full_deterministic_reason_ordering():
    # hold > active > open-PR, all with eligible actions present.
    assert (
        decide_dispatch(_plan(action_count=4), hold_active=True, open_growth_pr_count=1, active_promotion_run_count=1)[
            "reason"
        ]
        == "global_hold_active"
    )
    assert (
        decide_dispatch(_plan(action_count=4), hold_active=False, open_growth_pr_count=1, active_promotion_run_count=1)[
            "reason"
        ]
        == "promotion_workflow_active"
    )
    assert (
        decide_dispatch(_plan(action_count=4), hold_active=False, open_growth_pr_count=1, active_promotion_run_count=0)[
            "reason"
        ]
        == "open_growth_pr_exists"
    )
    # zero actions outranks every runtime-state block.
    assert (
        decide_dispatch(_plan(action_count=0), hold_active=True, open_growth_pr_count=1, active_promotion_run_count=1)[
            "reason"
        ]
        == "no_eligible_actions"
    )


def test_cap_passes_through_from_plan_summary():
    decision = decide_dispatch(_plan(action_count=1, cap=7), hold_active=False, open_growth_pr_count=0)

    assert decision["max_promotion_actions_per_pr"] == 7


def test_missing_cap_is_none_not_a_guessed_default():
    decision = decide_dispatch(_plan(action_count=1, cap=None), hold_active=False, open_growth_pr_count=0)

    assert decision["dispatch"] is True
    assert decision["max_promotion_actions_per_pr"] is None


def test_decision_is_deterministic():
    plan = _plan(action_count=2, cap=10)
    assert decide_dispatch(plan, hold_active=False, open_growth_pr_count=0) == decide_dispatch(
        plan, hold_active=False, open_growth_pr_count=0
    )


def test_records_source_run_provenance():
    decision = decide_dispatch(
        _plan(action_count=2), hold_active=False, open_growth_pr_count=0, source_run_id="123", plan_digest="sha256:abc"
    )

    assert decision["source_discovery_run_id"] == "123"
    assert decision["plan_digest"] == "sha256:abc"


def test_parse_bool_accepts_workflow_truthy_tokens():
    assert parse_bool("true") and parse_bool("TRUE") and parse_bool("1") and parse_bool("yes")
    assert not parse_bool("false") and not parse_bool("") and not parse_bool("0")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_eligibility_writes_json(tmp_path):
    out = tmp_path / "eligibility.json"
    result = main(
        [
            "eligibility",
            "--bridge-event",
            "workflow_run",
            "--upstream-event",
            "schedule",
            "--workflow-name",
            "catalog-growth-discovery",
            "--conclusion",
            "success",
            "--head-branch",
            "main",
            "--output",
            str(out),
        ]
    )

    assert result == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["eligible"] is True
    assert payload["reason"] == "scheduled_discovery_eligible"


def test_cli_eligibility_blocks_manual_upstream_on_workflow_run(tmp_path):
    out = tmp_path / "eligibility.json"
    main(
        [
            "eligibility",
            "--bridge-event",
            "workflow_run",
            "--upstream-event",
            "workflow_dispatch",
            "--workflow-name",
            "catalog-growth-discovery",
            "--conclusion",
            "success",
            "--head-branch",
            "main",
            "--output",
            str(out),
        ]
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["eligible"] is False
    assert payload["reason"] == "upstream_not_scheduled"


def test_cli_decide_writes_decision_json(tmp_path):
    plan_path = tmp_path / "strict-growth-promotion-plan.json"
    plan_path.write_text(json.dumps(_plan(action_count=2, cap=5)), encoding="utf-8")
    out = tmp_path / "decision.json"

    result = main(
        [
            "decide",
            "--plan",
            str(plan_path),
            "--hold-active",
            "false",
            "--open-growth-pr-count",
            "0",
            "--active-promotion-run-count",
            "0",
            "--source-run-id",
            "999",
            "--output",
            str(out),
        ]
    )

    assert result == 0
    decision = json.loads(out.read_text(encoding="utf-8"))
    assert decision["dispatch"] is True
    assert decision["mode"] == "strict-growth-latest"
    assert decision["source_discovery_run_id"] == "999"


def test_cli_decide_blocks_on_active_promotion_run(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(action_count=3)), encoding="utf-8")
    out = tmp_path / "decision.json"

    main(
        [
            "decide",
            "--plan",
            str(plan_path),
            "--active-promotion-run-count",
            "1",
            "--output",
            str(out),
        ]
    )

    decision = json.loads(out.read_text(encoding="utf-8"))
    assert decision["dispatch"] is False
    assert decision["reason"] == "promotion_workflow_active"
