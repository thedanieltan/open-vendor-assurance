from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.catalog_growth_discovery_queue import QUEUE_PATH, load_json, validate_queue
from tools.openva.source_verification import ROOT

SEED_DIR = ROOT / "maintenance" / "seeds" / "vendors"
VENDOR_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
DOMAIN_PATTERN = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")


def known_vendor_ids(root: Path = ROOT) -> set[str]:
    return {path.parent.name for path in (root / "data" / "vendors").glob("*/vendor.yaml")}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "unknown"


def load_seed_file(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        data = data.get("vendors", [])
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list or vendors mapping")
    seeds: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: seed entries must be mappings")
        seeds.append(item)
    return seeds


def seed_paths_for_lane(coverage_lane: str, root: Path = ROOT) -> list[Path]:
    seed_dir = root / "maintenance" / "seeds" / "vendors"
    return sorted(
        path
        for path in (
            seed_dir / f"{coverage_lane}.yaml",
            seed_dir / f"{coverage_lane}.yml",
        )
        if path.exists()
    )


def all_seed_paths(root: Path = ROOT) -> list[Path]:
    seed_dir = root / "maintenance" / "seeds" / "vendors"
    return sorted([*seed_dir.glob("*.yaml"), *seed_dir.glob("*.yml")])


def taxonomy_vendor_category_tags(root: Path = ROOT) -> set[str]:
    taxonomy = yaml.safe_load((root / "config" / "category-taxonomy.yaml").read_text(encoding="utf-8")) or {}
    return set((taxonomy.get("vendor_categories") or {}).keys())


def taxonomy_coverage_lanes(root: Path = ROOT) -> set[str]:
    taxonomy = yaml.safe_load((root / "config" / "category-taxonomy.yaml").read_text(encoding="utf-8")) or {}
    return set((taxonomy.get("coverage_lanes") or {}).keys())


def validate_seed_identities(root: Path = ROOT) -> dict[str, Any]:
    failures: list[str] = []
    seen_ids: dict[str, str] = {}
    seen_domains: dict[str, str] = {}
    category_tags = taxonomy_vendor_category_tags(root)
    lanes = taxonomy_coverage_lanes(root)
    lane_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    missing_country_count = 0
    seed_count = 0

    for path in all_seed_paths(root):
        default_lane = path.stem
        for index, seed in enumerate(load_seed_file(path), start=1):
            seed_count += 1
            location = f"{path}:{index}"
            vendor_id = str(seed.get("candidate_vendor_id") or "")
            domain = str(seed.get("official_domain_candidate") or "").lower().removeprefix("www.")
            lane = str(seed.get("coverage_lane") or default_lane)
            categories = seed.get("vendor_category_candidates") or []
            country = seed.get("headquarters_country_candidate")

            if not VENDOR_ID_PATTERN.fullmatch(vendor_id):
                failures.append(f"{location}: candidate_vendor_id {vendor_id!r} must be a canonical slug")
            elif vendor_id in seen_ids:
                failures.append(f"{location}: duplicate candidate_vendor_id also used by {seen_ids[vendor_id]}")
            else:
                seen_ids[vendor_id] = location

            if not DOMAIN_PATTERN.fullmatch(domain):
                failures.append(f"{location}: official_domain_candidate {domain!r} must be a domain")
            elif domain in seen_domains:
                failures.append(f"{location}: duplicate official_domain_candidate also used by {seen_domains[domain]}")
            else:
                seen_domains[domain] = location

            if lane not in lanes:
                failures.append(f"{location}: coverage_lane {lane!r} is not defined in config/category-taxonomy.yaml")
            lane_counts[lane] += 1

            if not isinstance(categories, list) or not categories:
                failures.append(f"{location}: vendor_category_candidates must be a non-empty list")
            else:
                for category in categories:
                    if category not in category_tags:
                        failures.append(
                            f"{location}: vendor_category_candidates tag {category!r} is "
                            "not defined in config/category-taxonomy.yaml"
                        )

            if country in (None, ""):
                missing_country_count += 1
            elif not isinstance(country, str) or not COUNTRY_PATTERN.fullmatch(country):
                failures.append(
                    f"{location}: headquarters_country_candidate {country!r} must be "
                    "ISO-3166 alpha-2 uppercase when present"
                )
            else:
                country_counts[country] += 1

            for key, expected in {
                "requires_review": True,
                "writes_canonical_vendors": False,
                "non_advisory": True,
            }.items():
                if seed.get(key) is not expected:
                    failures.append(f"{location}: {key} must be {expected}")

    return {
        "schema_version": "0.1.0",
        "seed_count": seed_count,
        "coverage_lane_counts": dict(sorted(lane_counts.items())),
        "headquarters_country_counts": dict(sorted(country_counts.items())),
        "missing_headquarters_country_count": missing_country_count,
        "failure_count": len(failures),
        "failures": failures,
    }


def candidate_from_seed(seed: dict[str, Any], coverage_lane: str, cohort_id: str) -> dict[str, Any]:
    vendor_id = str(seed.get("candidate_vendor_id") or slugify(str(seed["official_domain_candidate"]).split(".")[0]))
    domain = str(seed["official_domain_candidate"]).lower().removeprefix("www.")
    candidate = {
        "candidate_vendor_id": vendor_id,
        "display_name_candidate": str(seed.get("display_name_candidate") or domain)[:120],
        "official_domain_candidate": domain,
        "coverage_lane": str(seed.get("coverage_lane") or coverage_lane),
        "cohort_id": str(seed.get("cohort_id") or cohort_id),
        "discovery_method": str(seed.get("discovery_method") or "manual_seed"),
        "source_index_url": str(seed.get("source_index_url") or f"https://{domain}"),
        "requires_review": True,
        "writes_canonical_vendors": False,
        "non_advisory": True,
    }
    for field in ("vendor_category_candidates", "headquarters_country_candidate"):
        if field in seed:
            candidate[field] = seed[field]
    return candidate


def discover_for_cohort(cohort: dict[str, Any], root: Path = ROOT) -> list[dict[str, Any]]:
    lane = str(cohort["coverage_lane"])
    candidates: list[dict[str, Any]] = []
    for path in seed_paths_for_lane(lane, root=root):
        for seed in load_seed_file(path):
            if str(seed.get("coverage_lane") or lane) != lane:
                continue
            candidates.append(candidate_from_seed(seed, lane, str(cohort["cohort_id"])))
    return candidates


def build_vendor_candidate_report(
    queue_path: Path = QUEUE_PATH,
    root: Path = ROOT,
) -> dict[str, Any]:
    validate_queue(queue_path, root)
    queue = load_json(queue_path)
    known = known_vendor_ids(root)
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for cohort in queue.get("cohorts", []) or []:
        if cohort.get("status") != "queued":
            continue
        cohort_count = 0
        for candidate in discover_for_cohort(cohort, root=root):
            vendor_id = candidate["candidate_vendor_id"]
            if vendor_id in known or vendor_id in seen:
                continue
            seen.add(vendor_id)
            candidates.append(candidate)
            cohort_count += 1
            if cohort_count >= int(cohort["target_vendor_candidates"]):
                break
            if len(candidates) >= queue["limits"]["target_vendor_candidates"]:
                break
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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
            "known_vendor_count": len(known),
        },
        "vendor_candidates": sorted(candidates, key=lambda item: (item["coverage_lane"], item["candidate_vendor_id"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-vendor-candidate-discovery")
    parser.add_argument("command", choices={"discover", "validate-seeds"})
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "vendor-candidate-discovery-report.json")
    args = parser.parse_args()
    if args.command == "validate-seeds":
        summary = validate_seed_identities()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    key: summary[key]
                    for key in (
                        "seed_count",
                        "failure_count",
                        "missing_headquarters_country_count",
                    )
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if summary["failures"] else 0

    report = build_vendor_candidate_report(queue_path=args.queue)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
