from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva.automerge_lanes import load_policy
from tools.openva.promotion_planner import strict_growth_action
from tools.openva.source_verification import ROOT, display_path

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "strict_growth_shortlist"
STRICT_SAFE_VERIFICATION_STATUSES = {"ok", "redirected"}
SOURCE_PREFLIGHT_RISK_STATUSES = {
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "suspect_inferred_url",
    "soft_not_found",
    "soft_404_detected",
    "bot_protected",
    "gated_or_login_required",
    "forbidden_unknown",
    "rate_limited",
    "unreachable",
    "not_found",
    "gone",
    "server_error",
    "client_error",
}
EXCLUDED_CLASSIFICATIONS = {
    "review_required",
    "deferred",
    "rejected",
    "ambiguous",
    "reject_existing_vendor",
    "reject_duplicate",
    "reject_no_public_source",
    "reject_access_ambiguous",
    "reject_weak_semantic_match",
    "reject_source_health_failure",
    "reject_identity_unclear",
}
CSV_FIELDS = [
    "rank",
    "candidate_vendor_id",
    "display_name_candidate",
    "official_domain_candidate",
    "source_type_candidate",
    "candidate_source_id",
    "candidate_url",
    "verification_status",
    "evidence_hash",
    "reason_codes",
]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def evidence_hash_for(action: dict[str, Any]) -> str:
    payload = {
        "vendor": action.get("vendor", {}),
        "source": action.get("source", {}),
        "classification": action.get("classification"),
        "reason_codes": action.get("reason_codes", []),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_type_priority(policy: dict[str, Any]) -> list[str]:
    configured = policy.get("strict_growth", {}).get("source_type_priority", [])
    return [str(source_type) for source_type in configured if str(source_type)]


def action_sort_key(action: dict[str, Any], policy: dict[str, Any]) -> tuple[int, str, str]:
    priority = {source_type: index for index, source_type in enumerate(source_type_priority(policy))}
    source = action.get("source", {}) or {}
    vendor = action.get("vendor", {}) or {}
    source_type = str(source.get("source_type_candidate") or "")
    return (
        priority.get(source_type, len(priority)),
        str(vendor.get("candidate_vendor_id") or ""),
        str(source.get("candidate_source_id") or ""),
    )


def strict_item_by_vendor(eligibility_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("candidate_vendor_id")): item
        for item in eligibility_report.get("items", []) or []
        if isinstance(item, dict) and item.get("classification") == "strict_promote_ready"
    }


def excluded_from_eligibility(eligibility_report: dict[str, Any]) -> list[dict[str, Any]]:
    excluded: list[dict[str, Any]] = []
    for item in eligibility_report.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        classification = str(item.get("classification") or "")
        if classification != "strict_promote_ready" or classification in EXCLUDED_CLASSIFICATIONS:
            excluded.append(
                {
                    "candidate_vendor_id": item.get("candidate_vendor_id"),
                    "display_name_candidate": item.get("display_name_candidate"),
                    "official_domain_candidate": item.get("official_domain_candidate"),
                    "classification": classification,
                    "reason_codes": item.get("reason_codes", []) or [f"classification:{classification}"],
                }
            )
        for source in item.get("source_health_rejections", []) or []:
            if isinstance(source, dict):
                excluded.append(
                    {
                        "candidate_vendor_id": item.get("candidate_vendor_id"),
                        "display_name_candidate": item.get("display_name_candidate"),
                        "official_domain_candidate": item.get("official_domain_candidate"),
                        "candidate_source_id": source.get("candidate_source_id"),
                        "source_type_candidate": source.get("source_type_candidate"),
                        "candidate_url": source.get("candidate_url"),
                        "classification": source.get("classification") or "reject_source_health_failure",
                        "reason_codes": source.get("reason_codes", []) or ["source_preflight_risk"],
                    }
                )
    return excluded


def action_exclusion(action: dict[str, Any], reason_codes: list[str]) -> dict[str, Any]:
    vendor = action.get("vendor", {}) or {}
    source = action.get("source", {}) or {}
    evidence = source.get("evidence", {}) or {}
    return {
        "candidate_vendor_id": vendor.get("candidate_vendor_id"),
        "display_name_candidate": vendor.get("display_name_candidate"),
        "official_domain_candidate": vendor.get("official_domain_candidate"),
        "candidate_source_id": source.get("candidate_source_id"),
        "source_type_candidate": source.get("source_type_candidate"),
        "candidate_url": source.get("candidate_url"),
        "verification_status": evidence.get("verification_status"),
        "classification": action.get("classification"),
        "reason_codes": reason_codes,
    }


def action_exclusion_reasons(action: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    sg = policy.get("strict_growth", {})
    source = action.get("source", {}) or {}
    evidence = source.get("evidence", {}) or {}
    reasons: list[str] = []
    source_type = str(source.get("source_type_candidate") or "")
    if source_type not in set(sg.get("core_source_types", [])):
        reasons.append(f"non_core_source_type:{source_type}")
    verification_status = str(evidence.get("verification_status") or "")
    if verification_status in SOURCE_PREFLIGHT_RISK_STATUSES:
        reasons.append(f"source_preflight_risk:{verification_status}")
    if verification_status not in STRICT_SAFE_VERIFICATION_STATUSES:
        reasons.append(f"verification_status_not_strict_safe:{verification_status or 'missing'}")
    for reason in action.get("reason_codes", []) or []:
        if reason.startswith("source_preflight_risk:") or reason.startswith("strict_growth_advisory_wording_detected:"):
            reasons.append(reason)
    if evidence.get("http_status") != 200:
        reasons.append("http_status_not_200")
    if not evidence.get("matched_terms"):
        reasons.append("matched_terms_missing")
    if not evidence.get("final_url"):
        reasons.append("final_url_missing")
    if action.get("requires_human_review") is True:
        reasons.append("review_required_action")
    if action.get("strict_machine_candidate") is not True:
        reasons.append("strict_machine_candidate_not_true")
    if action.get("non_advisory") is not True:
        reasons.append("non_advisory_not_true")
    return sorted(dict.fromkeys(reasons))


def shortlist_item(action: dict[str, Any], rank: int) -> dict[str, Any]:
    vendor = action.get("vendor", {}) or {}
    source = action.get("source", {}) or {}
    evidence = source.get("evidence", {}) or {}
    return {
        "rank": rank,
        "candidate_vendor_id": vendor.get("candidate_vendor_id"),
        "display_name_candidate": vendor.get("display_name_candidate"),
        "official_domain_candidate": vendor.get("official_domain_candidate"),
        "source_type_candidate": source.get("source_type_candidate"),
        "candidate_source_id": source.get("candidate_source_id"),
        "candidate_url": source.get("candidate_url"),
        "verification_status": evidence.get("verification_status"),
        "evidence_hash": evidence_hash_for(action),
        "reason_codes": ["strict_growth_shortlisted"],
        "promotion_action_preview": action,
    }


def build_strict_growth_shortlist(
    eligibility_report: dict[str, Any],
    backlog_report: dict[str, Any] | None = None,
    *,
    policy: dict[str, Any] | None = None,
    generated_at: str | None = None,
    max_vendors: int | None = None,
    max_actions: int | None = None,
) -> dict[str, Any]:
    if eligibility_report.get("report_type") != "catalog_growth_eligibility_report":
        raise ValueError("expected catalog_growth_eligibility_report")
    if backlog_report is not None and backlog_report.get("report_type") != "catalog_growth_backlog_report":
        raise ValueError("expected catalog_growth_backlog_report")
    if max_vendors is not None and max_vendors < 0:
        raise ValueError("max_vendors must be non-negative")
    if max_actions is not None and max_actions < 0:
        raise ValueError("max_actions must be non-negative")

    policy = policy or load_policy()
    sg = policy.get("strict_growth", {})
    max_vendors = max_vendors if max_vendors is not None else int(sg.get("max_new_vendors_per_pr", 5))
    max_actions = max_actions if max_actions is not None else int(sg.get("max_new_vendors_per_pr", 5))
    max_sources_per_vendor = int(sg.get("max_sources_per_new_vendor", 2))
    strict_by_vendor = strict_item_by_vendor(eligibility_report)
    candidates: list[dict[str, Any]] = []
    excluded = excluded_from_eligibility(eligibility_report)
    evidence_reasons: list[str] = []
    if not eligibility_report.get("head_sha"):
        evidence_reasons.append("head_sha_missing")
    if not eligibility_report.get("base_sha"):
        evidence_reasons.append("base_sha_missing")

    for raw_action in eligibility_report.get("strict_promotions", []) or []:
        if not isinstance(raw_action, dict):
            continue
        vendor_id = str(raw_action.get("vendor", {}).get("candidate_vendor_id") or "")
        item = strict_by_vendor.get(vendor_id)
        if not item:
            continue
        action = strict_growth_action(item, raw_action)
        reasons = [*evidence_reasons, *action_exclusion_reasons(action, policy)]
        if reasons:
            excluded.append(action_exclusion(action, reasons))
        else:
            candidates.append(action)

    selected: list[dict[str, Any]] = []
    vendor_ids: set[str] = set()
    source_counts: dict[str, int] = defaultdict(int)
    for action in sorted(candidates, key=lambda row: action_sort_key(row, policy)):
        vendor_id = str(action.get("vendor", {}).get("candidate_vendor_id") or "")
        if vendor_id not in vendor_ids and len(vendor_ids) >= max_vendors:
            excluded.append(action_exclusion(action, ["strict_growth_shortlist_vendor_limit_exceeded"]))
            continue
        if source_counts[vendor_id] >= max_sources_per_vendor:
            excluded.append(action_exclusion(action, ["strict_growth_vendor_source_cap_exceeded"]))
            continue
        if len(selected) >= max_actions:
            excluded.append(action_exclusion(action, ["strict_growth_shortlist_max_actions_exceeded"]))
            continue
        vendor_ids.add(vendor_id)
        source_counts[vendor_id] += 1
        selected.append(action)

    items = [shortlist_item(action, rank) for rank, action in enumerate(selected, start=1)]
    reason_counts = Counter(reason for row in excluded for reason in row.get("reason_codes", []))
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "generated_at": generated_at or now_iso(),
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "opens_pull_requests": False,
            "non_advisory": True,
        },
        "summary": {
            "shortlisted_vendor_count": len({item["candidate_vendor_id"] for item in items}),
            "shortlisted_action_count": len(items),
            "excluded_count": len(excluded),
            "excluded_by_reason": dict(sorted(reason_counts.items())),
            "max_vendors": max_vendors,
            "max_actions": max_actions,
        },
        "items": items,
        "excluded": sorted(
            excluded,
            key=lambda row: (
                str(row.get("candidate_vendor_id") or ""),
                str(row.get("source_type_candidate") or ""),
                str(row.get("candidate_source_id") or ""),
                ";".join(row.get("reason_codes", [])),
            ),
        ),
    }
    if eligibility_report.get("head_sha"):
        report["head_sha"] = eligibility_report["head_sha"]
    if eligibility_report.get("base_sha"):
        report["base_sha"] = eligibility_report["base_sha"]
    return report


def promotion_plan_from_shortlist(
    shortlist: dict[str, Any],
    *,
    head_sha: str | None = None,
    base_sha: str | None = None,
    max_actions: int | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if shortlist.get("report_type") != REPORT_TYPE:
        raise ValueError(f"expected {REPORT_TYPE}")
    items = sorted(
        [item for item in shortlist.get("items", []) or [] if isinstance(item, dict)],
        key=lambda item: int(item.get("rank") or 0),
    )
    if max_actions is not None and max_actions < 0:
        raise ValueError("max_actions must be non-negative")
    selected = items if max_actions in {None, 0} else items[:max_actions]
    deferred = items[len(selected) :]
    actions = [item["promotion_action_preview"] for item in selected]
    counts = Counter(action.get("action") for action in actions)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": "strict_growth_promotion_plan",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "action_count": len(actions),
            "uncapped_action_count": len(shortlist.get("items", []) or []),
            "source_health_screened_action_count": len(shortlist.get("items", []) or []),
            "source_health_deferred_action_count": 0,
            "policy_capped_action_count": len(shortlist.get("items", []) or []),
            "actions_requiring_human_review": 0,
            "action_types": dict(sorted(counts.items())),
            "deferred_action_count": len(deferred),
            "batch_deferred_action_count": len(deferred),
            "max_actions_per_plan": max_actions,
            "shortlist_action_count": len(shortlist.get("items", []) or []),
        },
        "actions": actions,
    }
    if deferred:
        plan["deferred_actions"] = [
            {
                "action": item["promotion_action_preview"],
                "reason_codes": ["workflow_max_actions_per_plan_exceeded"],
            }
            for item in deferred
        ]
    effective_head_sha = head_sha or shortlist.get("head_sha")
    effective_base_sha = base_sha or shortlist.get("base_sha")
    if effective_head_sha:
        plan["head_sha"] = effective_head_sha
    if effective_base_sha:
        plan["base_sha"] = effective_base_sha
    return plan


def write_outputs(report: dict[str, Any], output_json: Path, output_csv: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in report.get("items", []):
            row = dict(item)
            row["reason_codes"] = ";".join(row.get("reason_codes", []))
            writer.writerow(row)
    lines = [
        "# Strict Growth Shortlist Summary",
        "",
        "This shortlist is generated from strict-growth eligibility evidence. It does not mutate catalog records.",
        "",
        "## Summary",
        "",
        f"- Shortlisted vendors: `{report['summary']['shortlisted_vendor_count']}`",
        f"- Shortlisted actions: `{report['summary']['shortlisted_action_count']}`",
        f"- Excluded candidates/actions: `{report['summary']['excluded_count']}`",
        "",
        "## Excluded By Reason",
        "",
    ]
    excluded_by_reason = report["summary"].get("excluded_by_reason", {})
    if excluded_by_reason:
        lines.extend(f"- `{reason}`: `{count}`" for reason, count in excluded_by_reason.items())
    else:
        lines.append("- none")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-strict-growth-shortlist")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--eligibility-report", type=Path, required=True)
    build.add_argument("--backlog-report", type=Path, required=True)
    build.add_argument("--output-json", type=Path, default=ROOT / "strict-growth-shortlist.json")
    build.add_argument("--output-csv", type=Path, default=ROOT / "reports" / "strict-growth-shortlist.csv")
    build.add_argument("--output-md", type=Path, default=ROOT / "reports" / "strict-growth-shortlist-summary.md")
    build.add_argument("--max-vendors", type=int)
    build.add_argument("--max-actions", type=int)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--shortlist", type=Path, required=True)
    plan.add_argument("--output", type=Path, default=ROOT / "strict-growth-promotion-plan.json")
    plan.add_argument("--head-sha")
    plan.add_argument("--base-sha")
    plan.add_argument("--max-actions", type=int)
    args = parser.parse_args()
    if args.command == "build":
        report = build_strict_growth_shortlist(
            load_json(args.eligibility_report),
            load_json(args.backlog_report),
            max_vendors=args.max_vendors,
            max_actions=None if args.max_actions in {None, 0} else args.max_actions,
        )
        write_outputs(report, args.output_json, args.output_csv, args.output_md)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    else:
        report = promotion_plan_from_shortlist(
            load_json(args.shortlist),
            head_sha=args.head_sha,
            base_sha=args.base_sha,
            max_actions=None if args.max_actions in {None, 0} else args.max_actions,
        )
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
