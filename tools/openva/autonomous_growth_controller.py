"""WP40A scheduled autonomous machine-provisional growth controller (Issue 3).

Turns machine-provisional growth from a manually-dispatched option into a
continuously-operating lane. On each scheduled cycle the controller:

1. evaluates the live queue state (with live-state enforcement on, so fallback
   state can never authorise a write);
2. honours holds, cooldowns, and the rate-limit reserve via the same queue
   evaluation and the global work-priority reserved capacity;
3. yields to pending integrity/maintenance work (rollback / quarantine /
   repair) before growth;
4. selects exactly **one** eligible candidate (demand-informed, deterministic);
5. authorises generating exactly one new machine_provisional vendor.

It never authorises more than one new machine-provisional vendor per cycle and
never authorises a second catalog-mutation architecture: on "proceed" it hands
the single selected candidate to the existing machine-provisional generation +
decision + not_before + automerge machinery.

Demand signals only prioritise already-eligible candidates. Demand never makes
an ineligible, ambiguous, gated, unsafe, or insufficient-evidence candidate
eligible and never bypasses candidate binding.

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

from tools.openva import bot_queue, vendor_resolution, work_priority

GROWTH_LANE = "catalog_growth_promotion"
GROWTH_WORK_CLASS = "machine_provisional_growth"
MAX_VENDORS_PER_CYCLE = 1

DEMAND_SIGNAL_WEIGHTS = {
    "repeated_user_agent_misses": 100,
    "frequently_requested_vendor": 80,
    "frequently_missing_source_type": 60,
    "repeated_ambiguous_identity": 50,
    "rediscovered_candidate_url": 40,
    "high_use_broken_gated_unavailable_url": 30,
}

DEMAND_SIGNAL_ALIASES = {
    "repeated_user_misses": "repeated_user_agent_misses",
    "repeated_agent_misses": "repeated_user_agent_misses",
    "frequent_vendor_request": "frequently_requested_vendor",
    "missing_source_type": "frequently_missing_source_type",
    "ambiguous_identity": "repeated_ambiguous_identity",
    "rediscovered_candidate": "rediscovered_candidate_url",
    "broken_gated_unavailable_url": "high_use_broken_gated_unavailable_url",
}


def normalise_demand_signal(signal: str) -> str:
    key = str(signal or "").strip().lower().replace("-", "_")
    return DEMAND_SIGNAL_ALIASES.get(key, key)


def demand_signal_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    """Summarise Phase 9 resolver-usefulness signals on a candidate.

    Signals may come from future resolver/API/agent-workspace telemetry in either
    ``demand_signals`` or ``resolver_demand_signals``. This function is tolerant:
    unknown signals are preserved for audit but score zero. It does not evaluate
    evidence and cannot make a candidate eligible.
    """
    raw = candidate.get("demand_signals") or candidate.get("resolver_demand_signals") or []
    if isinstance(raw, dict):
        raw_signals = [key for key, value in raw.items() if value]
    else:
        raw_signals = list(raw or [])
    signals = tuple(dict.fromkeys(normalise_demand_signal(signal) for signal in raw_signals if signal))
    priority = sum(DEMAND_SIGNAL_WEIGHTS.get(signal, 0) for signal in signals)
    return {
        "priority": priority,
        "signals": signals,
        "known_signals": tuple(signal for signal in signals if signal in DEMAND_SIGNAL_WEIGHTS),
        "unknown_signals": tuple(signal for signal in signals if signal not in DEMAND_SIGNAL_WEIGHTS),
        "not_advice": True,
    }


def demand_priority(candidate: dict[str, Any]) -> int:
    return int(demand_signal_summary(candidate)["priority"])


def select_one_candidate(eligible_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministically select exactly one eligible candidate.

    Phase 9 changes the ordering from pure age to resolver-usefulness priority,
    but the input set is still filtered to ``eligibility_state == 'eligible'``.
    Demand signals therefore prioritise background cache reuse only; they do not
    authorise a candidate, create a vendor, approve a source, or bypass binding.
    Ties remain oldest first for stable behaviour.
    """
    usable = [c for c in eligible_candidates if c.get("eligibility_state") == "eligible"]
    if not usable:
        return None
    return sorted(
        usable,
        key=lambda c: (-demand_priority(c), str(c.get("created_at") or ""), str(c.get("candidate_id") or "")),
    )[0]


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

    # WP-OPENVA-CANDIDATE-ACTIVATION-01: bind the selected candidate before it
    # may proceed. Recompute eligibility and identity from the persisted record
    # via the one canonical evaluator (never trusting the stored
    # eligibility_state) and carry the candidate_id / candidate_path /
    # content_digest / origin / selected_vendor through to the downstream
    # promotion mutation. Any mismatch fails this cycle closed; the identity is
    # never re-derived later from a separate queue.
    binding = vendor_resolution.evaluate_persisted_candidate(
        candidate, candidate_path=candidate.get("candidate_path")
    )
    if not binding.eligible:
        return _result(
            False,
            "candidate_eligibility_mismatch",
            candidate,
            queue_decision,
            capacity,
            mismatch_reasons=binding.reasons,
        )

    return _result(
        True,
        "growth_cycle_authorised",
        candidate,
        queue_decision,
        capacity,
        binding=binding.binding(),
    )


def _result(
    proceed: bool,
    reason: str,
    candidate: dict[str, Any] | None,
    queue_decision: dict[str, Any],
    capacity: dict[str, Any] | None = None,
    *,
    binding: dict[str, Any] | None = None,
    mismatch_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    demand = demand_signal_summary(candidate or {})
    result = {
        "schema_version": "0.1.0",
        "report_type": "autonomous_growth_cycle_decision",
        "proceed": proceed,
        "reason": reason,
        "max_vendors_this_cycle": MAX_VENDORS_PER_CYCLE if proceed else 0,
        "selected_candidate_id": (candidate or {}).get("candidate_id"),
        # Phase 9: demand signals explain ordering only. They are not an
        # authorisation surface and never replace eligibility, queue, capacity,
        # or candidate-binding gates.
        "selected_candidate_demand_priority": demand["priority"],
        "selected_candidate_demand_signals": list(demand["known_signals"]),
        # The bound candidate identity carried to the candidate-bound promotion
        # dispatch (None unless the cycle is authorised and binding succeeded).
        "selected_candidate": binding,
        "queue_decision": queue_decision["decision"],
        "queue_reasons": queue_decision["reasons"],
        "state_authoritative": queue_decision.get("state_authoritative"),
        "capacity_decision": (capacity or {}).get("decision"),
        "not_advice": True,
    }
    if mismatch_reasons:
        result["candidate_mismatch_reasons"] = list(mismatch_reasons)
    return result


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
