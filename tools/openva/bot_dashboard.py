from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
BOT_DASHBOARD = Path("docs/operations/contracts/bot-dashboard.yaml")


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_path(root: Path, path: str | Path) -> Path:
    return root / Path(path)


def markdown_row(values: list[Any]) -> str:
    return "| " + " | ".join("" if value is None else str(value).replace("|", "\\|") for value in values) + " |"


def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get(key) or "unknown") for item in items).items()))


def signal_class_ranks(dashboard_contract: dict[str, Any]) -> dict[str, int]:
    return {str(item["id"]): int(item["rank"]) for item in dashboard_contract.get("signal_classes", [])}


def make_signal(signal_class: str, title: str, summary: str, next_action: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "class": signal_class,
        "title": title,
        "summary": summary,
        "next_action": next_action,
        "evidence": evidence or {},
    }


def sort_signals(signals: list[dict[str, Any]], dashboard_contract: dict[str, Any]) -> list[dict[str, Any]]:
    ranks = signal_class_ranks(dashboard_contract)
    return sorted(signals, key=lambda item: (ranks.get(str(item["class"]), ranks.get("unknown", 999)), str(item["title"])))


def list_items(data: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def generated_at(data: Any) -> str | None:
    if isinstance(data, dict):
        value = data.get("generated_at") or data.get("run_started_at")
        if value:
            return str(value)
    return None


def read_optional_artifacts(root: Path, dashboard_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact in dashboard_contract.get("input_artifacts", []):
        artifact_id = str(artifact["id"])
        rel_path = str(artifact["path"])
        path = repo_path(root, rel_path)
        record: dict[str, Any] = {
            "id": artifact_id,
            "path": rel_path,
            "section": artifact.get("section"),
            "artifact_type": artifact.get("artifact_type"),
            "required": bool(artifact.get("required", False)),
            "stale_after_hours": artifact.get("stale_after_hours"),
            "exists": path.exists(),
            "data": None,
            "error": None,
            "generated_at": None,
        }
        if path.exists():
            try:
                if path.suffix == ".json":
                    record["data"] = load_json(path)
                else:
                    record["data"] = path.read_text(encoding="utf-8")
                record["generated_at"] = generated_at(record["data"])
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                record["error"] = str(exc)
        artifacts[artifact_id] = record
    return artifacts


def summarize_eligibility(artifact: dict[str, Any] | None) -> dict[str, Any]:
    items = list_items((artifact or {}).get("data"), "items")
    strict_ready = [
        item
        for item in items
        if item.get("classification") == "strict_promote_ready" or item.get("promotable_now") is True
    ]
    review_required = [
        item
        for item in items
        if "review" in str(item.get("classification") or "") or item.get("requires_human_review") is True
    ]
    deferred = [
        item
        for item in items
        if "defer" in str(item.get("classification") or "") or item.get("backlog_state") == "deferred"
    ]
    source_failures = [
        item
        for item in items
        if any("source" in str(reason) for reason in item.get("reason_codes", []) or [])
        and item not in strict_ready
    ]
    return {
        "items": items,
        "strict_ready": strict_ready,
        "review_required": review_required,
        "deferred": deferred,
        "source_failures": source_failures,
        "classification_counts": count_by(items, "classification"),
    }


def summarize_promotion_plan(artifact: dict[str, Any] | None) -> dict[str, Any]:
    actions = list_items((artifact or {}).get("data"), "actions", "promotion_actions")
    redirect_deferrals = []
    review_required = []
    for action in actions:
        redirect = action.get("redirect") if isinstance(action.get("redirect"), dict) else {}
        decision = str(redirect.get("decision") or "")
        if decision and decision not in {"keep", "accept"}:
            redirect_deferrals.append(action)
        if action.get("requires_human_review") is True:
            review_required.append(action)
    return {
        "actions": actions,
        "redirect_deferrals": redirect_deferrals,
        "review_required": review_required,
    }


def summarize_queue(artifact: dict[str, Any] | None) -> dict[str, Any]:
    cohorts = list_items((artifact or {}).get("data"), "cohorts")
    return {
        "cohorts": cohorts,
        "status_counts": count_by(cohorts, "status"),
        "priority_counts": count_by(cohorts, "priority"),
    }


def summarize_coverage(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report = artifacts.get("coverage_audit_report", {}).get("data")
    gaps = report.get("gaps", {}) if isinstance(report, dict) and isinstance(report.get("gaps"), dict) else {}
    gap_counts: dict[str, int] = {}
    for key, value in gaps.items():
        if isinstance(value, list):
            gap_counts[key] = len(value)
        elif isinstance(value, dict):
            gap_counts[key] = len(value)
        elif isinstance(value, int):
            gap_counts[key] = value
    return {"gap_counts": dict(sorted(gap_counts.items()))}


def summarize_source_health(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for artifact_id in ("source_health_snapshot", "source_health_report"):
        rows.extend(list_items(artifacts.get(artifact_id, {}).get("data"), "sources", "items", "rows"))
    status_counts = count_by(rows, "status")
    failure_rows = [
        row
        for row in rows
        if str(row.get("status") or row.get("health") or "").lower() in {"gone", "unavailable", "warning", "ambiguous"}
    ]
    return {"rows": rows, "status_counts": status_counts, "failure_rows": failure_rows}


def build_signals(
    *,
    authority: dict[str, Any],
    dashboard_contract: dict[str, Any],
    eligibility: dict[str, Any],
    promotion_plan: dict[str, Any],
    coverage: dict[str, Any],
    source_health: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    errored_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    missing_artifacts = [artifact for artifact in artifacts.values() if not artifact["exists"]]
    required_missing = [artifact for artifact in missing_artifacts if artifact["required"]]

    if required_missing:
        signals.append(
            make_signal(
                "blocking",
                "Required dashboard input missing",
                f"{len(required_missing)} required dashboard input(s) are unavailable.",
                "Regenerate required evidence before relying on write-capable bot recommendations.",
                {"artifacts": [artifact["id"] for artifact in required_missing]},
            )
        )
    if errored_artifacts:
        signals.append(
            make_signal(
                "blocking",
                "Dashboard artifact parse failure",
                f"{len(errored_artifacts)} local artifact(s) could not be parsed.",
                "Fix malformed local artifacts before using dashboard recommendations.",
                {"artifacts": [artifact["id"] for artifact in errored_artifacts]},
            )
        )

    if eligibility["strict_ready"] or promotion_plan["actions"]:
        signals.append(
            make_signal(
                "action_required",
                "Strict-growth evidence available",
                "Local strict-growth evidence exists for controlled promotion review.",
                "Review freshness, queue limits, and source-health evidence before controlled promotion.",
                {"strict_ready": len(eligibility["strict_ready"]), "promotion_actions": len(promotion_plan["actions"])},
            )
        )
    review_count = len(eligibility["review_required"]) + len(promotion_plan["review_required"])
    if review_count:
        signals.append(
            make_signal(
                "action_required",
                "Review-required candidates present",
                f"{review_count} candidate(s) or action(s) require manual review.",
                "Resolve review-required items before source repair or controlled promotion.",
                {"review_required": review_count},
            )
        )
    if source_health["failure_rows"]:
        signals.append(
            make_signal(
                "action_required",
                "Source-health failures present",
                f"{len(source_health['failure_rows'])} source-health row(s) show failure or ambiguity.",
                "Classify source-health failures before relying on related source records.",
                {"failure_rows": len(source_health["failure_rows"])},
            )
        )
    if promotion_plan["redirect_deferrals"]:
        signals.append(
            make_signal(
                "action_required",
                "Redirect deferrals present",
                f"{len(promotion_plan['redirect_deferrals'])} redirect deferral(s) require reviewed evidence.",
                "Resolve redirect canonicalization before promotion.",
                {"redirect_deferrals": len(promotion_plan["redirect_deferrals"])},
            )
        )

    if eligibility["deferred"]:
        signals.append(
            make_signal(
                "watch",
                "Deferred candidates present",
                f"{len(eligibility['deferred'])} candidate(s) are deferred.",
                "Track deferred backlog age before scheduling future promotion review.",
                {"deferred": len(eligibility["deferred"])},
            )
        )
    if coverage["gap_counts"]:
        signals.append(
            make_signal(
                "watch",
                "Coverage gaps present",
                "Local coverage artifact reports one or more gaps.",
                "Use coverage gaps to prioritize discovery, not direct catalog mutation.",
                {"gap_counts": coverage["gap_counts"]},
            )
        )

    if missing_artifacts:
        signals.append(
            make_signal(
                "missing_optional_input",
                "Optional local artifacts missing",
                f"{len(missing_artifacts)} optional local artifact(s) are unavailable in this checkout.",
                "Treat missing optional artifacts as evidence gaps, not workflow failures.",
                {"artifacts": [artifact["id"] for artifact in missing_artifacts]},
            )
        )

    if not signals:
        signals.append(
            make_signal(
                "informational",
                "No actionable local bot signals",
                "No blocking, action-required, watch, or missing optional signals were detected locally.",
                "Keep bot actions report-only until reviewed evidence supports a controlled operation.",
            )
        )

    if not authority["default_posture"].get("undeclared_lanes_are_denied"):
        signals.append(
            make_signal(
                "blocking",
                "Authority posture is not deny-by-default",
                "Undeclared lanes are not denied by default.",
                "Restore deny-by-default bot authority before enabling any write-capable lane.",
            )
        )

    return sort_signals(signals, dashboard_contract)


def highest_priority_next_action(signals: list[dict[str, Any]], fallback: str) -> str:
    if signals:
        return str(signals[0]["next_action"])
    return fallback


def next_safe_action(
    *,
    eligibility: dict[str, Any],
    promotion_plan: dict[str, Any],
    queue_policy: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    signals: list[dict[str, Any]] | None = None,
) -> str:
    fallback: str
    strict_ready = len(eligibility["strict_ready"]) or len(promotion_plan["actions"])
    missing_strict = [
        artifact_id
        for artifact_id in (
            "strict_growth_eligibility_report",
            "strict_growth_promotion_plan",
        )
        if not artifacts.get(artifact_id, {}).get("exists")
    ]
    if missing_strict:
        fallback = "Refresh local strict-growth evidence before recommending controlled promotion."
    elif strict_ready:
        max_open = queue_policy["global"]["max_open_catalog_growth_prs"]
        fallback = (
            "Review the strict-growth promotion plan, confirm stale evidence thresholds, "
            f"and use controlled promotion only if fewer than {max_open} catalog-growth PRs are open."
        )
    else:
        fallback = "Keep discovery/report-only lanes advisory and wait for reviewed evidence before controlled promotion."
    return highest_priority_next_action(signals or [], fallback)


def render_dashboard(root: Path = ROOT) -> str:
    authority = load_yaml(repo_path(root, BOT_AUTHORITY))
    failure_taxonomy = load_yaml(repo_path(root, BOT_FAILURE_TAXONOMY))
    queue_policy = load_yaml(repo_path(root, BOT_QUEUE_POLICY))
    dashboard_contract = load_yaml(repo_path(root, BOT_DASHBOARD))
    artifacts = read_optional_artifacts(root, dashboard_contract)

    eligibility = summarize_eligibility(artifacts.get("strict_growth_eligibility_report"))
    promotion_plan = summarize_promotion_plan(artifacts.get("strict_growth_promotion_plan"))
    discovery_queue = summarize_queue(artifacts.get("catalog_growth_discovery_queue"))
    coverage = summarize_coverage(artifacts)
    source_health = summarize_source_health(artifacts)
    missing_artifacts = [artifact for artifact in artifacts.values() if not artifact["exists"]]
    errored_artifacts = [artifact for artifact in artifacts.values() if artifact["error"]]
    signals = build_signals(
        authority=authority,
        dashboard_contract=dashboard_contract,
        eligibility=eligibility,
        promotion_plan=promotion_plan,
        coverage=coverage,
        source_health=source_health,
        artifacts=artifacts,
        errored_artifacts=errored_artifacts,
    )
    next_action = next_safe_action(
        eligibility=eligibility,
        promotion_plan=promotion_plan,
        queue_policy=queue_policy,
        artifacts=artifacts,
        signals=signals,
    )

    lines: list[str] = [
        "# OpenVA Bot Dashboard",
        "",
        "Generated from local WP9/WP10 contracts and optional local artifacts. This dashboard is advisory and does not update GitHub issues.",
        "",
        "## Current Bot Posture",
        "",
        f"- Undeclared lanes denied: `{authority['default_posture']['undeclared_lanes_are_denied']}`",
        f"- Undeclared write paths denied: `{authority['default_posture']['undeclared_write_paths_are_denied']}`",
        f"- Report-only lanes may write catalog truth: `{authority['default_posture']['report_only_lanes_may_write_catalog_truth']}`",
        f"- Discovery lanes may write catalog truth: `{authority['default_posture']['discovery_lanes_may_write_catalog_truth']}`",
        f"- Dashboard issue update enabled: `{dashboard_contract['dashboard_issue']['create_or_update_enabled']}`",
        "",
        "## Signal Quality Summary",
        "",
        "| Class | Signal | Summary | Next safe action |",
        "|---|---|---|---|",
    ]
    for signal in signals:
        lines.append(markdown_row([f"`{signal['class']}`", signal["title"], signal["summary"], signal["next_action"]]))
    lines.extend(
        [
            "",
            "## Pause Switch Status Model",
            "",
            f"- Global pause switch label: `{queue_policy['global']['pause_switch_label']}`",
            "- Local renderer status: `not_evaluated_without_github_issue_state`",
            "- If the pause switch is active, all write-capable bot actions should stop before branch, PR, label, or merge changes.",
            "",
            "## Strict-Growth Ready Candidates",
            "",
        ]
    )
    strict_ready_count = len(eligibility["strict_ready"])
    action_count = len(promotion_plan["actions"])
    lines.extend(
        [
            f"- Eligibility strict-ready candidates: `{strict_ready_count}`",
            f"- Reviewed promotion actions in local plan: `{action_count}`",
            f"- Discovery queue cohorts: `{len(discovery_queue['cohorts'])}`",
        ]
    )
    if eligibility["classification_counts"]:
        lines.append(f"- Eligibility classifications: `{json.dumps(eligibility['classification_counts'], sort_keys=True)}`")
    lines.extend(["", "## Deferred Candidates", ""])
    lines.append(f"- Deferred candidates detected locally: `{len(eligibility['deferred'])}`")
    lines.append("- Deferred state is advisory until dashboard issue automation is implemented.")
    lines.extend(["", "## Review-Required Candidates", ""])
    review_count = len(eligibility["review_required"]) + len(promotion_plan["review_required"])
    lines.append(f"- Review-required candidates/actions detected locally: `{review_count}`")
    lines.append("- Manual review remains required before source repair or controlled promotion.")
    lines.extend(["", "## Source-Health Failures", ""])
    lines.append(f"- Source-health failure rows detected locally: `{len(source_health['failure_rows'])}`")
    if source_health["status_counts"]:
        lines.append(f"- Source-health statuses: `{json.dumps(source_health['status_counts'], sort_keys=True)}`")
    lines.append(f"- Eligibility source-related failures: `{len(eligibility['source_failures'])}`")
    lines.extend(["", "## Redirect Deferrals", ""])
    lines.append(f"- Redirect deferrals detected in local promotion plan: `{len(promotion_plan['redirect_deferrals'])}`")
    lines.append("- Redirect ambiguity should use `redirect_canonicalization_failure` until reviewed evidence clears it.")
    lines.extend(["", "## Coverage Gaps", ""])
    if coverage["gap_counts"]:
        for name, count in coverage["gap_counts"].items():
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- No local coverage gap artifact was available.")
    lines.extend(["", "## Stale Backlog Items", ""])
    lines.append("- Stale backlog evaluation is policy-defined and should invalidate evidence before write recommendations.")
    lines.append(f"- Strict-growth stale evidence threshold hours: `{queue_policy['global']['stale_evidence_max_age_hours']['strict_growth']}`")
    lines.extend(["", "## Last Successful Catalog-Growth Run", ""])
    latest_success = (
        artifacts.get("strict_growth_eligibility_report", {}).get("generated_at")
        or artifacts.get("strict_growth_promotion_plan", {}).get("generated_at")
        or "not_available_in_local_checkout"
    )
    lines.append(f"- Last successful local catalog-growth artifact timestamp: `{latest_success}`")
    lines.extend(["", "## Last Failed Run", ""])
    if errored_artifacts:
        for artifact in errored_artifacts:
            lines.append(f"- `{artifact['id']}`: `{artifact['error']}`")
    else:
        lines.append("- No failed local artifact parse was detected.")
    lines.extend(["", "## Next Safe Action", "", f"- {next_action}"])
    lines.extend(["", "## Queue Policy Summary", ""])
    global_policy = queue_policy["global"]
    lines.extend(
        [
            f"- Max open catalog-growth PRs: `{global_policy['max_open_catalog_growth_prs']}`",
            f"- Max open source-repair PRs: `{global_policy['max_open_source_repair_prs']}`",
            f"- Max bot PRs per day: `{global_policy['max_bot_prs_per_day']}`",
            f"- Max bot PRs per week: `{global_policy['max_bot_prs_per_week']}`",
            f"- Cooldown after failure hours: `{global_policy['cooldown_after_failure_hours']}`",
            "",
            "| Lane | Max open PRs | Max actions per PR | Schedule | Source-host rate limit | Vendor-domain concurrency |",
            "|---|---:|---:|---|---|---:|",
        ]
    )
    for lane in queue_policy.get("lanes", []):
        lines.append(
            markdown_row(
                [
                    f"`{lane['lane_id']}`",
                    lane["max_open_prs"],
                    lane["max_actions_per_pr"],
                    lane["schedule_window"],
                    lane["source_host_rate_limit"],
                    lane["vendor_domain_concurrency_limit"],
                ]
            )
        )
    lines.extend(["", "## Authority Summary By Lane", ""])
    lines.extend(
        [
            "| Lane | Status | Workflows | Branch writes | Opens PRs | Merges PRs | Catalog truth | Deny by default |",
            "|---|---|---:|---|---|---|---|---|",
        ]
    )
    for lane in authority.get("lanes", []):
        lines.append(
            markdown_row(
                [
                    f"`{lane['id']}`",
                    lane["status"],
                    len(lane.get("workflows", [])),
                    lane["may_write_branches"],
                    lane["may_open_prs"],
                    lane["may_merge_prs"],
                    lane["may_write_catalog_truth"],
                    lane["deny_by_default"],
                ]
            )
        )
    lines.extend(["", "## Failure Taxonomy Summary", ""])
    lines.extend(["| Code | Retry | Escalation | Defer | Stop lane |", "|---|---|---|---|---|"])
    for failure in failure_taxonomy.get("failure_classes", []):
        lines.append(
            markdown_row(
                [
                    f"`{failure['code']}`",
                    failure["retry_eligible"],
                    failure["escalation_target"],
                    failure["defer_candidate"],
                    failure["stop_lane"],
                ]
            )
        )
    lines.extend(["", "## Stale Evidence Thresholds", ""])
    for name, hours in sorted(global_policy["stale_evidence_max_age_hours"].items()):
        lines.append(f"- `{name}`: `{hours}` hours")
    for artifact in dashboard_contract.get("input_artifacts", []):
        lines.append(f"- `{artifact['id']}`: `{artifact['stale_after_hours']}` hours")
    lines.extend(["", "## Missing Local Artifacts", ""])
    if missing_artifacts:
        lines.extend(["| Artifact | Path | Section | Signal class |", "|---|---|---|---|"])
        for artifact in missing_artifacts:
            lines.append(markdown_row([f"`{artifact['id']}`", f"`{artifact['path']}`", artifact["section"], "`missing_optional_input`"] ))
    else:
        lines.append("- No optional local artifacts are missing.")
    lines.extend(
        [
            "",
            "## Operator Checklist",
            "",
            "- Confirm the pause switch is not active before any write-capable action.",
            "- Treat missing local artifacts as unavailable evidence, not as successful runs.",
            "- Resolve `blocking` signals before write-capable bot actions continue.",
            "- Handle `action_required` signals before controlled promotion or source repair.",
            "- Refresh stale strict-growth evidence before controlled promotion.",
            "- Keep discovery and report-only lanes from mutating catalog truth.",
            "- Use reviewed evidence for source repair and controlled promotion.",
            "- Do not create or update a GitHub issue from this local renderer.",
            "",
        ]
    )
    return "\n".join(lines)


def write_dashboard(root: Path = ROOT, output_path: Path | None = None) -> Path:
    dashboard_contract = load_yaml(repo_path(root, BOT_DASHBOARD))
    relative_output = Path(output_path) if output_path else Path(str(dashboard_contract["output_path"]))
    target = relative_output if relative_output.is_absolute() else root / relative_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_dashboard(root), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-dashboard")
    parser.add_argument("command", choices={"render"})
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    path = write_dashboard(ROOT, args.out)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
