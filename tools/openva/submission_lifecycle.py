"""WP40A submission issue lifecycle status.

One idempotent bot status comment per human-submitted candidate issue. The
comment tracks the submission along the *same* lifecycle the autonomous lanes
use and never asks a maintainer to act on a routine catalog record:

    submitted -> verified -> eligible -> materialising -> machine_provisional
              -> observing -> quorum_pending -> active

or a fail-closed terminal outcome:

    submitted -> verified -> deferred
    submitted -> rejected

The comment is keyed by a stable marker so re-running intake replaces the same
comment instead of appending. When the lifecycle reaches a terminal state the
issue is closed automatically; no maintainer closes a routine submission.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

COMMENT_MARKER = "<!-- openva-submission-lifecycle -->"

# Ordered lifecycle (progress states). Terminal outcomes are separate.
PROGRESS_STATES = (
    "submitted",
    "verified",
    "eligible",
    "materialising",
    "machine_provisional",
    "observing",
    "quorum_pending",
    "active",
)

# Terminal states close the issue automatically.
TERMINAL_STATES = {"active", "deferred", "rejected", "rolled_back"}

ALL_STATES = PROGRESS_STATES + ("deferred", "rejected", "rolled_back")

# eligibility_state (candidate_record) -> lifecycle state after verification.
ELIGIBILITY_TO_STATE = {
    "pending": "verified",
    "eligible": "eligible",
}

NEXT_ACTION = {
    "submitted": "verify submitted sources",
    "verified": "evaluate eligibility",
    "eligible": "materialise machine_provisional vendor (one-vendor PR)",
    "materialising": "merge machine_provisional PR after not_before + release gates",
    "machine_provisional": "accumulate stable observations",
    "observing": "run independent machine quorum",
    "quorum_pending": "promote on quorum or reject",
    "active": "none (catalog record is live)",
    "deferred": "none (fails closed; re-evaluated when fresh evidence arrives)",
    "rejected": "none (closed; resubmit with corrected evidence)",
    "rolled_back": "none (machine-created state reverted)",
}


def derive_state(
    *,
    verification_done: bool,
    eligibility_state: str | None,
    materialising: bool = False,
    catalog_status: str | None = None,
    rolled_back: bool = False,
) -> str:
    """Derive the current lifecycle state from authoritative signals.

    Precedence runs from the most advanced committed signal backwards so the
    comment always reflects the furthest point actually reached.
    """
    if rolled_back:
        return "rolled_back"
    if catalog_status == "active":
        return "active"
    if catalog_status == "machine_provisional":
        return "machine_provisional"
    if materialising:
        return "materialising"
    if eligibility_state:
        if eligibility_state.startswith("rejected_"):
            return "rejected"
        if eligibility_state.startswith("deferred_"):
            return "deferred"
        return ELIGIBILITY_TO_STATE.get(eligibility_state, "verified")
    if verification_done:
        return "verified"
    return "submitted"


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def should_close(state: str) -> bool:
    return is_terminal(state)


def render_status_comment(
    *,
    state: str,
    candidate_id: str | None,
    verification_result: str | None,
    decision_id: str | None = None,
    pr_url: str | None = None,
    last_completed_action: str | None = None,
    decision_reasons: list[str] | None = None,
) -> str:
    """Render the single idempotent lifecycle comment (stable marker)."""
    if state not in ALL_STATES:
        raise ValueError(f"unknown lifecycle state: {state}")
    final_outcome = state if is_terminal(state) else "pending"
    rows = [
        ("Current state", f"`{state}`"),
        ("Last completed action", last_completed_action or "submission verified"),
        ("Verification result", f"`{verification_result}`" if verification_result else "n/a"),
        ("Candidate ID", f"`{candidate_id}`" if candidate_id else "n/a"),
        ("Linked decision", f"`{decision_id}`" if decision_id else "n/a"),
        ("Linked PR", pr_url or "n/a"),
        ("Next scheduled action", NEXT_ACTION.get(state, "n/a")),
        ("Final outcome", f"`{final_outcome}`"),
    ]
    lines = [
        COMMENT_MARKER,
        "## OpenVA submission lifecycle",
        "",
        "Automated lifecycle status for this candidate. OpenVA records observable "
        "public metadata and provenance only; this is not legal, compliance, "
        "procurement, security, or vendor-risk advice, and it neither approves nor "
        "scores any vendor.",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    lines += [f"| {label} | {value} |" for label, value in rows]
    if decision_reasons:
        lines += ["", "Decision reasons:", ""]
        lines += [f"- `{reason}`" for reason in decision_reasons]
    lines += [
        "",
        "Routine catalog records are created, observed, and promoted autonomously "
        "through pull requests; no maintainer approval is required for a routine "
        "submission. This issue closes automatically at a terminal state.",
    ]
    return "\n".join(lines) + "\n"


def status_payload(
    *,
    state: str,
    candidate_id: str | None,
    verification_result: str | None,
    decision_id: str | None = None,
    pr_url: str | None = None,
    last_completed_action: str | None = None,
    decision_reasons: list[str] | None = None,
) -> dict[str, Any]:
    comment = render_status_comment(
        state=state,
        candidate_id=candidate_id,
        verification_result=verification_result,
        decision_id=decision_id,
        pr_url=pr_url,
        last_completed_action=last_completed_action,
        decision_reasons=decision_reasons,
    )
    return {
        "marker": COMMENT_MARKER,
        "state": state,
        "terminal": is_terminal(state),
        "close_issue": should_close(state),
        "comment_body": comment,
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-submission-lifecycle")
    parser.add_argument("--candidate", type=Path, help="candidate record JSON (supplies state + ids)")
    parser.add_argument("--state", choices=ALL_STATES, help="explicit lifecycle state override")
    parser.add_argument("--decision-id", default=None)
    parser.add_argument("--pr-url", default=None)
    parser.add_argument("--catalog-status", default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    candidate_id = verification_result = None
    eligibility_state = None
    decision_reasons: list[str] = []
    if args.candidate:
        record = json.loads(args.candidate.read_text(encoding="utf-8"))
        candidate_id = record.get("candidate_id")
        eligibility_state = record.get("eligibility_state")
        decision_reasons = record.get("decision_reasons") or []
        evidence = record.get("evidence_references") or []
        if evidence:
            verification_result = evidence[0].get("verification_result")

    state = args.state or derive_state(
        verification_done=True,
        eligibility_state=eligibility_state,
        catalog_status=args.catalog_status,
    )
    payload = status_payload(
        state=state,
        candidate_id=candidate_id,
        verification_result=verification_result,
        decision_id=args.decision_id,
        pr_url=args.pr_url,
        decision_reasons=decision_reasons,
    )
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(payload["comment_body"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
