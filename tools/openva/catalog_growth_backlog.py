from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva.automerge_lanes import load_policy
from tools.openva.catalog_growth_eligibility import REVIEW_REQUIRED, STRICT_PROMOTE_READY
from tools.openva.source_verification import ROOT

REPORT_TYPE = "catalog_growth_backlog_report"
CSV_FIELDS = [
    "candidate_vendor_id",
    "display_name_candidate",
    "official_domain_candidate",
    "coverage_lane",
    "cohort_id",
    "eligibility_classification",
    "backlog_state",
    "refresh_policy",
    "evidence_hash",
    "source_candidate_count",
    "strict_source_count",
    "reason_codes",
]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def evidence_hash_for(item: dict[str, Any]) -> str:
    payload = {
        "candidate_vendor_id": item.get("candidate_vendor_id"),
        "official_domain_candidate": item.get("official_domain_candidate"),
        "classification": item.get("classification"),
        "reason_codes": item.get("reason_codes", []),
        "source_health_rejections": item.get("source_health_rejections", []),
        "source_candidate_count": item.get("source_candidate_count", 0),
        "strict_source_count": item.get("strict_source_count", 0),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def backlog_state_for(classification: str) -> str:
    if classification == STRICT_PROMOTE_READY:
        return "strict_pr_candidate"
    if classification == REVIEW_REQUIRED:
        return "human_review_required"
    return "rejected"


def refresh_policy_for(state: str, policy: dict[str, Any]) -> str:
    backlog = policy.get("backlog", {})
    if state == "strict_pr_candidate":
        cfg = backlog.get("strict_pr_candidate", {})
        return f"expires_after:{cfg.get('expires_after_days')}d/{cfg.get('expires_after_cycles')}cycles"
    if state == "human_review_required":
        cfg = backlog.get("human_review_required", {})
        return f"refresh_after:{cfg.get('refresh_after_days')}d/{cfg.get('refresh_after_cycles')}cycles"
    if state == "deferred":
        cfg = backlog.get("deferred", {})
        return f"refresh_after:{cfg.get('refresh_after_days')}d/{cfg.get('refresh_after_cycles')}cycles"
    cfg = backlog.get("rejected", {})
    return f"suppress_rediscovery:{cfg.get('suppress_rediscovery_days')}d"


def build_catalog_growth_backlog(
    eligibility_report: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if eligibility_report.get("report_type") != "catalog_growth_eligibility_report":
        raise ValueError("expected catalog_growth_eligibility_report")
    policy = policy or load_policy()
    items: list[dict[str, Any]] = []
    for item in eligibility_report.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        classification = str(item.get("classification") or "")
        state = backlog_state_for(classification)
        reason_codes = item.get("reason_codes", []) or []
        items.append(
            {
                "candidate_vendor_id": item.get("candidate_vendor_id"),
                "display_name_candidate": item.get("display_name_candidate"),
                "official_domain_candidate": item.get("official_domain_candidate"),
                "coverage_lane": item.get("coverage_lane"),
                "cohort_id": item.get("cohort_id"),
                "eligibility_classification": classification,
                "backlog_state": state,
                "refresh_policy": refresh_policy_for(state, policy),
                "evidence_hash": evidence_hash_for(item),
                "source_candidate_count": item.get("source_candidate_count", 0),
                "strict_source_count": item.get("strict_source_count", 0),
                "reason_codes": reason_codes,
                "source_health_rejections": item.get("source_health_rejections", []) or [],
                "non_advisory": True,
            }
        )
    counts = Counter(row["backlog_state"] for row in items)
    return {
        "schema_version": "0.1.0",
        "generated_at": generated_at or now_iso(),
        "report_type": REPORT_TYPE,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "opens_pull_requests": False,
            "non_advisory": True,
        },
        "policy": {
            "cadence": policy.get("backlog", {}).get("cadence", "weekly"),
            "evidence_hash_controls_reclassification": bool(
                policy.get("backlog", {}).get("evidence_hash_controls_reclassification", True)
            ),
        },
        "summary": {
            "candidate_count": len(items),
            "backlog_state_counts": dict(sorted(counts.items())),
            "strict_pr_candidate_count": counts.get("strict_pr_candidate", 0),
            "human_review_required_count": counts.get("human_review_required", 0),
            "rejected_count": counts.get("rejected", 0),
        },
        "items": sorted(items, key=lambda row: (row["backlog_state"], str(row.get("candidate_vendor_id") or ""))),
    }


def write_outputs(report: dict[str, Any], output_json: Path, output_csv: Path, output_md: Path) -> None:
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in report["items"]:
            row = dict(item)
            row["reason_codes"] = ";".join(row.get("reason_codes", []))
            writer.writerow(row)
    lines = [
        "# Catalog Growth Backlog Summary",
        "",
        "This backlog is operational memory. It is not catalog truth and does not mutate canonical records.",
        "",
        "## Summary",
        "",
        f"- Candidate vendors: `{report['summary']['candidate_count']}`",
        f"- Strict PR candidates: `{report['summary']['strict_pr_candidate_count']}`",
        f"- Human review required: `{report['summary']['human_review_required_count']}`",
        f"- Rejected: `{report['summary']['rejected_count']}`",
        "",
        "## State Counts",
        "",
    ]
    lines.extend(f"- `{name}`: `{count}`" for name, count in report["summary"]["backlog_state_counts"].items())
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-growth-backlog")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--eligibility-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=ROOT / "catalog-growth-backlog-report.json")
    parser.add_argument("--output-csv", type=Path, default=ROOT / "catalog-growth-backlog.csv")
    parser.add_argument("--output-md", type=Path, default=ROOT / "catalog-growth-backlog-summary.md")
    args = parser.parse_args()
    report = build_catalog_growth_backlog(load_json(args.eligibility_report))
    write_outputs(report, args.output_json, args.output_csv, args.output_md)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
