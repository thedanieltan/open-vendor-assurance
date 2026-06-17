"""WP-OPENVA-ZERO-INSTALL-DISTRIBUTION-01 PR2: discovery -> strict-growth promotion bridge gate.

Pure decision function for the ``catalog-growth-promotion-bridge`` workflow. After a
successful scheduled ``catalog-growth-discovery`` run on ``main``, the bridge reads the
strict-growth promotion plan that run produced and decides whether to dispatch the
**existing** mutation workflow (``candidate-promotion-pr.yml``) in
``strict-growth-latest`` mode.

It never writes catalog state, opens a PR, evaluates candidate eligibility, or
implements a second mutation path. The discovery plan is a dispatch **signal** only:
the dispatched promotion workflow regenerates and re-validates current evidence and
remains the sole catalog write authority. This module performs only the bounded
"is it worth dispatching, and is it safe to dispatch right now" gate:

* no-op unless the plan is a ``strict_growth_promotion_plan`` with > 0 eligible actions;
* no-op while the global hold (``openva-bot-paused``) is active;
* no-op when a catalog-growth PR is already open (one open growth PR at a time).

The authoritative queue, cadence, stale-evidence, source-preflight, and strict-growth
automerge gates remain inside ``candidate-promotion-pr.yml`` and ``agent-automerge.yml``;
this gate only avoids pointless or unsafe dispatch. It is a pure decision function; the
workflow performs the side effects.

Operational metadata only. Not legal, compliance, procurement, security, KYC, AML,
audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

STRICT_GROWTH_PLAN_TYPE = "strict_growth_promotion_plan"
DISPATCH_MODE = "strict-growth-latest"
MUTATION_WORKFLOW = "candidate-promotion-pr.yml"
DEFAULT_MAX_OPEN_GROWTH_PRS = 1

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


def decide_dispatch(
    plan: dict[str, Any],
    *,
    hold_active: bool,
    open_growth_pr_count: int,
    max_open_growth_prs: int = DEFAULT_MAX_OPEN_GROWTH_PRS,
    source_run_id: str | None = None,
    plan_digest: str | None = None,
) -> dict[str, Any]:
    """Decide whether to dispatch the existing strict-growth promotion workflow.

    Returns a deterministic decision record. ``dispatch`` is True only when the plan is
    a strict-growth promotion plan carrying eligible promotion actions and no hold /
    open-growth-PR blocks the handoff. The no-op reasons are checked in a fixed order so
    the decision is reproducible from its inputs.
    """
    report_type = plan.get("report_type")
    summary = plan.get("summary") or {}
    action_count = _coerce_int(summary.get("action_count")) or 0
    cap = _coerce_int(summary.get("max_promotion_actions_per_pr"))

    if report_type != STRICT_GROWTH_PLAN_TYPE:
        return _result(False, "invalid_plan", 0, None, source_run_id, plan_digest)
    if action_count <= 0:
        return _result(False, "no_eligible_actions", action_count, cap, source_run_id, plan_digest)
    if hold_active:
        return _result(False, "global_hold_active", action_count, cap, source_run_id, plan_digest)
    if open_growth_pr_count >= max_open_growth_prs:
        return _result(False, "open_growth_pr_exists", action_count, cap, source_run_id, plan_digest)

    return _result(True, "promotion_dispatch_authorised", action_count, cap, source_run_id, plan_digest)


def _result(
    dispatch: bool,
    reason: str,
    action_count: int,
    cap: int | None,
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
        "source_discovery_run_id": source_run_id,
        "plan_digest": plan_digest,
        "evidence_is_dispatch_signal_only": True,
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-promotion-bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    decide = subparsers.add_parser("decide", help="Decide whether to dispatch the strict-growth promotion workflow.")
    decide.add_argument("--plan", type=Path, required=True, help="strict-growth-promotion-plan.json from the discovery run")
    decide.add_argument("--hold-active", default="false", help="Global hold (openva-bot-paused) active: true/false")
    decide.add_argument("--open-growth-pr-count", type=int, default=0)
    decide.add_argument("--max-open-growth-prs", type=int, default=DEFAULT_MAX_OPEN_GROWTH_PRS)
    decide.add_argument("--source-run-id")
    decide.add_argument("--plan-digest")
    decide.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.command == "decide":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        result = decide_dispatch(
            plan,
            hold_active=parse_bool(args.hold_active),
            open_growth_pr_count=args.open_growth_pr_count,
            max_open_growth_prs=args.max_open_growth_prs,
            source_run_id=args.source_run_id,
            plan_digest=args.plan_digest,
        )
        text = json.dumps(result, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
