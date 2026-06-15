from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from tools.openva.source_verification import ROOT, display_path

QUEUE_PATH = ROOT / "maintenance" / "queues" / "catalog-growth-discovery.json"
TAXONOMY_PATH = ROOT / "config" / "category-taxonomy.yaml"
ALLOWED_PRIORITIES = {"high", "medium", "low"}
ALLOWED_STATUSES = {"queued", "paused", "done"}
ALLOWED_DISCOVERY_MODES = {
    "seed_file_vendor_discovery",
    "official_domain_source_discovery",
    # Tier A: bounded, report-only robots/sitemap inspection on a vendor's own
    # official domain. Produces zero-weight discovery-event candidates only.
    "sitemap_source_discovery",
}
SITEMAP_DISCOVERY_MODE = "sitemap_source_discovery"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def taxonomy_controls(root: Path = ROOT) -> tuple[set[str], set[str]]:
    taxonomy = load_yaml(root / "config" / "category-taxonomy.yaml")
    lanes = set((taxonomy.get("coverage_lanes") or {}).keys())
    source_types: set[str] = set()
    for artifact in (taxonomy.get("artifact_categories") or {}).values():
        if isinstance(artifact, dict):
            source_types.update(str(item) for item in artifact.get("maps_to_artifact_types", []) or [])
    return lanes, source_types


def validate_queue(path: Path = QUEUE_PATH, root: Path = ROOT) -> dict[str, Any]:
    queue = load_json(path)
    if queue.get("queue_type") != "catalog_growth_discovery_queue":
        raise ValueError("queue_type must be catalog_growth_discovery_queue")
    if queue.get("non_advisory") is not True:
        raise ValueError("queue must be non_advisory")

    posture = queue.get("posture", {}) or {}
    for key in [
        "network_fetch_performed",
        "writes_repository_state",
        "writes_canonical_sources",
        "creates_candidate_sources",
    ]:
        if posture.get(key) is not False:
            raise ValueError(f"posture.{key} must be false")

    lanes, taxonomy_source_types = taxonomy_controls(root)
    source_types = queue.get("source_types", []) or []
    if not source_types:
        raise ValueError("source_types must not be empty")
    for source_type in source_types:
        if source_type not in taxonomy_source_types:
            raise ValueError(f"unknown source type: {source_type}")

    modes = queue.get("discovery_modes", []) or []
    if not modes:
        raise ValueError("discovery_modes must not be empty")
    for mode in modes:
        if mode not in ALLOWED_DISCOVERY_MODES:
            raise ValueError(f"unknown discovery mode: {mode}")

    limits = queue.get("limits", {}) or {}
    for key in [
        "target_vendor_candidates",
        "max_vendors_per_discovery_run",
        "max_candidate_sources_per_report",
        "max_reviewed_actions_per_plan",
    ]:
        value = limits.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"limits.{key} must be a positive integer")

    cohorts = queue.get("cohorts", []) or []
    if not cohorts:
        raise ValueError("cohorts must not be empty")

    seen: set[str] = set()
    lane_counts: Counter[str] = Counter()
    for index, cohort in enumerate(cohorts):
        if not isinstance(cohort, dict):
            raise ValueError(f"cohort {index} must be an object")
        cohort_id = str(cohort.get("cohort_id") or "")
        if not cohort_id:
            raise ValueError(f"cohort {index} missing cohort_id")
        if cohort_id in seen:
            raise ValueError(f"duplicate cohort_id: {cohort_id}")
        seen.add(cohort_id)
        lane = cohort.get("coverage_lane")
        if lane not in lanes:
            raise ValueError(f"{cohort_id}: unknown coverage lane {lane}")
        lane_counts[str(lane)] += 1
        if cohort.get("priority") not in ALLOWED_PRIORITIES:
            raise ValueError(f"{cohort_id}: invalid priority")
        if cohort.get("status") not in ALLOWED_STATUSES:
            raise ValueError(f"{cohort_id}: invalid status")
        target = cohort.get("target_vendor_candidates")
        if not isinstance(target, int) or target <= 0:
            raise ValueError(f"{cohort_id}: target_vendor_candidates must be a positive integer")

    return {
        "schema_version": queue.get("schema_version"),
        "queue_type": queue.get("queue_type"),
        "cohort_count": len(cohorts),
        "queued_cohort_count": sum(1 for cohort in cohorts if cohort.get("status") == "queued"),
        "target_vendor_candidates": sum(int(cohort["target_vendor_candidates"]) for cohort in cohorts),
        "max_vendors_per_discovery_run": limits["max_vendors_per_discovery_run"],
        "max_candidate_sources_per_report": limits["max_candidate_sources_per_report"],
        "max_reviewed_actions_per_plan": limits["max_reviewed_actions_per_plan"],
        "source_types": source_types,
        "coverage_lane_counts": dict(sorted(lane_counts.items())),
    }


def sitemap_discovery_enabled(queue: dict[str, Any]) -> bool:
    return SITEMAP_DISCOVERY_MODE in (queue.get("discovery_modes", []) or [])


def run_sitemap_source_discovery(
    queue: dict[str, Any],
    vendors: list[dict[str, Any]],
    fetcher: Any,
    *,
    discovery_run_id: str,
    discovered_at: str,
) -> list[dict[str, Any]]:
    """Invoke bounded sitemap discovery for queued vendors when the mode is on.

    Returns normalized discovery events (each valid under the existing
    discovery-event ledger) ready for the append-only discovery lane. The events
    carry zero promotion weight; they are candidates, not evidence. A disabled
    mode yields nothing.
    """
    from tools.openva.discovery_ledger import validate_event
    from tools.openva.sitemap_discovery import discover_sitemap_candidates

    if not sitemap_discovery_enabled(queue):
        return []
    max_vendors = int((queue.get("limits", {}) or {}).get("max_vendors_per_discovery_run", len(vendors)))
    events: list[dict[str, Any]] = []
    for vendor in vendors[:max_vendors]:
        official_domains = [str(d) for d in (vendor.get("official_domains") or []) if d]
        if not official_domains:
            continue
        outcome = discover_sitemap_candidates(
            official_domains,
            fetcher,
            discovery_run_id=discovery_run_id,
            discovered_at=discovered_at,
            vendor_id=str(vendor.get("vendor_id") or "") or None,
        )
        for event in outcome.events:
            failures = validate_event(event)
            if failures:
                raise ValueError(f"sitemap discovery emitted an invalid event: {failures}")
            events.append(event)
    return events


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-growth-discovery-queue")
    parser.add_argument("command", choices={"validate"})
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summary = validate_queue(args.queue)
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
