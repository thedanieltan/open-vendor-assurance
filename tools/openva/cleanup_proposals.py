from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva.source_verification import ROOT, display_path

ACTION_ORDER = (
    "retire_or_replace_source_for_review",
    "cleanup_source_for_review",
    "promote_candidate_for_review",
    "review_unavailable_conflict",
    "manual_review_required",
    "keep_unavailable_until_next_review",
    "no_action_existing_source_type",
)

ACTION_HEADINGS = {
    "retire_or_replace_source_for_review": "Retire or replace unavailable canonical sources",
    "cleanup_source_for_review": "Clean up suspect or mismatched canonical sources",
    "promote_candidate_for_review": "Review candidate sources for possible promotion",
    "review_unavailable_conflict": "Resolve unavailable-source conflicts",
    "manual_review_required": "Manual review required",
    "keep_unavailable_until_next_review": "Keep unavailable-source ledger entries",
    "no_action_existing_source_type": "No action because canonical source type already exists",
}

ACTION_DESCRIPTIONS = {
    "retire_or_replace_source_for_review": "The existing source appears unavailable. Review whether to remove, replace, or mark it unavailable.",
    "cleanup_source_for_review": "The existing source appears generic, mismatched, or likely inferred. Review whether to remove or replace it.",
    "promote_candidate_for_review": "A candidate source has evidence but must be reviewed before becoming canonical.",
    "review_unavailable_conflict": "An unavailable-source ledger entry conflicts with an existing canonical source type.",
    "manual_review_required": "The planner could not safely classify this action beyond manual review.",
    "keep_unavailable_until_next_review": "The source type is intentionally absent until the next scheduled review.",
    "no_action_existing_source_type": "A canonical source type already exists, so no candidate promotion is proposed.",
}


def load_plan(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def action_key(action: dict[str, Any]) -> tuple[int, str, str, str]:
    action_name = str(action.get("action") or "")
    try:
        index = ACTION_ORDER.index(action_name)
    except ValueError:
        index = len(ACTION_ORDER)
    return (
        index,
        str(action.get("vendor_id") or ""),
        str(action.get("source_type") or ""),
        str(action.get("source_id") or action.get("candidate_source_id") or action.get("unavailable_source_id") or ""),
    )


def summarize_action(action: dict[str, Any]) -> str:
    bits = []
    for label, key in (
        ("vendor", "vendor_id"),
        ("source_type", "source_type"),
        ("source_id", "source_id"),
        ("candidate_source_id", "candidate_source_id"),
        ("unavailable_source_id", "unavailable_source_id"),
        ("url", "source_url"),
        ("candidate_url", "candidate_url"),
        ("path", "path"),
        ("next_review_after", "next_review_after"),
    ):
        value = action.get(key)
        if value not in (None, "", []):
            bits.append(f"{label}: `{value}`")

    verification = action.get("verification") or {}
    if verification:
        status = verification.get("verification_status")
        http_status = verification.get("http_status")
        final_url = verification.get("final_url")
        if status:
            bits.append(f"verification: `{status}`")
        if http_status:
            bits.append(f"http_status: `{http_status}`")
        if final_url:
            bits.append(f"final_url: `{final_url}`")

    evidence = action.get("evidence") or {}
    if evidence:
        confidence = evidence.get("confidence")
        matched_terms = evidence.get("matched_terms") or []
        if confidence:
            bits.append(f"confidence: `{confidence}`")
        if matched_terms:
            bits.append("matched_terms: " + ", ".join(f"`{term}`" for term in matched_terms))

    return " — ".join(bits)


def build_cleanup_proposal(plan: dict[str, Any]) -> dict[str, Any]:
    actions = sorted(plan.get("actions", []) or [], key=action_key)
    by_action: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_vendor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in actions:
        by_action[str(action.get("action") or "unknown")].append(action)
        by_vendor[str(action.get("vendor_id") or "unknown")].append(action)

    counts = Counter(str(action.get("action") or "unknown") for action in actions)
    blocking_actions = [
        action for action in actions
        if action.get("action") in {
            "retire_or_replace_source_for_review",
            "cleanup_source_for_review",
            "review_unavailable_conflict",
            "manual_review_required",
        }
    ]
    promotable_candidates = [action for action in actions if action.get("action") == "promote_candidate_for_review"]

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "cleanup_proposal",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "action_count": len(actions),
            "blocking_cleanup_actions": len(blocking_actions),
            "promotable_candidate_actions": len(promotable_candidates),
            "action_types": dict(sorted(counts.items())),
            "vendors_with_actions": sorted(by_vendor.keys()),
        },
        "groups": {action_name: grouped for action_name, grouped in sorted(by_action.items())},
    }


def render_markdown(proposal: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Cleanup Proposal",
        "",
        "This proposal is non-advisory. It does not make legal, procurement, compliance, risk, or vendor approval conclusions.",
        "",
        "It is generated from a promotion plan and is intended to help maintainers prepare reviewable catalog changes.",
        "",
        "## Summary",
        "",
    ]
    summary = proposal["summary"]
    lines.extend([
        f"- Action count: `{summary['action_count']}`",
        f"- Blocking cleanup actions: `{summary['blocking_cleanup_actions']}`",
        f"- Promotable candidate actions: `{summary['promotable_candidate_actions']}`",
        "",
        "### Action type counts",
        "",
    ])
    for action_name, count in summary.get("action_types", {}).items():
        lines.append(f"- `{action_name}`: `{count}`")
    lines.append("")

    groups = proposal.get("groups", {}) or {}
    for action_name in ACTION_ORDER:
        actions = groups.get(action_name, [])
        if not actions:
            continue
        lines.extend([
            f"## {ACTION_HEADINGS.get(action_name, action_name)}",
            "",
            ACTION_DESCRIPTIONS.get(action_name, "Review required."),
            "",
        ])
        for action in actions:
            lines.append(f"- {summarize_action(action)}")
            reason = action.get("reason")
            if reason:
                lines.append(f"  - Reason: {reason}")
        lines.append("")

    unknown_actions = sorted(set(groups) - set(ACTION_ORDER))
    if unknown_actions:
        lines.extend(["## Unknown action types", ""])
        for action_name in unknown_actions:
            lines.append(f"### `{action_name}`")
            for action in groups[action_name]:
                lines.append(f"- {summarize_action(action)}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-cleanup-proposals")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--promotion-plan", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, default=ROOT / "cleanup-proposal.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "cleanup-proposal.md")
    args = parser.parse_args()

    plan = load_plan(args.promotion_plan)
    proposal = build_cleanup_proposal(plan)
    args.json_output.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(proposal), encoding="utf-8")
    print(json.dumps(proposal["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
