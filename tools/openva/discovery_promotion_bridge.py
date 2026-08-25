"""WP-OPENVA-ZERO-INSTALL-DISTRIBUTION-01 PR2: discovery -> strict-growth promotion bridge gate.

Pure decision functions for the ``catalog-growth-promotion-bridge`` workflow. After a
successful scheduled ``catalog-growth-discovery`` run on ``main``, the bridge reads the
strict-growth promotion plan that run produced and decides whether to dispatch the
**existing** mutation workflow (``candidate-promotion-pr.yml``) in
``strict-growth-artifact`` mode.

It never writes catalog state, opens a PR, evaluates candidate eligibility, or
implements a second mutation path. The discovery plan is a dispatch **signal** rather than merge authority. The
dispatched promotion workflow binds the exact discovery artifact, reclassifies its
captured source evidence against current main, rebuilds the bounded shortlist, and
remains the sole catalog write authority.

Two fail-closed gates live here so they are unit-testable independently of GitHub:

``evaluate_run_eligibility`` enforces the authority boundary of the triggering run:
* the run must be a successful ``catalog-growth-discovery`` run on ``main``;
* on the automatic ``workflow_run`` path, the *upstream* discovery run's triggering
  event must be exactly ``schedule`` -- a manually dispatched discovery run must not
  cause automatic promotion;
* the explicit ``workflow_dispatch`` recovery path is an intentional operator action
  that may consume any exact, successful, main discovery run.

``decide_dispatch`` enforces the runtime safety gate against a strict-growth plan and
live repository state, in a fixed deterministic order:
``invalid plan`` -> ``zero eligible actions`` -> ``global hold`` ->
``active promotion workflow`` -> ``open catalog-growth PR`` -> authorised dispatch.

The authoritative queue, cadence, stale-evidence, source-preflight, and strict-growth
automerge gates remain inside ``candidate-promotion-pr.yml`` and ``agent-automerge.yml``;
these gates only avoid pointless, unauthorised, or duplicate dispatch. The workflow
performs the side effects.

Operational metadata only. Not legal, compliance, procurement, security, KYC, AML,
audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

STRICT_GROWTH_PLAN_TYPE = "strict_growth_promotion_plan"
DISPATCH_MODE = "strict-growth-artifact"
MUTATION_WORKFLOW = "candidate-promotion-pr.yml"
EXPECTED_DISCOVERY_WORKFLOW = "catalog-growth-discovery"
DEFAULT_MAX_OPEN_GROWTH_PRS = 1

SCHEDULE_EVENT = "schedule"
WORKFLOW_RUN_BRIDGE_EVENT = "workflow_run"
WORKFLOW_DISPATCH_BRIDGE_EVENT = "workflow_dispatch"

TRUE_TOKENS = {"1", "true", "yes", "on"}


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in TRUE_TOKENS


def evaluate_run_eligibility(
    *,
    bridge_event: str,
    upstream_event: str,
    workflow_name: str,
    conclusion: str,
    head_branch: str,
    expected_workflow: str = EXPECTED_DISCOVERY_WORKFLOW,
) -> dict[str, Any]:
    """Decide whether the triggering discovery run is eligible for bridge evaluation.

    Fail-closed authority boundary. ``bridge_event`` is the bridge workflow's own event
    (``workflow_run`` for the automatic path, ``workflow_dispatch`` for the explicit
    operator recovery path). ``upstream_event`` is the triggering event of the
    discovery run itself, read from authoritative run metadata. All checks default to
    ineligible; only an explicitly allowed combination returns ``eligible: True``.
    """
    eligible = False
    if workflow_name != expected_workflow:
        reason = "foreign_workflow"
    elif conclusion != "success":
        reason = "discovery_not_successful"
    elif head_branch != "main":
        reason = "discovery_not_main"
    elif bridge_event == WORKFLOW_RUN_BRIDGE_EVENT:
        # Automatic path: only a scheduled discovery run may auto-promote. A manually
        # dispatched discovery run that completes must not trigger automatic promotion.
        if upstream_event == SCHEDULE_EVENT:
            eligible = True
            reason = "scheduled_discovery_eligible"
        else:
            reason = "upstream_not_scheduled"
    elif bridge_event == WORKFLOW_DISPATCH_BRIDGE_EVENT:
        # Explicit operator recovery path: an intentional action against an exact,
        # successful, main discovery run, regardless of how that run was triggered.
        eligible = True
        reason = "manual_bridge_dispatch"
    else:
        reason = "unsupported_bridge_event"

    return {
        "schema_version": "0.1.0",
        "report_type": "catalog_growth_promotion_bridge_eligibility",
        "eligible": eligible,
        "reason": reason,
        "bridge_event": bridge_event,
        "upstream_event": upstream_event,
        "workflow_name": workflow_name,
        "conclusion": conclusion,
        "head_branch": head_branch,
        "not_advice": True,
    }


def decide_dispatch(
    plan: dict[str, Any],
    *,
    hold_active: bool,
    open_growth_pr_count: int,
    active_promotion_run_count: int = 0,
    max_open_growth_prs: int = DEFAULT_MAX_OPEN_GROWTH_PRS,
    source_run_id: str | None = None,
    plan_digest: str | None = None,
) -> dict[str, Any]:
    """Decide whether to dispatch the existing strict-growth promotion workflow.

    Returns a deterministic decision record. ``dispatch`` is True only when the plan is
    a strict-growth promotion plan carrying eligible promotion actions and no hold, no
    queued/in-progress promotion run, and no already-open growth PR blocks the handoff.
    The no-op reasons are checked in a fixed order so the decision is reproducible:
    invalid plan -> zero eligible actions -> global hold -> active promotion workflow ->
    open catalog-growth PR -> authorised dispatch.
    """
    report_type = plan.get("report_type")
    summary = plan.get("summary") or {}
    action_count = _coerce_int(summary.get("action_count")) or 0
    cap = _coerce_int(summary.get("max_promotion_actions_per_pr"))

    def result(dispatch: bool, reason: str, counted_actions: int, counted_cap: int | None) -> dict[str, Any]:
        return _result(
            dispatch,
            reason,
            counted_actions,
            counted_cap,
            active_promotion_run_count,
            source_run_id,
            plan_digest,
        )

    if report_type != STRICT_GROWTH_PLAN_TYPE:
        return result(False, "invalid_plan", 0, None)
    if action_count <= 0:
        return result(False, "no_eligible_actions", action_count, cap)
    if hold_active:
        return result(False, "global_hold_active", action_count, cap)
    if active_promotion_run_count > 0:
        return result(False, "promotion_workflow_active", action_count, cap)
    if open_growth_pr_count >= max_open_growth_prs:
        return result(False, "open_growth_pr_exists", action_count, cap)

    return result(True, "promotion_dispatch_authorised", action_count, cap)


def _result(
    dispatch: bool,
    reason: str,
    action_count: int,
    cap: int | None,
    active_promotion_run_count: int,
    source_run_id: str | None,
    plan_digest: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "report_type": "catalog_growth_promotion_bridge_decision",
        "dispatch": dispatch,
        "reason": reason,
        "mode": DISPATCH_MODE,
        "mutation_workflow": MUTATION_WORKFLOW,
        "action_count": action_count,
        "max_promotion_actions_per_pr": cap,
        "active_promotion_run_count": active_promotion_run_count,
        "source_discovery_run_id": source_run_id,
        "plan_digest": plan_digest,
        "evidence_is_dispatch_signal_only": True,
        "not_advice": True,
    }


def _emit(result: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(result, indent=2, sort_keys=True)
    if output:
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-promotion-bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    eligibility = subparsers.add_parser(
        "eligibility", help="Decide whether the triggering discovery run is eligible for bridge evaluation."
    )
    eligibility.add_argument("--bridge-event", required=True, help="The bridge workflow event: workflow_run or workflow_dispatch")
    eligibility.add_argument("--upstream-event", default="", help="The triggering event of the discovery run (from gh run view --json event)")
    eligibility.add_argument("--workflow-name", default="")
    eligibility.add_argument("--conclusion", default="")
    eligibility.add_argument("--head-branch", default="")
    eligibility.add_argument("--expected-workflow", default=EXPECTED_DISCOVERY_WORKFLOW)
    eligibility.add_argument("--output", type=Path)

    decide = subparsers.add_parser("decide", help="Decide whether to dispatch the strict-growth promotion workflow.")
    decide.add_argument("--plan", type=Path, required=True, help="strict-growth-promotion-plan.json from the discovery run")
    decide.add_argument("--hold-active", default="false", help="Global hold (openva-bot-paused) active: true/false")
    decide.add_argument("--open-growth-pr-count", type=int, default=0)
    decide.add_argument("--active-promotion-run-count", type=int, default=0, help="Count of queued/in-progress candidate-promotion-pr runs")
    decide.add_argument("--max-open-growth-prs", type=int, default=DEFAULT_MAX_OPEN_GROWTH_PRS)
    decide.add_argument("--source-run-id")
    decide.add_argument("--plan-digest")
    decide.add_argument("--output", type=Path)

    args = parser.parse_args(argv)

    if args.command == "eligibility":
        result = evaluate_run_eligibility(
            bridge_event=args.bridge_event,
            upstream_event=args.upstream_event,
            workflow_name=args.workflow_name,
            conclusion=args.conclusion,
            head_branch=args.head_branch,
            expected_workflow=args.expected_workflow,
        )
        _emit(result, args.output)
        return 0

    if args.command == "decide":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        result = decide_dispatch(
            plan,
            hold_active=parse_bool(args.hold_active),
            open_growth_pr_count=args.open_growth_pr_count,
            active_promotion_run_count=args.active_promotion_run_count,
            max_open_growth_prs=args.max_open_growth_prs,
            source_run_id=args.source_run_id,
            plan_digest=args.plan_digest,
        )
        _emit(result, args.output)
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
