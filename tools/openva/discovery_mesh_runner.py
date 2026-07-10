"""Sharded execution and aggregation for the OpenVA discovery mesh.

Workers emit report-only verified candidate records. The aggregate phase may stage
candidate-source YAML records for a noncanonical intake PR, after which the
existing candidate-promotion workflow remains the sole canonical mutation path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from tools.openva.discovery_mesh import (
    CrawlLimits,
    aggregate_identity_signals,
    discover_source_frontier,
    extract_relationship_identity_signals,
)
from tools.openva.source_discovery import (
    DEFAULT_SOURCE_TYPES,
    canonical_source_types_for_vendor,
    load_yaml,
    not_due_unavailable_source_types,
    parse_source_types,
    safe_discovery_fetcher,
    verify_sitemap_locators,
    vendor_paths,
    write_discovery_outputs,
)
from tools.openva.source_verification import FetchResult, ROOT

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "discovery_mesh_source_report"


def shard_for(vendor_id: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(vendor_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def selected_vendor_paths(
    *,
    root: Path = ROOT,
    shard_index: int = 0,
    shard_count: int = 1,
    vendor_limit: int | None = None,
) -> list[Path]:
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be within shard_count")
    selected = []
    for path in vendor_paths(root):
        vendor = load_yaml(path)
        vendor_id = str(vendor.get("vendor_id") or "")
        if vendor_id and shard_for(vendor_id, shard_count) == shard_index:
            selected.append(path)
    if vendor_limit is not None and vendor_limit > 0:
        selected = selected[:vendor_limit]
    return selected


def _missing_source_types(vendor_id: str, requested: tuple[str, ...], root: Path) -> tuple[str, ...]:
    present = canonical_source_types_for_vendor(vendor_id, root)
    deferred = not_due_unavailable_source_types(vendor_id, root)
    return tuple(source_type for source_type in requested if source_type not in present | deferred)


def _official_locator_urls(frontier: dict[str, Any], allowed_types: set[str]) -> list[str]:
    urls = []
    for signal in frontier.get("source_locator_signals", []) or []:
        if signal.get("authority_state") != "official_domain":
            continue
        if signal.get("source_type_candidate") not in allowed_types:
            continue
        url = str(signal.get("candidate_url") or "")
        if url:
            urls.append(url)
    return list(dict.fromkeys(urls))


def _relationship_signals(
    *,
    vendor_result: dict[str, Any],
    fetcher: Callable[[str], FetchResult],
    observed_at: str,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    urls = [
        str(candidate.get("canonical_candidate_url") or candidate.get("candidate_url") or "")
        for candidate in vendor_result.get("candidates", []) or []
        if candidate.get("source_type_candidate") == "subprocessors_list"
    ]
    output: dict[str, dict[str, Any]] = {}
    for url in list(dict.fromkeys(url for url in urls if url))[:max_pages]:
        result = fetcher(url)
        for signal in extract_relationship_identity_signals(
            source_url=url,
            result=result,
            provider="subprocessor_relationship_graph",
            observed_at=observed_at,
        ):
            output[str(signal["signal_id"])] = signal
    return sorted(output.values(), key=lambda row: str(row["signal_id"]))


def run_source_shard(
    *,
    root: Path = ROOT,
    shard_index: int = 0,
    shard_count: int = 1,
    vendor_limit: int | None = None,
    source_types: tuple[str, ...] = DEFAULT_SOURCE_TYPES,
    fetch_timeout: float = 10.0,
    limits: CrawlLimits | None = None,
    max_locators_per_vendor: int = 2_000,
    fetcher_factory: Callable[[dict[str, Any], float], Callable[[str], FetchResult]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    limits = limits or CrawlLimits()
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    fetcher_factory = fetcher_factory or (lambda vendor, timeout: safe_discovery_fetcher(vendor, timeout))
    vendor_results: list[dict[str, Any]] = []
    frontier_reports: list[dict[str, Any]] = []
    identity_signals: list[dict[str, Any]] = []

    for path in selected_vendor_paths(
        root=root,
        shard_index=shard_index,
        shard_count=shard_count,
        vendor_limit=vendor_limit,
    ):
        vendor = load_yaml(path)
        vendor_id = str(vendor["vendor_id"])
        missing_types = _missing_source_types(vendor_id, source_types, root)
        if not missing_types:
            continue
        fetcher = fetcher_factory(vendor, fetch_timeout)
        frontier = discover_source_frontier(
            vendor,
            fetcher,
            limits=limits,
            discovered_at=generated_at,
        )
        locator_urls = _official_locator_urls(frontier, set(missing_types))
        verified = verify_sitemap_locators(
            vendor,
            locator_urls,
            fetcher=fetcher,
            source_types=missing_types,
            discovered_at=generated_at,
            discovery_run_id=f"mesh-{shard_index}-{vendor_id}-{generated_at}",
            max_locators=max_locators_per_vendor,
        )
        verified["mesh_summary"] = frontier.get("summary") or {}
        verified["delegated_locator_signals"] = [
            row
            for row in frontier.get("source_locator_signals", []) or []
            if row.get("authority_state") == "first_party_attested_delegate"
        ]
        vendor_results.append(verified)
        frontier_reports.append(frontier)
        identity_signals.extend(
            _relationship_signals(
                vendor_result=verified,
                fetcher=fetcher,
                observed_at=generated_at,
            )
        )

    candidates = sum(len(row.get("candidates", []) or []) for row in vendor_results)
    delegated = sum(len(row.get("delegated_locator_signals", []) or []) for row in vendor_results)
    pages = sum(int((row.get("summary") or {}).get("pages_attempted", 0)) for row in frontier_reports)
    requests = sum(int((row.get("summary") or {}).get("requests", 0)) for row in frontier_reports)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "report_type": REPORT_TYPE,
        "shard": {"index": shard_index, "count": shard_count},
        "posture": {
            "network_fetch_performed": True,
            "writes_repository_state": False,
            "writes_canonical_sources": False,
            "public_sources_only": True,
            "delegated_candidates_are_unverified": True,
            "non_advisory": True,
        },
        "summary": {
            "vendors_checked": len(vendor_results),
            "candidate_sources_written_or_reported": candidates,
            "unavailable_sources_written_or_reported": 0,
            "pages_attempted": pages,
            "requests": requests,
            "delegated_locator_signal_count": delegated,
            "vendor_identity_signal_count": len(identity_signals),
        },
        "vendors": vendor_results,
        "source_frontier_reports": frontier_reports,
        "vendor_identity_signals": identity_signals,
    }


def _known_vendor_identity(root: Path) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    domains: set[str] = set()
    for path in vendor_paths(root):
        vendor = load_yaml(path)
        vendor_id = str(vendor.get("vendor_id") or "")
        if vendor_id:
            ids.add(vendor_id)
        for domain in vendor.get("official_domains", []) or []:
            clean = str(domain).lower().removeprefix("www.")
            if clean:
                domains.add(clean)
    return ids, domains


def aggregate_shard_reports(
    reports: list[dict[str, Any]],
    *,
    root: Path = ROOT,
    write_candidates: bool = False,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    vendors: list[dict[str, Any]] = []
    frontiers: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    seen_candidates: set[str] = set()
    manifest_paths: list[str] = []

    for report in reports:
        frontiers.extend(report.get("source_frontier_reports", []) or [])
        signals.extend(report.get("vendor_identity_signals", []) or [])
        for vendor in report.get("vendors", []) or []:
            unique_candidates = []
            for candidate in vendor.get("candidates", []) or []:
                candidate_id = str(candidate.get("candidate_source_id") or "")
                if not candidate_id or candidate_id in seen_candidates:
                    continue
                seen_candidates.add(candidate_id)
                unique_candidates.append(candidate)
            merged_vendor = {**vendor, "candidates": unique_candidates}
            vendors.append(merged_vendor)
            if write_candidates and unique_candidates:
                write_discovery_outputs(
                    {
                        "vendor_id": str(vendor["vendor_id"]),
                        "candidates": unique_candidates,
                        "unavailable_sources": [],
                    },
                    root=root,
                )
                for candidate in unique_candidates:
                    manifest_paths.append(
                        (root / "data" / "vendors" / str(vendor["vendor_id"]) / "candidate_sources" / f"{candidate['candidate_source_id']}.yaml").relative_to(root).as_posix()
                    )

    vendors.sort(key=lambda row: str(row.get("vendor_id") or ""))
    known_ids, known_domains = _known_vendor_identity(root)
    identity_report = aggregate_identity_signals(
        signals,
        known_vendor_ids=known_ids,
        known_domains=known_domains,
    )
    source_report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "report_type": "source_discovery_report",
        "discovery_context": "discovery_mesh",
        "posture": {
            "network_fetch_performed": True,
            "writes_repository_state": write_candidates,
            "writes_canonical_sources": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
        },
        "summary": {
            "vendors_checked": len(vendors),
            "candidate_sources_written_or_reported": sum(len(row.get("candidates", []) or []) for row in vendors),
            "unavailable_sources_written_or_reported": 0,
            "source_frontier_report_count": len(frontiers),
            "vendor_identity_signal_count": len(signals),
        },
        "vendors": vendors,
        "source_frontier_reports": frontiers,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "candidate_source_ids": sorted(seen_candidates),
        "candidate_paths": sorted(set(manifest_paths)),
        "candidate_count": len(seen_candidates),
        "not_advice": True,
    }
    return source_report, identity_report, manifest


def load_reports(input_dir: Path) -> list[dict[str, Any]]:
    reports = []
    for path in sorted(input_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("report_type") == REPORT_TYPE:
            reports.append(data)
    if not reports:
        raise ValueError(f"no {REPORT_TYPE} files found under {input_dir}")
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-mesh-runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    shard = subparsers.add_parser("shard")
    shard.add_argument("--shard-index", type=int, required=True)
    shard.add_argument("--shard-count", type=int, required=True)
    shard.add_argument("--vendor-limit", type=int)
    shard.add_argument("--source-types")
    shard.add_argument("--fetch-timeout", type=float, default=10.0)
    shard.add_argument("--max-pages", type=int, default=500)
    shard.add_argument("--max-total-requests", type=int, default=750)
    shard.add_argument("--max-links-per-page", type=int, default=750)
    shard.add_argument("--max-locators-per-vendor", type=int, default=2_000)
    shard.add_argument("--output", type=Path, required=True)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--input-dir", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    aggregate.add_argument("--identity-output", type=Path, required=True)
    aggregate.add_argument("--manifest-output", type=Path, required=True)
    aggregate.add_argument("--write-candidates", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "shard":
        limits = CrawlLimits(
            max_pages=args.max_pages,
            max_total_requests=args.max_total_requests,
            max_links_per_page=args.max_links_per_page,
            max_locator_candidates=args.max_locators_per_vendor,
        )
        report = run_source_shard(
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            vendor_limit=args.vendor_limit,
            source_types=parse_source_types(args.source_types),
            fetch_timeout=args.fetch_timeout,
            limits=limits,
            max_locators_per_vendor=args.max_locators_per_vendor,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0

    source_report, identity_report, manifest = aggregate_shard_reports(
        load_reports(args.input_dir),
        write_candidates=args.write_candidates,
    )
    for path, payload in (
        (args.output, source_report),
        (args.identity_output, identity_report),
        (args.manifest_output, manifest),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(source_report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
