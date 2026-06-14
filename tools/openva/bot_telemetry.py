"""WP39 operational telemetry.

Operational COUNTS only, computed from committed state (the decision store, the
catalog, the observation ledger, and the reproducibility audit). It carries no
scores, rankings, recommendations, or vendor-risk signals — telemetry reports
what the machine quorum did, never a judgement about any vendor.

Surfaces: provisional / promoted / challenged / quarantined / rollback counts,
decisions-by-bot, separation-of-duty failures, deferred-or-rejected decisions,
and unresolved reproducibility defects.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.catalog_audit import audit_catalog
from tools.openva.indexes import ROOT
from tools.openva.machine_decisions import DEFAULT_DECISIONS_DIR, load_decisions, validate_committed
from tools.openva import work_priority

LEDGER_DIR = ROOT / "maintenance" / "source-observations" / "events"
CANDIDATES_DIR = ROOT / "maintenance" / "candidates"
QUEUE_POLICY_PATH = ROOT / "docs" / "operations" / "contracts" / "bot-queue-policy.yaml"


def load_candidates(candidates_dir: Path) -> list[dict[str, Any]]:
    if not candidates_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(candidates_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("candidate_id"):
            records.append(data)
    return records


def _pr_budget() -> dict[str, int]:
    if not QUEUE_POLICY_PATH.exists():
        return {"daily": 0, "weekly": 0}
    policy = yaml.safe_load(QUEUE_POLICY_PATH.read_text(encoding="utf-8")) or {}
    glob = policy.get("global", {}) if isinstance(policy, dict) else {}
    return {
        "daily": int(glob.get("max_bot_prs_per_day", 0)),
        "weekly": int(glob.get("max_bot_prs_per_week", 0)),
    }


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def latest_event_per_source(ledger_dir: Path) -> dict[str, dict[str, Any]]:
    from tools.openva.observation_ledger import load_ledger_baseline

    return load_ledger_baseline(ledger_dir)


def build_telemetry(
    root: Path = ROOT,
    decisions_dir: Path = DEFAULT_DECISIONS_DIR,
    ledger_dir: Path = LEDGER_DIR,
    candidates_dir: Path | None = None,
    live_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates_dir = candidates_dir if candidates_dir is not None else (root / "maintenance" / "candidates")
    decisions = load_decisions(decisions_dir)
    by_decision = Counter(str(r.get("decision")) for r in decisions)
    by_decision_type = Counter(str(r.get("decision_type")) for r in decisions if r.get("decision_type"))
    by_bot = Counter(str(r.get("deciding_bot")) for r in decisions if r.get("deciding_bot"))

    provisional = promoted = 0
    for path in (root / "data" / "vendors").glob("*/vendor.yaml"):
        vendor = load_yaml(path)
        if vendor.get("catalog_status") == "machine_provisional":
            provisional += 1
        elif vendor.get("catalog_status") == "active" and vendor.get("machine_generated") is True:
            promoted += 1

    quarantined_sources = sum(
        1 for path in (root / "data" / "vendors").glob("*/sources/*.yaml")
        if load_yaml(path).get("review_state") == "quarantined"
    )

    # Open challenges: sources whose latest committed observation still flags review.
    challenged = sum(
        1 for event in latest_event_per_source(ledger_dir).values()
        if (event.get("review_signal") or {}).get("required") is True
    )

    sod_failures = sum(1 for reason in validate_committed(decisions_dir) if "separation_of_duty" in reason)
    audit = audit_catalog(root=root, decisions_dir=decisions_dir)

    # --- candidate buckets (committed candidate records) ---
    candidates = load_candidates(candidates_dir)
    eligible = [c for c in candidates if c.get("eligibility_state") == "eligible"]
    deferred = [c for c in candidates if str(c.get("eligibility_state", "")).startswith("deferred_")]
    rejected = [c for c in candidates if str(c.get("eligibility_state", "")).startswith("rejected_")]
    oldest_deferred = min(
        (c for c in deferred if c.get("created_at")),
        key=lambda c: str(c.get("created_at")),
        default=None,
    )

    # --- next eligible action: highest-priority work class with pending work ---
    eligible_classes: list[str] = []
    if challenged:
        eligible_classes.append("observation_continuity")
    if audit.findings:
        eligible_classes.append("rollback")
    if challenged:
        eligible_classes.append("quarantine")
    if eligible:
        eligible_classes.append("machine_provisional_growth")
    next_eligible_action = work_priority.select_next(eligible_classes)

    budget = _pr_budget()
    live = live_state or {}

    return {
        "schema_version": "0.1.0",
        "report_type": "bot_operational_telemetry",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "non_advisory": True,
        "carries_scores_or_rankings": False,
        "counts": {
            "candidate_total": len(candidates),
            "eligible_candidates": len(eligible),
            "deferred_candidates": len(deferred),
            "rejected_candidates": len(rejected),
            "provisional_vendors": provisional,
            "promoted_vendors": promoted,
            "quarantined_sources": quarantined_sources,
            "autonomous_repair_decisions": by_decision_type.get("repair", 0),
            "open_challenged_sources": challenged,
            "rollback_decisions": by_decision.get("rollback", 0),
            "deferred_or_rejected_decisions": by_decision.get("defer", 0) + by_decision.get("reject", 0),
            "separation_of_duty_failures": sod_failures,
            "unresolved_reproducibility_defects": len(audit.findings),
            "decisions_total": len(decisions),
        },
        "decisions_by_type": dict(sorted(by_decision.items())),
        "decisions_by_decision_type": dict(sorted(by_decision_type.items())),
        "decisions_by_deciding_bot": dict(sorted(by_bot.items())),
        "pr_budget": budget,
        "oldest_deferred_candidate": (oldest_deferred or {}).get("candidate_id"),
        "next_eligible_action": next_eligible_action,
        "live": {
            # Live operational surface; supplied by the workflow from authoritative
            # GitHub state. Absent fields are reported as null, never fabricated.
            "available": bool(live),
            "open_bot_prs_by_lane": live.get("open_bot_prs_by_lane"),
            "daily_prs_used": live.get("daily_prs_used"),
            "weekly_prs_used": live.get("weekly_prs_used"),
            "latest_success_by_lane": live.get("latest_success_by_lane"),
            "latest_failure_by_lane": live.get("latest_failure_by_lane"),
            "next_scheduled_action": live.get("next_scheduled_action"),
        },
        "not_advice": True,
    }


def render_markdown(telemetry: dict[str, Any]) -> str:
    lines = [
        "## Bot Operational Telemetry",
        "",
        "Operational counts only; not legal, compliance, procurement, security, or vendor-risk advice. "
        "No scores, rankings, or recommendations.",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
    ]
    for key, value in telemetry["counts"].items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines += ["", "### Decisions by deciding bot", "", "| Bot | Decisions |", "| --- | ---: |"]
    for bot, count in telemetry["decisions_by_deciding_bot"].items():
        lines.append(f"| `{bot}` | {count} |")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-telemetry")
    parser.add_argument("command", choices=["build"])
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args(argv)

    telemetry = build_telemetry(decisions_dir=args.decisions_dir)
    if args.out_json:
        args.out_json.write_text(json.dumps(telemetry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = render_markdown(telemetry)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
