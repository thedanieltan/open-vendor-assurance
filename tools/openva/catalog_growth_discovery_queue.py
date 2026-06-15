from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timezone
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


# A bounded rejection reason code: a lowercase token, optionally one ``:``
# followed by a bounded token (status int, exception class, robots reason, or
# resolved address). Anything with whitespace, punctuation or free text — i.e.
# any raw page/robots snippet — fails this and is mapped to a generic code, so
# the no-leak property is structural rather than incidental.
_SAFE_REASON_RE = re.compile(r"^[a-z][a-z0-9_]*(?::[A-Za-z0-9_.]+)?$")


def _normalize_reason(reason: str) -> str:
    """A bounded rejection reason code with no raw page/parse detail."""
    reason = str(reason or "")
    if reason.startswith("malformed_sitemap_xml"):
        return "malformed_sitemap_xml"  # drop the ParseError positional/detail tail
    if len(reason) <= 80 and _SAFE_REASON_RE.match(reason):
        return reason
    return "rejected_other"


def _bounded_reason_codes(rejected: list[dict[str, Any]], *, limit: int = 20) -> list[str]:
    return sorted({_normalize_reason(r.get("reason", "")) for r in rejected if r.get("reason")})[:limit]


def run_sitemap_source_discovery(
    queue: dict[str, Any],
    vendors: list[dict[str, Any]],
    fetcher: Any = None,
    *,
    fetcher_factory: Any = None,
    discovery_run_id: str,
    discovered_at: str,
) -> list[dict[str, Any]]:
    """Run bounded sitemap discovery for the GIVEN vendors when the mode is on.

    Returns one structured record per vendor — robots access state, the robots
    parser id, sitemaps attempted, the zero-weight discovery events, the
    discovered locator URLs, and bounded rejection reason codes — so the
    scheduled command can both surface per-vendor execution metadata and feed the
    locators into ordinary candidate verification. Events carry zero promotion
    weight; they are candidates, not evidence. A disabled mode yields nothing.
    Vendor selection/bounding is the caller's responsibility (see
    ``select_rotation_vendors``); this processes exactly the vendors it is given.

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
    records: list[dict[str, Any]] = []
    for vendor in vendors:
        official_domains = [str(d) for d in (vendor.get("official_domains") or []) if d]
        if not official_domains:
            continue
        vendor_fetcher = fetcher_factory(official_domains) if fetcher_factory is not None else fetcher
        vendor_id = str(vendor.get("vendor_id") or "")
        outcome = discover_sitemap_candidates(
            official_domains,
            vendor_fetcher,
            discovery_run_id=discovery_run_id,
            discovered_at=discovered_at,
            vendor_id=vendor_id or None,
        )
        for event in outcome.events:
            failures = validate_event(event)
            if failures:
                raise ValueError(f"sitemap discovery emitted an invalid event: {failures}")
        records.append(
            {
                "vendor_id": vendor_id,
                "official_domain": official_domains[0],
                "robots_state": outcome.robots_state,
                "robots_reason": outcome.robots_reason,
                "robots_parser": outcome.robots_parser,
                "sitemaps_attempted": outcome.sitemaps_attempted,
                "candidate_count": len(outcome.candidates),
                "rejected_count": len(outcome.rejected),
                "rejection_reason_codes": _bounded_reason_codes(outcome.rejected),
                "locators": [c["url"] for c in outcome.candidates],
                "events": list(outcome.events),
            }
        )
    return records


# --- deterministic vendor rotation (item 4) ----------------------------------


def _parse_discovered_at(discovered_at: str) -> datetime:
    text = str(discovered_at or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            continue
    raise ValueError(f"unrecognized discovered_at: {discovered_at!r}")


# A fixed Monday reference (ISO week 1 of 2024 begins Mon 2024-01-01). The cursor
# counts whole weeks from this epoch, which is CONTIGUOUS across year boundaries —
# unlike isocalendar()[1], whose W52/W53 -> W01 wrap would re-run or skip a shard.
_ROTATION_EPOCH = date(2024, 1, 1)


def rotation_shard_count(vendor_count: int, max_vendors: int) -> int:
    """How many cycles a full rotation takes: ceil(vendors / per-run bound)."""
    if vendor_count <= 0 or max_vendors <= 0:
        return 1
    return max(1, math.ceil(vendor_count / max_vendors))


def epoch_week_index(discovered_at: str) -> int:
    """Contiguous week counter from the fixed Monday epoch (no year-seam gap)."""
    dt = _parse_discovered_at(discovered_at)
    iso_year, iso_week, _iso_day = dt.isocalendar()
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    return (monday - _ROTATION_EPOCH).days // 7


def rotation_cursor_index(discovered_at: str, shard_count: int) -> int:
    """Derived rotation cursor: contiguous epoch week modulo shard_count.

    Derived (not committed) so the scheduled lane mutates no repository state
    (PR-only posture) and a rerun of the same logical cycle selects the same
    vendors — the key is the calendar week, never the run id (which changes on
    rerun). Using a contiguous epoch-week counter guarantees that exactly
    ``shard_count`` consecutive cycles cover every shard with no year-seam
    discontinuity (no shard runs twice in a row and none is skipped at New Year).
    """
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    return epoch_week_index(discovered_at) % shard_count


def select_rotation_vendors(
    vendors: list[dict[str, Any]], *, max_vendors: int, discovered_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bounded deterministic epoch-week stride rotation over the sorted catalog.

    Each scheduled cycle selects one stride of the (already path-sorted) vendor
    list; over ``shard_count`` consecutive cycles every vendor is covered, while
    any single run stays bounded by ``max_vendors``. Stride membership
    (``offset % shard_count``) keeps each vendor's assignment stable except when
    ``shard_count`` itself changes (the catalog grows past a ``max_vendors``
    multiple), so adding one vendor within a band does not reshuffle the schedule;
    ``shard_count`` is recorded so a consumer can detect a band transition.
    """
    shard_count = rotation_shard_count(len(vendors), max_vendors)
    shard_index = rotation_cursor_index(discovered_at, shard_count)
    sharded = [vendor for offset, vendor in enumerate(vendors) if offset % shard_count == shard_index]
    selected = sharded[:max_vendors]
    parsed = _parse_discovered_at(discovered_at)
    meta = {
        "shard_index": shard_index,
        "shard_count": shard_count,
        "cursor_week": epoch_week_index(discovered_at),
        "iso_week": parsed.isocalendar()[1],
        "eligible_vendor_count": len(vendors),
        "selected_vendor_ids": [str(vendor.get("vendor_id") or "") for vendor in selected],
    }
    return selected, meta


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
        # Distinct wire caps: gzip bodies are bounded by the compressed ceiling
        # while streaming, identity bodies by the decompressed ceiling; the whole
        # exchange is bounded by max_request_seconds.
        return build_safe_fetcher(
            official_domains,
            max_redirects=bounds.max_redirects,
            timeout_seconds=bounds.max_request_seconds,
            max_compressed_bytes=bounds.max_compressed_bytes,
            max_decompressed_bytes=bounds.max_decompressed_bytes,
        ).fetch

    return factory


def _production_verify_fetcher_factory() -> Any:
    """Ordinary candidate-verification fetcher used to fetch+classify locators."""
    from tools.openva.source_verification import fetch_url

    def factory(_official_domain: str) -> Any:
        return fetch_url

    return factory


def _provisional_eligibility(vendor: dict[str, Any], verification: dict[str, Any]) -> str:
    """Run the EXISTING eligibility classifier on verified locator candidates.

    Returns a PROVISIONAL outcome label (strict_promote_ready / review_required /
    reject_*) describing source quality only. It is report-only: the full
    pipeline additionally applies catalog-identity gates (these are existing
    vendors) and, before any catalog write, materialization independence
    (distinct runs/modes) and the reviewed quorum. A single-run sitemap locator
    therefore carries zero promotion weight regardless of this label. Statuses
    are derived from ALL observations (not just matched candidates), so an
    access-ambiguous/unreachable probe still surfaces here.
    """
    from tools.openva.catalog_growth_eligibility import classify

    sources = verification.get("candidates", []) or []
    statuses = {
        str(observation.get("verification_status") or "")
        for observation in verification.get("observations", []) or []
    }
    classification, _reasons, _strict, _rejections = classify(vendor, sources, statuses, [])
    return classification


def run_sitemap_discovery_command(
    *,
    queue_path: Path,
    output_path: Path,
    discovery_run_id: str,
    discovered_at: str,
    root: Path = ROOT,
    vendors: list[dict[str, Any]] | None = None,
    fetcher_factory: Any = None,
    verify_fetcher_factory: Any = None,
) -> dict[str, Any]:
    """The scheduled-path entrypoint: run (or skip) bounded sitemap discovery.

    Always callable; it is a no-op that performs no network I/O when the
    ``sitemap_source_discovery`` mode is not enabled in the committed queue, so
    the workflow can invoke it unconditionally and the committed config decides
    whether it is active.

    When enabled it (1) selects a bounded, deterministic ISO-week vendor shard so
    successive cycles cover the whole catalog without starving any vendor;
    (2) runs bounded sitemap discovery per vendor via the SSRF-safe SafeFetcher;
    (3) feeds each discovered locator through ORDINARY candidate verification
    (``verify_sitemap_locators``) and the EXISTING eligibility classifier, so a
    locator becomes an eligible/deferred/rejected candidate without any new
    mutation path and with zero promotion weight; and (4) records per-vendor
    execution + rejection metadata and the rotation cursor in the report.
    ``fetcher_factory`` / ``verify_fetcher_factory`` are injected by tests.
    """
    from tools.openva.robots_policy import PARSER_ID as ROBOTS_PARSER_ID
    from tools.openva.source_discovery import verify_sitemap_locators

    validate_queue(queue_path, root)  # fail closed on an incoherent queue/posture
    queue = load_json(queue_path)
    enabled = sitemap_discovery_enabled(queue)

    rotation: dict[str, Any] = {
        "shard_index": None,
        "shard_count": None,
        "cursor_week": None,
        "iso_week": None,
        "eligible_vendor_count": 0,
        "selected_vendor_ids": [],
    }
    events: list[dict[str, Any]] = []
    per_vendor: list[dict[str, Any]] = []
    verified_vendor_results: list[dict[str, Any]] = []
    outcome_counts: Counter[str] = Counter()
    robots_parser = ""

    if enabled:
        if vendors is None:
            vendors = load_catalog_vendors(root)
        if fetcher_factory is None:
            fetcher_factory = _production_fetcher_factory()
        if verify_fetcher_factory is None:
            verify_fetcher_factory = _production_verify_fetcher_factory()
        max_vendors = int((queue.get("limits", {}) or {}).get("max_vendors_per_discovery_run", 0)) or len(vendors)
        selected, rotation = select_rotation_vendors(
            vendors, max_vendors=max_vendors, discovered_at=discovered_at
        )
        records = run_sitemap_source_discovery(
            queue,
            selected,
            fetcher_factory=fetcher_factory,
            discovery_run_id=discovery_run_id,
            discovered_at=discovered_at,
        )
        for record in records:
            events.extend(record["events"])
            robots_parser = robots_parser or record["robots_parser"]
            verified_count = 0
            provisional_eligibility: str | None = None
            if record["locators"]:
                vendor = {
                    "vendor_id": record["vendor_id"],
                    "candidate_vendor_id": record["vendor_id"],
                    "official_domains": [record["official_domain"]],
                    "official_domain_candidate": record["official_domain"],
                }
                verification = verify_sitemap_locators(
                    vendor,
                    record["locators"],
                    fetcher=verify_fetcher_factory(record["official_domain"]),
                    discovered_at=discovered_at,
                    discovery_run_id=f"{discovery_run_id}-{record['vendor_id']}",
                )
                verified_count = len(verification["candidates"])
                provisional_eligibility = _provisional_eligibility(vendor, verification)
                outcome_counts[provisional_eligibility] += 1
                verified_vendor_results.append(
                    {
                        "vendor_id": record["vendor_id"],
                        "candidates": verification["candidates"],
                        "unavailable_sources": [],
                        "observations": verification["observations"],
                        # These verification events are report-only provenance and
                        # are NOT appended to the committed discovery-ledger lane.
                        "discovery_events": verification["discovery_events"],
                    }
                )
            # Per-vendor execution + rejection metadata (item 5): identifiers and
            # bounded codes only — never raw robots text, page content or snippets.
            per_vendor.append(
                {
                    "vendor_id": record["vendor_id"],
                    "official_domain": record["official_domain"],
                    "robots_parser": record["robots_parser"],
                    "robots_state": record["robots_state"],
                    "robots_reason": record["robots_reason"],
                    "sitemaps_attempted": record["sitemaps_attempted"],
                    "candidate_count": record["candidate_count"],
                    "rejected_count": record["rejected_count"],
                    "rejection_reason_codes": record["rejection_reason_codes"],
                    "verified_candidate_count": verified_count,
                    "provisional_eligibility": provisional_eligibility,
                }
            )

    report = {
        "report_type": "sitemap_source_discovery_events",
        "schema_version": "0.1.0",
        "mode_enabled": enabled,
        "non_advisory": True,
        "discovery_run_id": discovery_run_id,
        "discovered_at": discovered_at,
        # Demonstrates the corrected robots evaluator was actually used.
        "robots_parser": robots_parser or ROBOTS_PARSER_ID,
        "rotation": rotation,
        "event_count": len(events),
        "events": events,
        "per_vendor": per_vendor,
        "verification": {
            "verified_candidate_count": sum(v["verified_candidate_count"] for v in per_vendor),
            # Provisional: source-quality only. Catalog-identity gates and (before
            # any catalog write) materialization independence + the reviewed
            # quorum are applied downstream, not here.
            "provisional_eligibility_outcomes": dict(sorted(outcome_counts.items())),
            "vendors": verified_vendor_results,
        },
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
