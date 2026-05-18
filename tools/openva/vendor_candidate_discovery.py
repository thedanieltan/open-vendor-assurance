from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from tools.openva.catalog_growth_discovery_queue import QUEUE_PATH, load_json, validate_queue
from tools.openva.source_verification import FetchResult, ROOT, fetch_url, title_from_sample

INDEX_HINTS = {
    "cloud_platforms": ["cloud", "platform", "infrastructure"],
    "crm_customer_marketing": ["crm", "customer", "marketing"],
    "payments_fintech": ["payments", "fintech", "billing"],
    "security_identity": ["security", "identity", "access"],
    "data_ai": ["data", "ai", "analytics"],
    "devtools_ops": ["developer", "devops", "operations"],
    "productivity_collaboration": ["productivity", "collaboration", "workspace"],
    "hr_education": ["hr", "learning", "education"],
    "commerce_content_docs": ["commerce", "content", "cms"],
    "grc_privacy_trust": ["grc", "privacy", "trust"],
    "kyc_risk": ["kyc", "risk", "compliance"],
    "regional_apac": ["apac", "asia", "singapore"],
}


def known_vendor_ids(root: Path = ROOT) -> set[str]:
    return {path.parent.name for path in (root / "data" / "vendors").glob("*/vendor.yaml")}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "unknown"


def candidate_from_url(url: str, coverage_lane: str, cohort_id: str, source_url: str, title: str | None) -> dict[str, Any] | None:
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    domain = parsed.netloc.lower().removeprefix("www.")
    vendor_id = slugify(domain.split(":")[0].split(".")[0])
    display_name = title or domain
    return {
        "candidate_vendor_id": vendor_id,
        "display_name_candidate": display_name[:120],
        "official_domain_candidate": domain,
        "coverage_lane": coverage_lane,
        "cohort_id": cohort_id,
        "discovery_method": "public_index_vendor_discovery",
        "source_index_url": source_url,
        "requires_review": True,
        "writes_canonical_vendors": False,
        "non_advisory": True,
    }


def extract_links(body: str | bytes) -> list[str]:
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="ignore")
    return re.findall(r"https?://[^\s\"'<>]+", body or "")


def discover_for_cohort(cohort: dict[str, Any], fetcher: Callable[[str], FetchResult] = fetch_url) -> list[dict[str, Any]]:
    lane = str(cohort["coverage_lane"])
    hints = INDEX_HINTS.get(lane, [lane.replace("_", " ")])
    candidates: list[dict[str, Any]] = []
    for hint in hints:
        url = f"https://www.google.com/search?q={hint.replace(' ', '+')}+software+vendor"
        result = fetcher(url)
        title = title_from_sample(result.body_sample, result.content_type)
        for link in extract_links(result.body_sample)[:20]:
            candidate = candidate_from_url(link, lane, str(cohort["cohort_id"]), url, title)
            if candidate:
                candidates.append(candidate)
    return candidates


def build_vendor_candidate_report(
    queue_path: Path = QUEUE_PATH,
    root: Path = ROOT,
    fetcher: Callable[[str], FetchResult] = fetch_url,
) -> dict[str, Any]:
    validate_queue(queue_path, root)
    queue = load_json(queue_path)
    known = known_vendor_ids(root)
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for cohort in queue.get("cohorts", []) or []:
        if cohort.get("status") != "queued":
            continue
        for candidate in discover_for_cohort(cohort, fetcher=fetcher):
            vendor_id = candidate["candidate_vendor_id"]
            if vendor_id in known or vendor_id in seen:
                continue
            seen.add(vendor_id)
            candidates.append(candidate)
            if len(candidates) >= queue["limits"]["target_vendor_candidates"]:
                break
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "vendor_candidate_discovery_report",
        "posture": {
            "network_fetch_performed": True,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "candidate_vendor_count": len(candidates),
            "known_vendor_count": len(known),
        },
        "vendor_candidates": sorted(candidates, key=lambda item: (item["coverage_lane"], item["candidate_vendor_id"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-vendor-candidate-discovery")
    parser.add_argument("command", choices={"discover"})
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "vendor-candidate-discovery-report.json")
    args = parser.parse_args()
    report = build_vendor_candidate_report(queue_path=args.queue)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
