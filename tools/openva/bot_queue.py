from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
DEFAULT_REPORT = Path("maintenance/bot-queue-report.json")

DECISION_ORDER = {"allow": 0, "defer": 1, "deny": 2, "pause": 3}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    reasons = report.get("reasons") or []
    violated = report.get("violated_policies") or []
    stale = report.get("stale_evidence") or {}
    open_prs = report.get("open_pr_evaluation") or {}
    recent = report.get("recent_bot_pr_evaluation") or {}
    lines = [
        "# OpenVA Bot Queue Decision",
        "",
        "## Decision",
        "",
        f"- Lane: `{report.get('lane_id')}`",
        f"- Decision: `{report.get('decision')}`",
        f"- Next safe action: {report.get('next_safe_action')}",
        "",
        "## Reasons",
        "",
        *[f"- `{reason}`" for reason in reasons],
        "",
        "## Violated Policies",
        "",
        *([f"- `{policy}`" for policy in violated] if violated else ["- None"]),
        "",
        "## Queue Evidence",
        "",
        f"- Open PR count: `{open_prs.get('open_pr_count')}`",
        f"- Max open PRs: `{open_prs.get('max_open_prs')}`",
        f"- Recent bot PRs today: `{recent.get('day_count')}`",
        f"- Recent bot PRs this week: `{recent.get('week_count')}`",
        f"- Evidence generated at: `{stale.get('generated_at')}`",
        f"- Evidence stale: `{stale.get('stale')}`",
        f"- Evidence missing: `{stale.get('missing')}`",
        "",
    ]
    return "\n".join(lines)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    return {
        "authority": load_yaml(root / BOT_AUTHORITY),
        "queue": load_yaml(root / BOT_QUEUE_POLICY),
        "failure_taxonomy": load_yaml(root / BOT_FAILURE_TAXONOMY),
    }


def load_state(path: Path) -> dict[str, Any]:
    state = load_yaml(path)
    if not isinstance(state.get("open_prs"), list):
        state["open_prs"] = []
    if not isinstance(state.get("recent_bot_prs"), dict):
        state["recent_bot_prs"] = {}
    if not isinstance(state.get("pause"), dict):
        state["pause"] = {}
    state["recent_bot_prs"].setdefault("day_count", 0)
    state["recent_bot_prs"].setdefault("week_count", 0)
    state["pause"].setdefault("active", False)
    return state


def lane_by_id(authority: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(lane["id"]): lane for lane in authority.get("lanes", [])}


def queue_lane_by_id(queue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(lane["lane_id"]): lane for lane in queue.get("lanes", [])}


def failure_codes(failure_taxonomy: dict[str, Any]) -> set[str]:
    return {str(entry["code"]) for entry in failure_taxonomy.get("failure_classes", [])}


def lane_is_write_capable(lane: dict[str, Any]) -> bool:
    write_fields = (
        "may_write_branches",
        "may_open_prs",
        "may_label_prs",
        "may_enable_auto_merge",
        "may_merge_prs",
        "may_write_catalog_truth",
    )
    if any(bool(lane.get(field)) for field in write_fields):
        return True
    return any(value == "write" for value in lane.get("token_permissions", {}).values())


def choose_decision(current: str, candidate: str) -> str:
    if DECISION_ORDER[candidate] > DECISION_ORDER[current]:
        return candidate
    return current


def lane_open_prs(state: dict[str, Any], lane_id: str) -> list[dict[str, Any]]:
    prs = state.get("open_prs", []) or []
    return [pr for pr in prs if isinstance(pr, dict) and str(pr.get("lane_id") or lane_id) == lane_id]


def requested_action(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("requested_action")
    return value if isinstance(value, dict) else {}


def evaluate_stale_evidence(state: dict[str, Any], queue_lane: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    threshold = queue_lane.get("stale_evidence_max_age_hours") if queue_lane else None
    generated = parse_time((state.get("evidence") or {}).get("generated_at") if isinstance(state.get("evidence"), dict) else None)
    result = {
        "generated_at": isoformat_z(generated) if generated else None,
        "threshold_hours": threshold,
        "age_hours": None,
        "stale": False,
        "missing": generated is None,
    }
    if generated and threshold is not None:
        age_hours = (now - generated).total_seconds() / 3600
        result["age_hours"] = round(age_hours, 3)
        result["stale"] = age_hours > float(threshold)
    return result


def evaluate_cooldown(state: dict[str, Any], global_policy: dict[str, Any], failure_taxonomy: dict[str, Any], now: datetime) -> dict[str, Any]:
    last_failure = state.get("last_failure") if isinstance(state.get("last_failure"), dict) else {}
    occurred = parse_time(last_failure.get("occurred_at"))
    threshold = int(global_policy.get("cooldown_after_failure_hours", 0))
    code = last_failure.get("code")
    known_code = code in failure_codes(failure_taxonomy) if code else None
    result = {
        "failure_code": code,
        "known_failure_code": known_code,
        "occurred_at": isoformat_z(occurred) if occurred else None,
        "threshold_hours": threshold,
        "age_hours": None,
        "active": False,
    }
    if occurred and threshold > 0:
        age_hours = (now - occurred).total_seconds() / 3600
        result["age_hours"] = round(age_hours, 3)
        result["active"] = age_hours < threshold
    return result


def evaluate_duplicate_pr(state: dict[str, Any], lane_id: str, queue_lane: dict[str, Any] | None) -> dict[str, Any]:
    policy = str((queue_lane or {}).get("duplicate_pr_policy") or "")
    action = requested_action(state)
    duplicate_key = action.get("duplicate_key")
    open_prs = lane_open_prs(state, lane_id)
    duplicates: list[dict[str, Any]] = []
    for pr in open_prs:
        if duplicate_key and pr.get("duplicate_key") == duplicate_key:
            duplicates.append(pr)
        elif not duplicate_key and policy.startswith("do_not_create_duplicate") and open_prs:
            duplicates.append(pr)
    return {
        "policy": policy,
        "requested_duplicate_key": duplicate_key,
        "duplicate_open_pr_numbers": [pr.get("number") for pr in duplicates],
        "duplicate_found": bool(duplicates),
    }


def evaluate_source_host_limit(state: dict[str, Any], queue_lane: dict[str, Any] | None) -> dict[str, Any]:
    action = requested_action(state)
    active_count = int((state.get("source_host_activity") or {}).get("active_count", 0))
    return {
        "policy": (queue_lane or {}).get("source_host_rate_limit"),
        "source_host": action.get("source_host"),
        "active_count": active_count,
        "placeholder": True,
        "limited": active_count > 0 and bool(action.get("source_host")),
    }


def evaluate_vendor_domain_limit(state: dict[str, Any], queue_lane: dict[str, Any] | None) -> dict[str, Any]:
    action = requested_action(state)
    active_count = int((state.get("vendor_domain_activity") or {}).get("active_count", 0))
    limit = int((queue_lane or {}).get("vendor_domain_concurrency_limit", 0) or 0)
    return {
        "limit": limit,
        "vendor_domain": action.get("vendor_domain"),
        "active_count": active_count,
        "placeholder": True,
        "limited": bool(action.get("vendor_domain")) and limit > 0 and active_count >= limit,
    }


def evaluate_base_change(state: dict[str, Any], queue_lane: dict[str, Any] | None) -> dict[str, Any]:
    base_change = state.get("base_change") if isinstance(state.get("base_change"), dict) else {}
    base_changed = bool(base_change.get("base_changed", False))
    policy_satisfied = bool(base_change.get("policy_satisfied", not base_changed))
    return {
        "policy": (queue_lane or {}).get("base_change_policy"),
        "base_changed": base_changed,
        "policy_satisfied": policy_satisfied,
        "placeholder": True,
        "blocked": base_changed and not policy_satisfied,
    }


def next_safe_action_for(decision: str, reasons: list[str], lane_id: str) -> str:
    if decision == "allow":
        return f"{lane_id} may proceed in report-only queue terms; caller must still satisfy reviewed evidence and workflow checks."
    if decision == "pause":
        return "Do not take write-capable bot actions until the pause switch is cleared by a maintainer."
    if "unknown_lane" in reasons:
        return "Declare the lane in bot-authority.yaml before any bot action."
    if "lane_missing_queue_policy" in reasons:
        return "Add an explicit lane entry to bot-queue-policy.yaml before queue-managed write actions."
    if "lane_not_write_capable" in reasons:
        return "Keep this lane report-only or expand authority through a reviewed contract PR."
    if "cooldown_after_failure_active" in reasons:
        return "Wait for cooldown expiry or record maintainer-reviewed recovery evidence before retry."
    if "stale_evidence" in reasons or "missing_evidence" in reasons:
        return "Refresh evidence before controlled promotion, source repair, or other write-capable action."
    if "duplicate_pr_policy" in reasons or "max_open_prs_exceeded" in reasons:
        return "Use the existing open PR or wait until queue capacity is available."
    return "Defer until the violated queue policy is cleared."


def evaluate(
    lane_id: str,
    state: dict[str, Any],
    *,
    policies: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    policies = policies or load_policy()
    now = now or datetime.now(UTC).replace(microsecond=0)
    authority = policies["authority"]
    queue = policies["queue"]
    failure_taxonomy = policies.get("failure_taxonomy", {"failure_classes": []})

    authority_lane = lane_by_id(authority).get(lane_id)
    queue_lane = queue_lane_by_id(queue).get(lane_id)
    global_policy = queue["global"]
    reasons: list[str] = []
    violated: list[str] = []
    decision = "allow"

    pause_state = state.get("pause") if isinstance(state.get("pause"), dict) else {}
    if pause_state.get("active") is True:
        decision = "pause"
        reasons.append("pause_switch_active")
        violated.append("global.pause_switch_label")

    if authority_lane is None:
        decision = choose_decision(decision, "deny")
        reasons.append("unknown_lane")
        violated.append("authority.lanes")
    if queue_lane is None:
        decision = choose_decision(decision, "deny")
        reasons.append("lane_missing_queue_policy")
        violated.append("queue.lanes")

    if authority_lane is not None:
        if authority_lane.get("deny_by_default") is not True:
            decision = choose_decision(decision, "deny")
            reasons.append("lane_not_deny_by_default")
            violated.append("authority.deny_by_default")
        if not lane_is_write_capable(authority_lane):
            decision = choose_decision(decision, "deny")
            reasons.append("lane_not_write_capable")
            violated.append("authority.write_capability")

    open_prs = lane_open_prs(state, lane_id)
    stale = evaluate_stale_evidence(state, queue_lane, now)
    cooldown = evaluate_cooldown(state, global_policy, failure_taxonomy, now)
    duplicate = evaluate_duplicate_pr(state, lane_id, queue_lane)
    source_host = evaluate_source_host_limit(state, queue_lane)
    vendor_domain = evaluate_vendor_domain_limit(state, queue_lane)
    base_change = evaluate_base_change(state, queue_lane)

    if queue_lane is not None:
        max_open_prs = int(queue_lane["max_open_prs"])
        if max_open_prs > 0 and len(open_prs) >= max_open_prs:
            decision = choose_decision(decision, "defer")
            reasons.append("max_open_prs_exceeded")
            violated.append("queue.lanes.max_open_prs")
        if duplicate["duplicate_found"]:
            decision = choose_decision(decision, "defer")
            reasons.append("duplicate_pr_policy")
            violated.append("queue.lanes.duplicate_pr_policy")
        if stale["missing"]:
            decision = choose_decision(decision, "defer")
            reasons.append("missing_evidence")
            violated.append("queue.lanes.stale_evidence_max_age_hours")
        elif stale["stale"]:
            decision = choose_decision(decision, "defer")
            reasons.append("stale_evidence")
            violated.append("queue.lanes.stale_evidence_max_age_hours")
        if source_host["limited"]:
            decision = choose_decision(decision, "defer")
            reasons.append("source_host_rate_limit_placeholder")
            violated.append("queue.lanes.source_host_rate_limit")
        if vendor_domain["limited"]:
            decision = choose_decision(decision, "defer")
            reasons.append("vendor_domain_concurrency_limit")
            violated.append("queue.lanes.vendor_domain_concurrency_limit")
        if base_change["blocked"]:
            decision = choose_decision(decision, "defer")
            reasons.append("base_change_policy")
            violated.append("queue.lanes.base_change_policy")

    recent = state.get("recent_bot_prs") if isinstance(state.get("recent_bot_prs"), dict) else {}
    if int(recent.get("day_count", 0)) >= int(global_policy["max_bot_prs_per_day"]):
        decision = choose_decision(decision, "defer")
        reasons.append("max_bot_prs_per_day_exceeded")
        violated.append("queue.global.max_bot_prs_per_day")
    if int(recent.get("week_count", 0)) >= int(global_policy["max_bot_prs_per_week"]):
        decision = choose_decision(decision, "defer")
        reasons.append("max_bot_prs_per_week_exceeded")
        violated.append("queue.global.max_bot_prs_per_week")
    if cooldown["active"]:
        decision = choose_decision(decision, "defer")
        reasons.append("cooldown_after_failure_active")
        violated.append("queue.global.cooldown_after_failure_hours")

    if not reasons:
        reasons.append("queue_policy_satisfied")

    referenced_queue_policy_values = {
        "global": {
            "pause_switch_label": global_policy["pause_switch_label"],
            "max_bot_prs_per_day": global_policy["max_bot_prs_per_day"],
            "max_bot_prs_per_week": global_policy["max_bot_prs_per_week"],
            "cooldown_after_failure_hours": global_policy["cooldown_after_failure_hours"],
        },
        "lane": queue_lane or None,
    }
    referenced_authority_values = None
    if authority_lane is not None:
        referenced_authority_values = {
            "id": authority_lane["id"],
            "status": authority_lane["status"],
            "deny_by_default": authority_lane["deny_by_default"],
            "may_write_branches": authority_lane["may_write_branches"],
            "may_open_prs": authority_lane["may_open_prs"],
            "may_label_prs": authority_lane["may_label_prs"],
            "may_enable_auto_merge": authority_lane["may_enable_auto_merge"],
            "may_merge_prs": authority_lane["may_merge_prs"],
            "may_write_catalog_truth": authority_lane["may_write_catalog_truth"],
        }

    return {
        "version": 1,
        "report_type": "bot_queue_decision",
        "lane_id": lane_id,
        "state_lane_id": state.get("lane_id"),
        "decision": decision,
        "reasons": reasons,
        "violated_policies": sorted(set(violated)),
        "referenced_queue_policy_values": referenced_queue_policy_values,
        "referenced_authority_values": referenced_authority_values,
        "open_pr_evaluation": {
            "open_pr_count": len(open_prs),
            "open_pr_numbers": [pr.get("number") for pr in open_prs],
            "max_open_prs": queue_lane.get("max_open_prs") if queue_lane else None,
        },
        "recent_bot_pr_evaluation": {
            "day_count": int(recent.get("day_count", 0)),
            "week_count": int(recent.get("week_count", 0)),
            "max_bot_prs_per_day": global_policy["max_bot_prs_per_day"],
            "max_bot_prs_per_week": global_policy["max_bot_prs_per_week"],
        },
        "stale_evidence": stale,
        "cooldown": cooldown,
        "duplicate_pr": duplicate,
        "source_host_rate_limit": source_host,
        "vendor_domain_concurrency": vendor_domain,
        "base_change": base_change,
        "next_safe_action": next_safe_action_for(decision, reasons, lane_id),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-queue")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--lane", required=True)
    evaluate_parser.add_argument("--state", type=Path, required=True)
    evaluate_parser.add_argument("--out", type=Path, default=ROOT / DEFAULT_REPORT)
    evaluate_parser.add_argument("--out-md", type=Path, help="Optional markdown queue decision report.")
    evaluate_parser.add_argument("--now", help="Evaluation time as ISO-8601, for deterministic local reports.")
    args = parser.parse_args(argv)

    if args.command == "evaluate":
        now = parse_time(args.now) if args.now else None
        report = evaluate(args.lane, load_state(args.state), now=now)
        out = args.out if args.out.is_absolute() else ROOT / args.out
        write_json(out, report)
        if args.out_md:
            out_md = args.out_md if args.out_md.is_absolute() else ROOT / args.out_md
            write_text(out_md, render_markdown(report))
        print(json.dumps({"decision": report["decision"], "reasons": report["reasons"]}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
