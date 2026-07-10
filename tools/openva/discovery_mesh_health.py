"""Production health and efficiency reporting for the OpenVA discovery mesh.

The report distinguishes catalog state, crawl activity, provider replenishment,
and admission yield. It does not score vendors or weaken any admission gate.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.source_verification import ROOT

SCHEMA_VERSION = "0.1.0"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 6)


def percentage(numerator: int | float, denominator: int | float) -> float | None:
    value = ratio(numerator, denominator)
    return None if value is None else round(value * 100.0, 3)


def catalog_snapshot(root: Path = ROOT) -> dict[str, Any]:
    vendor_paths = sorted((root / "data" / "vendors").glob("*/vendor.yaml"))
    source_paths = sorted((root / "data" / "vendors").glob("*/sources/*.yaml"))
    source_type_counts: Counter[str] = Counter()
    vendors_with_sources: set[str] = set()
    source_counts_by_vendor: Counter[str] = Counter()
    active_vendor_count = 0
    provisional_vendor_count = 0

    for path in vendor_paths:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(value, dict):
            continue
        status = str(value.get("catalog_status") or "active")
        if status == "active":
            active_vendor_count += 1
        elif status == "machine_provisional":
            provisional_vendor_count += 1

    for path in source_paths:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(value, dict):
            continue
        vendor_id = str(value.get("vendor_id") or path.parents[1].name)
        source_type = str(value.get("source_type") or "unknown")
        vendors_with_sources.add(vendor_id)
        source_counts_by_vendor[vendor_id] += 1
        source_type_counts[source_type] += 1

    vendor_count = len(vendor_paths)
    source_count = len(source_paths)
    return {
        "vendor_count": vendor_count,
        "active_vendor_count": active_vendor_count,
        "machine_provisional_vendor_count": provisional_vendor_count,
        "source_count": source_count,
        "vendors_with_any_source": len(vendors_with_sources),
        "vendors_without_sources": max(0, vendor_count - len(vendors_with_sources)),
        "vendors_with_any_source_pct": percentage(len(vendors_with_sources), vendor_count),
        "average_sources_per_vendor": ratio(source_count, vendor_count),
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "max_sources_for_one_vendor": max(source_counts_by_vendor.values(), default=0),
    }


def source_discovery_snapshot(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {
            "available": False,
            "vendors_checked": 0,
            "pages_attempted": 0,
            "requests": 0,
            "locator_signal_count": 0,
            "delegated_host_count": 0,
            "verified_candidate_count": 0,
            "identity_signal_count": 0,
            "candidate_source_type_counts": {},
        }
    frontiers = [
        value
        for value in report.get("source_frontier_reports", []) or []
        if isinstance(value, dict)
    ]
    vendors = [value for value in report.get("vendors", []) or [] if isinstance(value, dict)]
    source_types: Counter[str] = Counter()
    verified_candidate_count = 0
    identity_signal_count = int((report.get("summary") or {}).get("vendor_identity_signal_count") or 0)
    for vendor in vendors:
        for candidate in vendor.get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            verified_candidate_count += 1
            source_types[str(candidate.get("source_type_candidate") or "unknown")] += 1
    return {
        "available": True,
        "vendors_checked": int((report.get("summary") or {}).get("vendors_checked") or len(vendors)),
        "pages_attempted": sum(
            int((value.get("summary") or {}).get("pages_attempted") or 0) for value in frontiers
        ),
        "requests": sum(int((value.get("summary") or {}).get("requests") or 0) for value in frontiers),
        "locator_signal_count": sum(
            int((value.get("summary") or {}).get("locator_signal_count") or 0) for value in frontiers
        ),
        "delegated_host_count": sum(
            int((value.get("summary") or {}).get("delegated_host_count") or 0) for value in frontiers
        ),
        "verified_candidate_count": verified_candidate_count,
        "identity_signal_count": identity_signal_count,
        "candidate_source_type_counts": dict(sorted(source_types.items())),
    }


def breadth_snapshot(
    metrics: dict[str, Any] | None,
    queue: dict[str, Any] | None,
    candidates: dict[str, Any] | None,
) -> dict[str, Any]:
    metric_summary = (metrics or {}).get("summary") or {}
    queue_summary = (queue or {}).get("summary") or {}
    candidate_summary = (candidates or {}).get("summary") or {}
    state_counts = queue_summary.get("state_counts") or metric_summary.get("queue_state_counts") or {}
    if not isinstance(state_counts, dict):
        state_counts = {}
    queue_count = int(queue_summary.get("queue_count") or sum(int(value) for value in state_counts.values()))
    ready_count = int(
        queue_summary.get("ready_for_source_discovery_count")
        or metric_summary.get("ready_for_source_discovery_count")
        or 0
    )
    return {
        "available": bool(metrics or queue or candidates),
        "entity_count": int(metric_summary.get("entity_count") or 0),
        "signal_count": int(metric_summary.get("signal_count") or 0),
        "observation_count": int(metric_summary.get("observation_count") or 0),
        "provider_count": int(metric_summary.get("provider_count") or 0),
        "provider_entity_counts": dict(metric_summary.get("provider_entity_counts") or {}),
        "provider_signal_counts": dict(metric_summary.get("provider_signal_counts") or {}),
        "source_kind_counts": dict(metric_summary.get("source_kind_counts") or {}),
        "queue_count": queue_count,
        "queue_state_counts": dict(sorted((str(key), int(value)) for key, value in state_counts.items())),
        "ready_for_source_discovery_count": ready_count,
        "unresolved_identity_count": max(0, queue_count - ready_count - int(state_counts.get("already_catalogued", 0))),
        "ready_for_source_discovery_pct": percentage(ready_count, queue_count),
        "candidate_projection_count": int(candidate_summary.get("candidate_vendor_count") or 0),
        "catalog_vendor_count_cap": None,
    }


def promotion_snapshot(plan: dict[str, Any] | None) -> dict[str, Any]:
    actions = [value for value in (plan or {}).get("actions", []) or [] if isinstance(value, dict)]
    vendors = {
        str(value.get("vendor_id") or (value.get("vendor") or {}).get("candidate_vendor_id") or "")
        for value in actions
    }
    vendors.discard("")
    action_types = Counter(str(value.get("action") or "unknown") for value in actions)
    return {
        "available": plan is not None,
        "viable_action_count": len(actions),
        "vendor_count": len(vendors),
        "action_type_counts": dict(sorted(action_types.items())),
    }


def run_change_snapshot(run_report: dict[str, Any] | None) -> dict[str, Any]:
    summary = (run_report or {}).get("summary") or {}
    changed = sorted(str(value) for value in summary.get("changed_outputs", []) or [])
    unchanged = sorted(str(value) for value in summary.get("unchanged_outputs", []) or [])
    return {
        "available": run_report is not None,
        "input_signal_count": int(summary.get("input_signal_count") or 0),
        "skipped_input_count": int(summary.get("skipped_input_count") or 0),
        "changed_outputs": changed,
        "unchanged_outputs": unchanged,
    }


def build_health_report(
    *,
    root: Path = ROOT,
    source_discovery_report: dict[str, Any] | None = None,
    breadth_metrics: dict[str, Any] | None = None,
    breadth_queue: dict[str, Any] | None = None,
    breadth_candidates: dict[str, Any] | None = None,
    promotion_plan: dict[str, Any] | None = None,
    replenishment_run: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    catalog = catalog_snapshot(root)
    discovery = source_discovery_snapshot(source_discovery_report)
    breadth = breadth_snapshot(breadth_metrics, breadth_queue, breadth_candidates)
    promotion = promotion_snapshot(promotion_plan)
    run_changes = run_change_snapshot(replenishment_run)

    requests = discovery["requests"]
    locators = discovery["locator_signal_count"]
    verified = discovery["verified_candidate_count"]
    viable = promotion["viable_action_count"]
    intake_needed = bool(viable or run_changes["changed_outputs"])

    efficiency = {
        "pages_per_vendor_checked": ratio(discovery["pages_attempted"], discovery["vendors_checked"]),
        "requests_per_vendor_checked": ratio(requests, discovery["vendors_checked"]),
        "locator_signals_per_request": ratio(locators, requests),
        "verified_candidates_per_request": ratio(verified, requests),
        "verified_candidates_per_locator": ratio(verified, locators),
        "viable_promotions_per_verified_candidate": ratio(viable, verified),
    }

    reason_codes: list[str] = []
    if catalog["vendor_count"] and discovery["available"] and discovery["vendors_checked"] == 0:
        reason_codes.append("catalog_present_but_no_vendors_checked")
    if discovery["available"] and requests > 0 and locators == 0:
        reason_codes.append("requests_without_locator_signals")
    if discovery["available"] and verified > 0 and not promotion["available"]:
        reason_codes.append("promotion_plan_missing_for_verified_candidates")
    if not breadth["available"]:
        reason_codes.append("breadth_metrics_unavailable")
    if breadth["candidate_projection_count"] != breadth["ready_for_source_discovery_count"]:
        reason_codes.append("breadth_candidate_projection_count_mismatch")

    status = "attention" if reason_codes else "healthy"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": "discovery_mesh_health",
        "status": status,
        "reason_codes": reason_codes,
        "catalog": catalog,
        "source_discovery": discovery,
        "vendor_breadth": breadth,
        "promotion": promotion,
        "run_changes": run_changes,
        "efficiency": efficiency,
        "intake": {
            "intake_needed": intake_needed,
            "no_op_run": not intake_needed,
            "reason": (
                "viable_source_promotions_or_breadth_state_changed"
                if intake_needed
                else "no_viable_source_promotions_and_breadth_state_unchanged"
            ),
        },
        "success_metrics": {
            "catalog_vendor_count": catalog["vendor_count"],
            "catalog_source_count": catalog["source_count"],
            "vendors_with_any_source_pct": catalog["vendors_with_any_source_pct"],
            "provider_discovered_entity_count": breadth["entity_count"],
            "provider_ready_candidate_count": breadth["ready_for_source_discovery_count"],
            "provider_unresolved_identity_count": breadth["unresolved_identity_count"],
            "locator_signal_count": locators,
            "verified_candidate_count": verified,
            "viable_promotion_action_count": viable,
            "locator_signals_per_request": efficiency["locator_signals_per_request"],
            "verified_candidates_per_request": efficiency["verified_candidates_per_request"],
            "viable_promotions_per_verified_candidate": efficiency[
                "viable_promotions_per_verified_candidate"
            ],
            "catalog_vendor_count_cap": None,
        },
        "posture": {
            "report_only": True,
            "changes_admission_authority": False,
            "vendor_risk_scoring_performed": False,
            "non_advisory": True,
        },
    }


def markdown_report(report: dict[str, Any]) -> str:
    metrics = report["success_metrics"]
    efficiency = report["efficiency"]
    breadth = report["vendor_breadth"]
    lines = [
        "# Discovery Mesh Health",
        "",
        f"Status: `{report['status']}`",
        "",
        "## Catalog",
        "",
        f"- Vendors: `{metrics['catalog_vendor_count']}`",
        f"- Sources: `{metrics['catalog_source_count']}`",
        f"- Vendors with at least one source: `{metrics['vendors_with_any_source_pct']}`%",
        "",
        "## Discovery efficiency",
        "",
        f"- Locator signals: `{metrics['locator_signal_count']}`",
        f"- Verified source candidates: `{metrics['verified_candidate_count']}`",
        f"- Viable promotion actions: `{metrics['viable_promotion_action_count']}`",
        f"- Locator signals per request: `{efficiency['locator_signals_per_request']}`",
        f"- Verified candidates per request: `{efficiency['verified_candidates_per_request']}`",
        f"- Viable promotions per verified candidate: `{efficiency['viable_promotions_per_verified_candidate']}`",
        "",
        "## Vendor breadth",
        "",
        f"- Provider-discovered entities: `{breadth['entity_count']}`",
        f"- Ready for source discovery: `{breadth['ready_for_source_discovery_count']}`",
        f"- Unresolved identities retained: `{breadth['unresolved_identity_count']}`",
        f"- Catalog vendor cap: `none`",
        "",
        "## Intake",
        "",
        f"- Intake needed: `{report['intake']['intake_needed']}`",
        f"- No-op run: `{report['intake']['no_op_run']}`",
    ]
    if report["reason_codes"]:
        lines.extend(["", "## Attention reasons", ""])
        lines.extend(f"- `{value}`" for value in report["reason_codes"])
    lines.extend(
        [
            "",
            "Operational metadata only. This report does not score vendors or alter catalog admission.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-mesh-health")
    parser.add_argument("build", nargs="?")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-discovery-report", type=Path)
    parser.add_argument("--breadth-metrics", type=Path)
    parser.add_argument("--breadth-queue", type=Path)
    parser.add_argument("--breadth-candidates", type=Path)
    parser.add_argument("--promotion-plan", type=Path)
    parser.add_argument("--replenishment-run", type=Path)
    parser.add_argument("--generated-at")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_health_report(
        root=args.root,
        source_discovery_report=load_optional_json(args.source_discovery_report),
        breadth_metrics=load_optional_json(args.breadth_metrics),
        breadth_queue=load_optional_json(args.breadth_queue),
        breadth_candidates=load_optional_json(args.breadth_candidates),
        promotion_plan=load_optional_json(args.promotion_plan),
        replenishment_run=load_optional_json(args.replenishment_run),
        generated_at=args.generated_at,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_md.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], **report["success_metrics"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
