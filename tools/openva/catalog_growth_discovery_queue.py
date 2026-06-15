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
SITEMAP_DISCOVERY_MODE = "sitemap_source_discovery"

# The four posture flags, declared per-mode and aggregated for the queue.
POSTURE_KEYS = (
    "network_fetch_performed",
    "writes_repository_state",
    "writes_canonical_sources",
    "creates_candidate_sources",
)

# Hard invariants of the discovery lane: NO mode may write repository state,
# write canonical sources, or create candidate source records. Those mutations
# happen only through the human-reviewed, PR-only promotion path. Network fetch
# is the one capability a mode may legitimately exercise.
HARD_FALSE_KEYS = (
    "writes_repository_state",
    "writes_canonical_sources",
    "creates_candidate_sources",
)

# Authoritative per-mode capability registry. This is the single source of
# truth: the queue artifact declares each enabled mode's capabilities and the
# validator confirms they match here, so the artifact cannot under-declare a
# network-fetching mode to slip it under a no-network posture. A mode that
# performs network I/O at execution MUST be marked network_fetch_performed here.
MODE_CAPABILITIES: dict[str, dict[str, bool]] = {
    # Reads a committed seed file; no network, no writes.
    "seed_file_vendor_discovery": {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "writes_canonical_sources": False,
        "creates_candidate_sources": False,
    },
    # Probes vendor source URLs over the network to build a report.
    "official_domain_source_discovery": {
        "network_fetch_performed": True,
        "writes_repository_state": False,
        "writes_canonical_sources": False,
        "creates_candidate_sources": False,
    },
    # Tier A: bounded robots/sitemap inspection on a vendor's own official
    # domain. Fetches over the network; emits zero-weight discovery events only.
    "sitemap_source_discovery": {
        "network_fetch_performed": True,
        "writes_repository_state": False,
        "writes_canonical_sources": False,
        "creates_candidate_sources": False,
    },
}
# The registry itself must respect the hard invariants.
for _mode, _caps in MODE_CAPABILITIES.items():
    assert set(_caps) == set(POSTURE_KEYS), f"{_mode} capability keys must be exactly {POSTURE_KEYS}"
    for _key in HARD_FALSE_KEYS:
        assert _caps[_key] is False, f"{_mode} may not declare {_key} true"

ALLOWED_DISCOVERY_MODES = set(MODE_CAPABILITIES)


def expected_posture(modes: list[str]) -> dict[str, bool]:
    """The queue posture implied by its enabled modes (capability union).

    A flag is true iff some enabled mode declares it; with the hard invariants
    that resolves to: network_fetch_performed mirrors the enabled modes, and the
    write/create flags are always false.
    """
    posture = {key: False for key in POSTURE_KEYS}
    for mode in modes:
        caps = MODE_CAPABILITIES[mode]
        for key in POSTURE_KEYS:
            posture[key] = posture[key] or caps[key]
    return posture


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
        if mode not in MODE_CAPABILITIES:
            raise ValueError(f"unknown discovery mode: {mode}")

    # Optional per-mode capability declarations in the artifact: an auditability
    # restatement of the authoritative code registry. When present they must
    # cover exactly the enabled modes and match the registry exactly, so the
    # artifact cannot under-declare a network-fetching mode as non-fetching.
    if "mode_capabilities" in queue:
        declared_caps = queue.get("mode_capabilities") or {}
        if set(declared_caps) != set(modes):
            raise ValueError("mode_capabilities must declare exactly the enabled discovery_modes")
        for mode in modes:
            declared = declared_caps.get(mode, {}) or {}
            registry = MODE_CAPABILITIES[mode]
            if set(declared) != set(POSTURE_KEYS):
                raise ValueError(f"mode_capabilities.{mode} must declare exactly {list(POSTURE_KEYS)}")
            for key in POSTURE_KEYS:
                if bool(declared.get(key)) is not registry[key]:
                    raise ValueError(
                        f"mode_capabilities.{mode}.{key} must be {registry[key]} (authoritative registry)"
                    )

    # Posture is the exact capability union of the enabled modes, derived from
    # the authoritative code registry (not from the artifact's own assertion).
    # This is the real enforcement: a network-fetching mode forces
    # network_fetch_performed true regardless of what the artifact declares, and
    # the write/create invariants stay false because no mode may declare them.
    posture = queue.get("posture", {}) or {}
    required_posture = expected_posture(modes)
    for key in POSTURE_KEYS:
        if posture.get(key) is not required_posture[key]:
            raise ValueError(
                f"posture.{key} must be {required_posture[key]} given the enabled discovery_modes"
            )

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
        "discovery_modes": list(modes),
        "posture": required_posture,
        "mode_capabilities": {mode: dict(MODE_CAPABILITIES[mode]) for mode in modes},
    }


def sitemap_discovery_enabled(queue: dict[str, Any]) -> bool:
    return SITEMAP_DISCOVERY_MODE in (queue.get("discovery_modes", []) or [])


def run_sitemap_source_discovery(
    queue: dict[str, Any],
    vendors: list[dict[str, Any]],
    fetcher: Any = None,
    *,
    fetcher_factory: Any = None,
    discovery_run_id: str,
    discovered_at: str,
) -> list[dict[str, Any]]:
    """Invoke bounded sitemap discovery for queued vendors when the mode is on.

    Returns normalized discovery events (each valid under the existing
    discovery-event ledger) ready for the append-only discovery lane. The events
    carry zero promotion weight; they are candidates, not evidence. A disabled
    mode yields nothing.

    Pass ``fetcher`` to use one fetcher for every vendor (tests), or
    ``fetcher_factory(official_domains) -> Fetcher`` to bind a same-authority
    fetcher per vendor (production: each vendor only fetches its own domains).
    """
    from tools.openva.discovery_ledger import validate_event
    from tools.openva.sitemap_discovery import discover_sitemap_candidates

    if not sitemap_discovery_enabled(queue):
        return []
    if fetcher is None and fetcher_factory is None:
        raise ValueError("a fetcher or fetcher_factory is required")
    max_vendors = int((queue.get("limits", {}) or {}).get("max_vendors_per_discovery_run", len(vendors)))
    events: list[dict[str, Any]] = []
    for vendor in vendors[:max_vendors]:
        official_domains = [str(d) for d in (vendor.get("official_domains") or []) if d]
        if not official_domains:
            continue
        vendor_fetcher = fetcher_factory(official_domains) if fetcher_factory is not None else fetcher
        outcome = discover_sitemap_candidates(
            official_domains,
            vendor_fetcher,
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


def load_catalog_vendors(root: Path = ROOT) -> list[dict[str, Any]]:
    """Existing catalog vendors as {vendor_id, official_domains} for discovery.

    Sitemap discovery inspects a vendor's OWN official domain(s), so the safe
    target set is vendors whose official domains are already committed/vetted.
    """
    vendors: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        domains = [str(d) for d in (vendor.get("official_domains") or []) if d]
        if not domains:
            continue
        vendors.append({"vendor_id": str(vendor.get("vendor_id") or path.parent.name), "official_domains": domains})
    return vendors


def _production_fetcher_factory() -> Any:
    """Per-vendor SafeFetcher factory bound to discovery bounds (the live path)."""
    from tools.openva.safe_fetch import build_safe_fetcher
    from tools.openva.sitemap_discovery import load_bounds

    bounds = load_bounds()

    def factory(official_domains: list[str]) -> Any:
        # Wire cap is the decompressed ceiling; decode bounds the compressed and
        # decompressed sizes more finely once the bytes are in hand.
        return build_safe_fetcher(
            official_domains,
            max_redirects=bounds.max_redirects,
            timeout_seconds=bounds.max_request_seconds,
            max_response_bytes=bounds.max_decompressed_bytes,
        ).fetch

    return factory


def run_sitemap_discovery_command(
    *,
    queue_path: Path,
    output_path: Path,
    discovery_run_id: str,
    discovered_at: str,
    root: Path = ROOT,
    vendors: list[dict[str, Any]] | None = None,
    fetcher_factory: Any = None,
) -> dict[str, Any]:
    """The scheduled-path entrypoint: run (or skip) bounded sitemap discovery.

    Always callable; it is a no-op that performs no network I/O when the
    ``sitemap_source_discovery`` mode is not enabled in the committed queue, so
    the workflow can invoke it unconditionally and the committed config decides
    whether it is active. ``fetcher_factory`` is injected by tests; production
    uses the SSRF-safe SafeFetcher bound per vendor to that vendor's domains.
    """
    validate_queue(queue_path, root)  # fail closed on an incoherent queue/posture
    queue = load_json(queue_path)
    enabled = sitemap_discovery_enabled(queue)
    events: list[dict[str, Any]] = []
    if enabled:
        if vendors is None:
            vendors = load_catalog_vendors(root)
        if fetcher_factory is None:
            fetcher_factory = _production_fetcher_factory()
        events = run_sitemap_source_discovery(
            queue,
            vendors,
            fetcher_factory=fetcher_factory,
            discovery_run_id=discovery_run_id,
            discovered_at=discovered_at,
        )
    report = {
        "report_type": "sitemap_source_discovery_events",
        "schema_version": "0.1.0",
        "mode_enabled": enabled,
        "non_advisory": True,
        "discovery_run_id": discovery_run_id,
        "discovered_at": discovered_at,
        "event_count": len(events),
        "events": events,
    }
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-growth-discovery-queue")
    parser.add_argument("command", choices={"validate", "run-sitemap-discovery"})
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--discovery-run-id")
    parser.add_argument("--discovered-at")
    args = parser.parse_args()

    if args.command == "run-sitemap-discovery":
        if not args.output or not args.discovery_run_id or not args.discovered_at:
            parser.error("run-sitemap-discovery requires --output, --discovery-run-id and --discovered-at")
        report = run_sitemap_discovery_command(
            queue_path=args.queue,
            output_path=args.output,
            discovery_run_id=args.discovery_run_id,
            discovered_at=args.discovered_at,
        )
        print(json.dumps({k: report[k] for k in ("mode_enabled", "event_count")}, indent=2, sort_keys=True))
        return 0

    summary = validate_queue(args.queue)
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
