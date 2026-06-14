"""WP40A scheduled autonomous machine-provisional growth controller (Issue 3).

Turns machine-provisional growth from a manually-dispatched option into a
continuously-operating lane. On each scheduled cycle the controller:

1. evaluates the live queue state (with live-state enforcement on, so fallback
   state can never authorise a write);
2. honours holds, cooldowns, and the rate-limit reserve via the same queue
   evaluation and the global work-priority reserved capacity;
3. yields to pending integrity/maintenance work (rollback / quarantine /
   repair) before growth;
4. selects exactly **one** eligible candidate (deterministically, oldest
   first);
5. authorises generating exactly one new machine_provisional vendor.

It never authorises more than one new machine-provisional vendor per cycle and
never authorises a second catalog-mutation architecture: on "proceed" it hands
the single selected candidate to the existing machine-provisional generation +
decision + not_before + automerge machinery.

This module is a pure decision function; the workflow performs the side effects.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva import bot_queue, work_priority

GROWTH_LANE = "catalog_growth_promotion"
GROWTH_WORK_CLASS = "machine_provisional_growth"
MAX_VENDORS_PER_CYCLE = 1


def select_one_candidate(eligible_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministically select exactly one eligible candidate (oldest first)."""
    usable = [c for c in eligible_candidates if c.get("eligibility_state") == "eligible"]
    if not usable:
        return None
    return sorted(usable, key=lambda c: (str(c.get("created_at") or ""), str(c.get("candidate_id") or "")))[0]


def decide_cycle(
    queue_state: dict[str, Any],
    eligible_candidates: list[dict[str, Any]],
    *,
    pending_integrity_work: bool = False,
    total_pr_budget: int = 3,
    open_prs_total: int = 0,
    now: datetime | None = None,
    policies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide whether to start one growth cycle and which candidate to run."""
    now = now or datetime.now(UTC).replace(microsecond=0)

    queue_decision = bot_queue.evaluate(
        GROWTH_LANE, queue_state, now=now, policies=policies, enforce_live_state=True
    )
    if queue_decision["decision"] != "allow":
        return _result(False, f"queue_{queue_decision['decision']}", None, queue_decision)

    capacity = work_priority.capacity_decision(
        GROWTH_WORK_CLASS,
        total_pr_budget=total_pr_budget,
        open_prs_total=open_prs_total,
        pending_integrity_work=pending_integrity_work,
    )
    if capacity["decision"] != "allow":
        return _result(False, capacity["reason"], None, queue_decision, capacity)

    candidate = select_one_candidate(eligible_candidates)
    if candidate is None:
        return _result(False, "no_eligible_candidate", None, queue_decision, capacity)

    return _result(True, "growth_cycle_authorised", candidate, queue_decision, capacity)


def _result(
    proceed: bool,
    reason: str,
    candidate: dict[str, Any] | None,
    queue_decision: dict[str, Any],
    capacity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "report_type": "autonomous_growth_cycle_decision",
        "proceed": proceed,
        "reason": reason,
        "max_vendors_this_cycle": MAX_VENDORS_PER_CYCLE if proceed else 0,
        "selected_candidate_id": (candidate or {}).get("candidate_id"),
        "queue_decision": queue_decision["decision"],
        "queue_reasons": queue_decision["reasons"],
        "state_authoritative": queue_decision.get("state_authoritative"),
        "capacity_decision": (capacity or {}).get("decision"),
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-autonomous-growth-controller")
    parser.add_argument("--queue-state", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True, help="JSON array of candidate records")
    parser.add_argument("--pending-integrity-work", action="store_true")
    parser.add_argument("--total-pr-budget", type=int, default=3)
    parser.add_argument("--open-prs-total", type=int, default=0)
    parser.add_argument("--now")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    queue_state = json.loads(args.queue_state.read_text(encoding="utf-8"))
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    now = bot_queue.parse_time(args.now) if args.now else None
    result = decide_cycle(
        queue_state,
        candidates,
        pending_integrity_work=args.pending_integrity_work,
        total_pr_budget=args.total_pr_budget,
        open_prs_total=args.open_prs_total,
        now=now,
    )
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
