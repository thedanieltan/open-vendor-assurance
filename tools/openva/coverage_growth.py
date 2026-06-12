"""WP34 Coverage Growth Engine.

Coverage reporting and growth prioritization only: identifies missing
vendors, missing source types, stale sources, and high-priority categories,
and routes all growth through the candidate/submission/verification model.
No crawling, no direct catalog mutation, no compliance scoring.

Growth is measured by completeness and freshness, not raw URL count.

priority = category weight
         + missing source criticality
         + business prevalence (wishlist membership)
         + staleness component

All weights are editorial, maintainer-tunable config; every queue row records
its additive breakdown so rankings are auditable, and nothing consumes the
priority automatically.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT
from tools.openva.observation_ledger import (
    DEFAULT_LEDGER_DIR,
    DEFAULT_SLA_CONFIG,
    load_ledger_baseline,
    load_sla_config,
    parse_when,
    sla_for,
)

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "coverage_growth_report"
DEFAULT_TARGETS_CONFIG = ROOT / "config" / "coverage-targets.yaml"

DOCTRINE = (
    "Growth is measured by completeness and freshness, not raw URL count. "
    "New vendors and sources enter as candidates through the submission and "
    "verification model; coverage reporting never writes catalog data."
)

ROUTE = "candidate_submission"

QUEUE_CLASSES = (
    "missing_vendor",
    "missing_source_type",
    "stale_source",
    "ambiguous_source",
    "high_priority_vendor",
    "machine_readable_surface_needed",
)

OBSERVATION_INPUT_RUN_ARTIFACT = "run_artifact"
OBSERVATION_INPUT_FALLBACK = "committed_events_fallback"
OBSERVATION_INPUT_NONE = "none"

AMBIGUOUS_HEALTH = {"gated", "bot_protected"}
STALE_STATUSES = {"stale", "expired", "unknown"}


def load_yaml_file(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def load_targets_config(path: Path = DEFAULT_TARGETS_CONFIG) -> dict[str, Any]:
    config = load_yaml_file(path)
    for key in ("required_source_types", "source_type_criticality", "staleness_weights", "prevalence_weight", "categories"):
        if key not in config:
            raise ValueError(f"{path}: missing {key}")
    return config


def load_records(root: Path, glob: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted(root.glob(glob)):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(record, dict):
            records.append(record)
    return records


def high_priority_categories(targets: dict[str, Any]) -> list[str]:
    return sorted(
        name for name, spec in targets["categories"].items() if int(spec.get("weight", 0)) >= 5
    )


def categories_for_vendor(vendor: dict[str, Any], targets: dict[str, Any]) -> list[str]:
    tags = set(vendor.get("vendor_categories") or [])
    matched = [
        name
        for name, spec in targets["categories"].items()
        if tags & set(spec.get("taxonomy_tags") or [])
    ]
    return sorted(matched)


def wishlist_ids(targets: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for spec in targets["categories"].values():
        for entry in spec.get("priority_vendors") or []:
            ids.add(str(entry.get("vendor_id")))
    return ids


def max_category_weight(categories: list[str], targets: dict[str, Any]) -> int:
    weights = [int(targets["categories"][name].get("weight", 0)) for name in categories]
    return max(weights) if weights else 0


def observation_state(
    latest_observations: dict[str, Any] | None,
    ledger_baseline: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    if latest_observations is not None:
        entries = {
            str(entry.get("source_id")): entry
            for entry in latest_observations.get("sources", [])
            if entry.get("source_id")
        }
        return OBSERVATION_INPUT_RUN_ARTIFACT, entries
    if ledger_baseline:
        return OBSERVATION_INPUT_FALLBACK, dict(ledger_baseline)
    return OBSERVATION_INPUT_NONE, {}


def freshness_status_for(
    source: dict[str, Any],
    observation: dict[str, Any] | None,
    freshness_by_source: dict[str, Any],
    sla_config: dict[str, Any],
    now: datetime,
) -> str:
    from_report = freshness_by_source.get(str(source.get("source_id")))
    if isinstance(from_report, dict) and from_report.get("status"):
        return str(from_report["status"])
    observed_at = (observation or {}).get("observed_at")
    if not observed_at:
        return "unknown"
    sla = sla_for(str(source.get("source_type") or ""), sla_config)
    age_days = max(0, (now - parse_when(str(observed_at))).days)
    if age_days > sla["expired_after_days"]:
        return "expired"
    if age_days > sla["stale_after_days"]:
        return "stale"
    return "fresh"


def priority_row(
    *,
    queue_class: str,
    category: str | None,
    vendor_id: str,
    source_id: str | None,
    source_type: str | None,
    category_weight: int,
    criticality: int,
    prevalence: int,
    staleness: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "queue_class": queue_class,
        "category": category,
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_type": source_type,
        "priority": category_weight + criticality + prevalence + staleness,
        "priority_breakdown": {
            "category_weight": category_weight,
            "missing_source_criticality": criticality,
            "business_prevalence": prevalence,
            "staleness": staleness,
        },
        "reason": reason,
        "route": ROUTE,
    }


def build_coverage_growth_report(
    *,
    root: Path = ROOT,
    targets: dict[str, Any],
    sla_config: dict[str, Any],
    now: datetime,
    generated_at: str,
    latest_observations: dict[str, Any] | None = None,
    freshness_report: dict[str, Any] | None = None,
    ledger_dir: Path | None = None,
) -> dict[str, Any]:
    ledger_dir = ledger_dir if ledger_dir is not None else (root / "maintenance" / "source-observations" / "events")
    vendors = sorted(load_records(root, "data/vendors/*/vendor.yaml"), key=lambda v: str(v.get("vendor_id") or ""))
    sources = load_records(root, "data/vendors/*/sources/*.yaml")
    candidates = load_records(root, "data/vendors/*/candidate_sources/*.yaml")

    observation_input, observations = observation_state(
        latest_observations, load_ledger_baseline(ledger_dir)
    )
    freshness_by_source = {
        str(row.get("source_id")): row.get("freshness")
        for row in (freshness_report or {}).get("sources", [])
        if row.get("source_id")
    }

    required_types = list(targets["required_source_types"])
    criticality = {str(k): int(v) for k, v in targets["source_type_criticality"].items()}
    staleness_weights = {str(k): int(v) for k, v in targets["staleness_weights"].items()}
    prevalence_weight = int(targets["prevalence_weight"])
    wishlist = wishlist_ids(targets)
    high_priority = high_priority_categories(targets)

    materialized_ids = {str(v.get("vendor_id")) for v in vendors}
    vendor_categories = {str(v.get("vendor_id")): categories_for_vendor(v, targets) for v in vendors}
    sources_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        sources_by_vendor.setdefault(str(source.get("vendor_id") or ""), []).append(source)
    candidates_by_vendor: dict[str, int] = {}
    for candidate in candidates:
        vid = str(candidate.get("vendor_id") or "")
        candidates_by_vendor[vid] = candidates_by_vendor.get(vid, 0) + 1

    def vendor_prevalence(vendor_id: str) -> int:
        return prevalence_weight if vendor_id in wishlist else 0

    def vendor_types(vendor_id: str) -> set[str]:
        return {str(s.get("source_type")) for s in sources_by_vendor.get(vendor_id, [])}

    def source_freshness(source: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        observation = observations.get(str(source.get("source_id")))
        return (
            freshness_status_for(source, observation, freshness_by_source, sla_config, now),
            observation,
        )

    # --- section builders -------------------------------------------------
    vendor_count_by_category: dict[str, int] = {name: 0 for name in targets["categories"]}
    uncategorized = 0
    for vendor_id, cats in vendor_categories.items():
        if not cats:
            uncategorized += 1
        for cat in cats:
            vendor_count_by_category[cat] += 1

    source_completeness_by_category = {}
    for name in sorted(targets["categories"]):
        member_ids = sorted(vid for vid, cats in vendor_categories.items() if name in cats)
        per_type = {}
        complete = 0
        for required in required_types:
            have = sum(1 for vid in member_ids if required in vendor_types(vid))
            per_type[required] = {
                "vendors_with_source": have,
                "vendor_count": len(member_ids),
                "ratio": round(have / len(member_ids), 3) if member_ids else None,
            }
        for vid in member_ids:
            if all(required in vendor_types(vid) for required in required_types):
                complete += 1
        source_completeness_by_category[name] = {
            "vendor_count": len(member_ids),
            "complete_vendors": complete,
            "by_source_type": per_type,
        }

    def missing_type_rows(source_type: str) -> list[dict[str, Any]]:
        return [
            {"vendor_id": vid, "categories": vendor_categories[vid]}
            for vid in sorted(materialized_ids)
            if source_type not in vendor_types(vid)
        ]

    missing_dpa = missing_type_rows("dpa")
    missing_subprocessors = missing_type_rows("subprocessors_list")
    missing_trust_centers = missing_type_rows("trust_center")

    stale_rows = []
    for vendor_id in sorted(materialized_ids):
        cats = vendor_categories[vendor_id]
        hp_cats = [c for c in cats if c in high_priority]
        if not hp_cats:
            continue
        for source in sorted(sources_by_vendor.get(vendor_id, []), key=lambda s: str(s.get("source_id") or "")):
            status, observation = source_freshness(source)
            if status in STALE_STATUSES:
                stale_rows.append(
                    {
                        "vendor_id": vendor_id,
                        "source_id": source.get("source_id"),
                        "source_type": source.get("source_type"),
                        "categories": hp_cats,
                        "freshness_status": status,
                        "last_observed_at": (observation or {}).get("observed_at"),
                    }
                )

    candidate_backlog_by_category: dict[str, int] = {name: 0 for name in targets["categories"]}
    candidate_uncategorized = 0
    for vendor_id, count in sorted(candidates_by_vendor.items()):
        cats = vendor_categories.get(vendor_id, [])
        if not cats:
            candidate_uncategorized += count
        for cat in cats:
            candidate_backlog_by_category[cat] += count

    top_missing_vendors = {}
    for name in sorted(targets["categories"]):
        spec = targets["categories"][name]
        weight = int(spec.get("weight", 0))
        rows = []
        for entry in spec.get("priority_vendors") or []:
            vendor_id = str(entry.get("vendor_id"))
            if vendor_id in materialized_ids:
                continue
            rows.append(
                {
                    "vendor_id": vendor_id,
                    "name": entry.get("name"),
                    "priority": weight + prevalence_weight,
                }
            )
        top_missing_vendors[name] = sorted(rows, key=lambda row: (-row["priority"], row["vendor_id"]))

    machine_readable_coverage = {}
    for name in sorted(targets["categories"]):
        member_ids = {vid for vid, cats in vendor_categories.items() if name in cats}
        per_type = {}
        for required in required_types:
            counts = {"machine_readable": 0, "not_machine_readable": 0, "unknown": 0}
            for vid in sorted(member_ids):
                for source in sources_by_vendor.get(vid, []):
                    if str(source.get("source_type")) != required:
                        continue
                    flag = (source.get("retrieval") or {}).get("machine_readable")
                    if flag is True:
                        counts["machine_readable"] += 1
                    elif flag is False:
                        counts["not_machine_readable"] += 1
                    else:
                        counts["unknown"] += 1
            per_type[required] = counts
        machine_readable_coverage[name] = per_type

    # --- growth queue ------------------------------------------------------
    queue: list[dict[str, Any]] = []

    for name in sorted(targets["categories"]):
        spec = targets["categories"][name]
        weight = int(spec.get("weight", 0))
        for row in top_missing_vendors[name]:
            queue.append(
                priority_row(
                    queue_class="missing_vendor",
                    category=name,
                    vendor_id=row["vendor_id"],
                    source_id=None,
                    source_type=None,
                    category_weight=weight,
                    criticality=0,
                    prevalence=prevalence_weight,
                    staleness=0,
                    reason="wishlist vendor not materialized",
                )
            )

    for vendor_id in sorted(materialized_ids):
        cats = vendor_categories[vendor_id]
        if not cats:
            continue
        weight = max_category_weight(cats, targets)
        category = sorted(cats, key=lambda c: (-int(targets["categories"][c].get("weight", 0)), c))[0]
        missing = [t for t in required_types if t not in vendor_types(vendor_id)]
        for source_type in missing:
            queue.append(
                priority_row(
                    queue_class="missing_source_type",
                    category=category,
                    vendor_id=vendor_id,
                    source_id=None,
                    source_type=source_type,
                    category_weight=weight,
                    criticality=criticality.get(source_type, 0),
                    prevalence=vendor_prevalence(vendor_id),
                    staleness=0,
                    reason=f"required source type {source_type} not in catalog",
                )
            )
        if missing and any(c in high_priority for c in cats):
            queue.append(
                priority_row(
                    queue_class="high_priority_vendor",
                    category=category,
                    vendor_id=vendor_id,
                    source_id=None,
                    source_type=None,
                    category_weight=weight,
                    criticality=max(criticality.get(t, 0) for t in missing),
                    prevalence=vendor_prevalence(vendor_id),
                    staleness=0,
                    reason=f"high-priority vendor missing {len(missing)} required source types",
                )
            )

    for row in stale_rows:
        vendor_id = str(row["vendor_id"])
        cats = vendor_categories[vendor_id]
        weight = max_category_weight(cats, targets)
        category = row["categories"][0]
        queue.append(
            priority_row(
                queue_class="stale_source",
                category=category,
                vendor_id=vendor_id,
                source_id=str(row["source_id"]),
                source_type=str(row["source_type"]),
                category_weight=weight,
                criticality=criticality.get(str(row["source_type"]), 0),
                prevalence=vendor_prevalence(vendor_id),
                staleness=staleness_weights.get(str(row["freshness_status"]), 0),
                reason=f"freshness {row['freshness_status']}",
            )
        )

    for vendor_id in sorted(materialized_ids):
        cats = vendor_categories[vendor_id]
        weight = max_category_weight(cats, targets)
        category = cats[0] if cats else None
        for source in sorted(sources_by_vendor.get(vendor_id, []), key=lambda s: str(s.get("source_id") or "")):
            source_id = str(source.get("source_id"))
            source_type = str(source.get("source_type"))
            confidence_class = (source.get("canonical_confidence") or {}).get("class")
            health = (observations.get(source_id) or {}).get("source_health_status")
            if confidence_class == "ambiguous" or health in AMBIGUOUS_HEALTH:
                status, _ = source_freshness(source)
                queue.append(
                    priority_row(
                        queue_class="ambiguous_source",
                        category=category,
                        vendor_id=vendor_id,
                        source_id=source_id,
                        source_type=source_type,
                        category_weight=weight,
                        criticality=criticality.get(source_type, 0),
                        prevalence=vendor_prevalence(vendor_id),
                        staleness=staleness_weights.get(status, 0),
                        reason=(
                            "canonical confidence ambiguous"
                            if confidence_class == "ambiguous"
                            else f"latest observed health {health}"
                        ),
                    )
                )
            if cats and source_type in required_types:
                flag = (source.get("retrieval") or {}).get("machine_readable")
                if flag is not True:
                    queue.append(
                        priority_row(
                            queue_class="machine_readable_surface_needed",
                            category=category,
                            vendor_id=vendor_id,
                            source_id=source_id,
                            source_type=source_type,
                            category_weight=weight,
                            criticality=criticality.get(source_type, 0),
                            prevalence=vendor_prevalence(vendor_id),
                            staleness=0,
                            reason="no machine-readable surface recorded",
                        )
                    )

    queue.sort(
        key=lambda row: (
            -row["priority"],
            QUEUE_CLASSES.index(row["queue_class"]),
            str(row["category"] or ""),
            row["vendor_id"],
            str(row["source_id"] or ""),
        )
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "generated_at": generated_at,
        "doctrine": DOCTRINE,
        "posture": {
            "network_fetch_performed": False,
            "catalog_mutation_performed": False,
            "non_advisory": True,
            "growth_route": ROUTE,
        },
        "observation_input": observation_input,
        "high_priority_categories": high_priority,
        "summary": {
            "vendor_count": len(vendors),
            "source_count": len(sources),
            "candidate_count": len(candidates),
            "growth_queue_count": len(queue),
            "queue_by_class": {
                queue_class: sum(1 for row in queue if row["queue_class"] == queue_class)
                for queue_class in QUEUE_CLASSES
            },
        },
        "vendor_count_by_category": {
            **{name: vendor_count_by_category[name] for name in sorted(vendor_count_by_category)},
            "uncategorized": uncategorized,
        },
        "source_completeness_by_category": source_completeness_by_category,
        "missing_dpa_sources": missing_dpa,
        "missing_subprocessor_sources": missing_subprocessors,
        "missing_trust_centers": missing_trust_centers,
        "stale_high_priority_sources": stale_rows,
        "candidate_backlog_by_category": {
            **{name: candidate_backlog_by_category[name] for name in sorted(candidate_backlog_by_category)},
            "uncategorized": candidate_uncategorized,
        },
        "top_missing_vendors": top_missing_vendors,
        "machine_readable_coverage": machine_readable_coverage,
        "growth_queue": queue,
        "not_advice": True,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Coverage Growth Report",
        "",
        report["doctrine"],
        "",
        "Operational coverage metadata only. It is not legal, compliance, procurement, audit, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        f"- Vendors: `{report['summary']['vendor_count']}`",
        f"- Sources: `{report['summary']['source_count']}`",
        f"- Candidate sources: `{report['summary']['candidate_count']}`",
        f"- Growth queue rows: `{report['summary']['growth_queue_count']}`",
        f"- Observation input: `{report['observation_input']}`",
        f"- High-priority categories: `{', '.join(report['high_priority_categories'])}`",
        "",
        "## Queue by class",
        "",
    ]
    for queue_class, count in report["summary"]["queue_by_class"].items():
        lines.append(f"- `{queue_class}`: {count}")
    lines.extend(["", "## Top of the growth queue", ""])
    for row in report["growth_queue"][:15]:
        target = row["source_id"] or row["source_type"] or row["vendor_id"]
        lines.append(
            f"- [{row['priority']}] `{row['queue_class']}` {row['vendor_id']} ({target}) - {row['reason']}"
        )
    lines.append("")
    return "\n".join(lines)


def write_queue_csv(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["priority", "queue_class", "category", "vendor_id", "source_id", "source_type", "reason", "route"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in report["growth_queue"]:
            writer.writerow(row)


def load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-coverage-growth")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build the coverage growth report")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--markdown-output", type=Path, default=None)
    build.add_argument("--csv-output", type=Path, default=None)
    build.add_argument("--latest-observations", type=Path, default=None)
    build.add_argument("--freshness-report", type=Path, default=None)
    build.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    build.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_CONFIG)
    build.add_argument("--sla-config", type=Path, default=DEFAULT_SLA_CONFIG)
    args = parser.parse_args()

    now = datetime.now(UTC)
    report = build_coverage_growth_report(
        targets=load_targets_config(args.targets),
        sla_config=load_sla_config(args.sla_config),
        now=now,
        generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        latest_observations=load_optional_json(args.latest_observations),
        freshness_report=load_optional_json(args.freshness_report),
        ledger_dir=args.ledger_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    if args.csv_output:
        write_queue_csv(report, args.csv_output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
