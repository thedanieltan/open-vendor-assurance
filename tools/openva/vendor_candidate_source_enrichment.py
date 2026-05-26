from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from tools.openva.source_discovery import DEFAULT_SOURCE_TYPES, discover_for_vendor
from tools.openva.source_verification import FetchResult, ROOT

SCHEMA_VERSION = "0.1.0"
DISCOVERY_CONTEXT = "vendor_candidate_source_enrichment"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def candidate_to_vendor(candidate: dict[str, Any]) -> dict[str, Any]:
    vendor_id = str(candidate.get("candidate_vendor_id") or "")
    domain = str(candidate.get("official_domain_candidate") or "").strip().lower().removeprefix("www.")
    entrypoint = str(candidate.get("source_index_url") or f"https://{domain}")
    return {
        "vendor_id": vendor_id,
        "display_name": candidate.get("display_name_candidate"),
        "official_domains": [domain] if domain else [],
        "public_entrypoints": [entrypoint] if entrypoint else [],
    }


def valid_candidate(candidate: dict[str, Any]) -> bool:
    return bool(candidate.get("candidate_vendor_id") and candidate.get("official_domain_candidate"))


def build_enrichment_report(
    vendor_candidate_report: dict[str, Any],
    root: Path = ROOT,
    fetcher: Callable[[str], FetchResult] | None = None,
    vendor_limit: int | None = None,
    max_urls_per_type: int = 20,
    source_types: tuple[str, ...] = DEFAULT_SOURCE_TYPES,
) -> dict[str, Any]:
    if vendor_candidate_report.get("report_type") != "vendor_candidate_discovery_report":
        raise ValueError("expected vendor_candidate_discovery_report")
    candidates = [
        item for item in vendor_candidate_report.get("vendor_candidates", []) or []
        if isinstance(item, dict) and valid_candidate(item)
    ]
    if vendor_limit is not None:
        candidates = candidates[:vendor_limit]

    vendor_results: list[dict[str, Any]] = []
    for candidate in candidates:
        discovery = discover_for_vendor(
            candidate_to_vendor(candidate),
            root=root,
            fetcher=fetcher if fetcher is not None else __import__("tools.openva.source_verification", fromlist=["fetch_url"]).fetch_url,
            source_types=source_types,
            max_urls_per_type=max_urls_per_type,
        )
        discovery["candidate_vendor_id"] = candidate.get("candidate_vendor_id")
        discovery["display_name_candidate"] = candidate.get("display_name_candidate")
        discovery["official_domain_candidate"] = candidate.get("official_domain_candidate")
        discovery["coverage_lane"] = candidate.get("coverage_lane")
        discovery["cohort_id"] = candidate.get("cohort_id")
        vendor_results.append(discovery)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "report_type": "source_discovery_report",
        "discovery_context": DISCOVERY_CONTEXT,
        "posture": {
            "network_fetch_performed": True,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
        },
        "summary": {
            "vendor_candidates_checked": len(vendor_results),
            "candidate_sources_written_or_reported": sum(len(item["candidates"]) for item in vendor_results),
            "unavailable_sources_written_or_reported": sum(len(item["unavailable_sources"]) for item in vendor_results),
        },
        "vendors": vendor_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-vendor-candidate-source-enrichment")
    parser.add_argument("command", choices={"enrich"})
    parser.add_argument("--vendor-candidates", type=Path, required=True)
    parser.add_argument("--vendor-limit", type=int)
    parser.add_argument("--max-urls-per-type", type=int, default=20)
    parser.add_argument("--output", type=Path, default=ROOT / "vendor-candidate-source-enrichment-report.json")
    args = parser.parse_args()
    report = build_enrichment_report(
        load_json(args.vendor_candidates),
        vendor_limit=args.vendor_limit,
        max_urls_per_type=args.max_urls_per_type,
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
