"""Unit tests for the discovery -> strict-growth promotion bridge decision gate.

These prove the bounded no-op semantics required by the bridge: dispatch only on a
strict-growth plan with eligible actions, and only when no hold / open growth PR
blocks the handoff. The dispatched target is always the single existing mutation
workflow in strict-growth-latest mode; this module never opens a PR or writes catalog
state itself.
"""

from __future__ import annotations

import json

from tools.openva.discovery_promotion_bridge import (
    DISPATCH_MODE,
    MUTATION_WORKFLOW,
    decide_dispatch,
    main,
    parse_bool,
)


def _plan(action_count: int = 3, cap: int | None = 10, report_type: str = "strict_growth_promotion_plan") -> dict:
    summary: dict = {"action_count": action_count}
    if cap is not None:
        summary["max_promotion_actions_per_pr"] = cap
    return {"report_type": report_type, "summary": summary}


def test_dispatch_when_eligible_actions_and_no_blocks():
    decision = decide_dispatch(_plan(action_count=2, cap=10), hold_active=False, open_growth_pr_count=0)

    assert decision["dispatch"] is True
    assert decision["reason"] == "promotion_dispatch_authorised"
    assert decision["mode"] == DISPATCH_MODE == "strict-growth-latest"
    assert decision["mutation_workflow"] == MUTATION_WORKFLOW == "candidate-promotion-pr.yml"
    assert decision["action_count"] == 2
    assert decision["max_promotion_actions_per_pr"] == 10
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
    # Action count is not trusted from a foreign plan shape.
    assert decision["action_count"] == 0


def test_no_dispatch_while_global_hold_active():
    decision = decide_dispatch(_plan(action_count=4), hold_active=True, open_growth_pr_count=0)

    assert decision["dispatch"] is False
    assert decision["reason"] == "global_hold_active"


def test_no_dispatch_when_growth_pr_already_open():
    decision = decide_dispatch(_plan(action_count=4), hold_active=False, open_growth_pr_count=1)

    assert decision["dispatch"] is False
    assert decision["reason"] == "open_growth_pr_exists"


def test_hold_takes_precedence_over_open_pr_when_both_block():
    # Deterministic ordering: hold is evaluated before the open-PR check.
    decision = decide_dispatch(_plan(action_count=4), hold_active=True, open_growth_pr_count=5)

    assert decision["reason"] == "global_hold_active"


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


def test_cli_writes_decision_json(tmp_path):
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


def test_cli_no_op_when_hold_active(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(action_count=3)), encoding="utf-8")
    out = tmp_path / "decision.json"

    main(["decide", "--plan", str(plan_path), "--hold-active", "true", "--output", str(out)])

    assert json.loads(out.read_text(encoding="utf-8"))["dispatch"] is False
