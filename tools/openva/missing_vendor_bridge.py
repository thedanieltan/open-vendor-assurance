"""WP36 queue-bound missing_vendor -> candidate bridge.

Turns coverage-growth `missing_vendor` queue rows into vendor-candidate records
that feed the EXISTING strict-growth chain (source_discovery -> eligibility ->
promotion_planner -> candidate_promotion_actions materializer). It does not
write catalog state; it emits a candidate artifact in the same shape
vendor_candidate_discovery produces, so the rest of the pipeline is unchanged.

The official domain + headquarters country come from the curated wishlist in
config/coverage-targets.yaml (priority_vendors). Rows whose wishlist entry lacks
a domain or country are skipped (fail closed); discovery still verifies the
domain serves a public assurance source downstream. A row is materialized only
if it is still genuinely missing: no collision on vendor_id, official domain
(including previous_domains), or display name/alias.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.catalog_growth_eligibility import (
    current_vendor_identity,
    known_vendor_names,
    normalize_domain,
    normalize_name,
)
from tools.openva.indexes import ROOT

DEFAULT_TARGETS = ROOT / "config" / "coverage-targets.yaml"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def load_targets(path: Path = DEFAULT_TARGETS) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected coverage-targets mapping")
    return data


def wishlist_map(targets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for category, spec in (targets.get("categories") or {}).items():
        tags = list(spec.get("taxonomy_tags") or [])
        for entry in spec.get("priority_vendors") or []:
            vendor_id = str(entry.get("vendor_id") or "")
            if vendor_id and vendor_id not in result:
                result[vendor_id] = {
                    "name": entry.get("name"),
                    "domain": entry.get("domain"),
                    "country": entry.get("country"),
                    "category": category,
                    "taxonomy_tags": tags,
                }
    return result


def build_bridge_report(
    coverage_report: dict[str, Any],
    targets: dict[str, Any],
    root: Path = ROOT,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    wishlist = wishlist_map(targets)
    known_ids, known_domains = current_vendor_identity(root)
    known_names = known_vendor_names(root)

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in coverage_report.get("growth_queue", []) or []:
        if row.get("queue_class") != "missing_vendor":
            continue
        vendor_id = str(row.get("vendor_id") or "")
        if not vendor_id or vendor_id in seen:
            continue
        seen.add(vendor_id)

        entry = wishlist.get(vendor_id)
        if not entry:
            skipped.append({"vendor_id": vendor_id, "reason": "not_in_wishlist"})
            continue
        domain = str(entry.get("domain") or "").strip()
        country = str(entry.get("country") or "").strip()
        if not domain or not country:
            skipped.append({"vendor_id": vendor_id, "reason": "wishlist_missing_domain_or_country"})
            continue

        collisions: list[str] = []
        if vendor_id in known_ids:
            collisions.append("vendor_id")
        if normalize_domain(domain) in known_domains:
            collisions.append("official_domain")
        if normalize_name(entry.get("name")) in known_names:
            collisions.append("name_or_alias")
        if collisions:
            skipped.append({"vendor_id": vendor_id, "reason": "already_in_catalog", "collisions": collisions})
            continue

        clean_domain = domain.lower().removeprefix("www.")
        candidates.append({
            "candidate_vendor_id": vendor_id,
            "display_name_candidate": str(entry.get("name") or vendor_id)[:120],
            "official_domain_candidate": clean_domain,
            "coverage_lane": str(entry["category"]),
            "cohort_id": f"{entry['category']}-missing-vendor",
            "discovery_method": "coverage_growth_missing_vendor_bridge",
            "source_index_url": f"https://{clean_domain}",
            "requires_review": True,
            "writes_canonical_vendors": False,
            "non_advisory": True,
            "vendor_category_candidates": list(entry.get("taxonomy_tags") or []),
            "headquarters_country_candidate": country,
        })

    return {
        "schema_version": "0.1.0",
        "generated_at": generated_at,
        "report_type": "vendor_candidate_discovery_report",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "candidate_vendor_count": len(candidates),
            "skipped_count": len(skipped),
        },
        "vendor_candidates": sorted(candidates, key=lambda c: (c["coverage_lane"], c["candidate_vendor_id"])),
        "bridge_skipped": skipped,
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-missing-vendor-bridge")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--coverage-report", type=Path, required=True)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--output", type=Path, default=ROOT / "missing-vendor-bridge-report.json")
    args = parser.parse_args(argv)

    report = build_bridge_report(load_json(args.coverage_report), load_targets(args.targets))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
