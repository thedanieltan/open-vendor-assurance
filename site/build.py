from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = SITE_ROOT / "dist"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def release_tag() -> str:
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    if ref_type == "tag" and ref_name:
        return ref_name
    exact_tag = git_value("describe", "--tags", "--exact-match")
    return exact_tag if exact_tag.startswith("v") else ""


def commit_sha() -> str:
    return os.environ.get("GITHUB_SHA") or git_value("rev-parse", "HEAD")


def commit_date() -> str:
    return git_value("show", "-s", "--format=%cI", "HEAD")


def source_date(sources: list[dict[str, Any]]) -> str:
    collected = [
        str(source.get("provenance", {}).get("collected_at", ""))
        for source in sources
        if isinstance(source.get("provenance"), dict)
    ]
    return max([value for value in collected if value], default="")


def annotation(record_class: str) -> dict[str, Any]:
    if record_class == "candidate":
        return {
            "record_class": "candidate",
            "canonical": False,
            "catalog_tier": "discovery",
            "review_state": "human_review_required",
            "advisory_boundary": "non_advisory",
        }
    if record_class == "observation":
        return {
            "record_class": "observation",
            "canonical": False,
            "catalog_tier": "observation",
            "review_state": "auto_observed",
            "advisory_boundary": "non_advisory",
        }
    return {
        "record_class": record_class,
        "canonical": record_class == "canonical",
        "catalog_tier": "human_reviewed",
        "review_state": "human_reviewed",
        "advisory_boundary": "non_advisory",
    }


def compact_source(source: dict[str, Any]) -> dict[str, Any]:
    tier = source.get("catalog_tier") or (
        "machine_validated" if source.get("review_state") == "auto_validated" else "human_reviewed"
    )
    review_state = source.get("review_state")
    if review_state in (None, "", "validated"):
        review_state = "auto_validated" if tier == "machine_validated" else "human_reviewed"
    return {
        **annotation("canonical"),
        "catalog_tier": tier,
        "review_state": review_state,
        "advisory_boundary": source.get("advisory_boundary") or "non_advisory",
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "source_url": source.get("source_url"),
        "title": source.get("title_en") or source.get("title_native"),
        "source_language": source.get("source_language"),
        "source_authority_class": source.get("source_authority_class"),
        "access_class": source.get("access_class"),
        "rights_class": source.get("rights_class"),
        "provenance": source.get("provenance") or {},
    }


def compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **annotation("candidate"),
        "vendor_id": candidate.get("vendor_id"),
        "candidate_source_id": candidate.get("candidate_source_id"),
        "source_type_candidate": candidate.get("source_type_candidate"),
        "candidate_url": candidate.get("candidate_url"),
        "confidence": candidate.get("confidence"),
        "requires_review": candidate.get("requires_review"),
        "discovered_at": candidate.get("discovered_at"),
    }


def build_meta(pack: dict[str, Any], sources: list[dict[str, Any]], vendor_count: int) -> dict[str, Any]:
    sha = commit_sha()
    tag = release_tag()
    date = commit_date() or source_date(sources) or str(pack.get("generated_at") or pack.get("generatedAt") or "")
    return {
        "profileId": pack.get("profileId"),
        "schemaVersion": pack.get("schemaVersion"),
        "packId": pack.get("packId"),
        "schema_version": pack.get("schema_version"),
        "release_tag": tag,
        "commit_sha": sha,
        "catalog_snapshot_identity": tag or sha,
        "catalog_snapshot_date": date,
        "pack_generated_at": pack.get("generated_at") or pack.get("generatedAt"),
        "vendor_count": vendor_count,
        "source_count": len(sources),
        "github_releases_url": "https://github.com/thedanieltan/open-vendor-assurance/releases",
        "non_advisory": True,
        "compiled_distribution": True,
        "site_data_contract": "openva-site-compiled-catalog.v1",
        "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def build_compiled_catalog() -> dict[str, Any]:
    pack = load_json(ROOT / "openva-pack.json")
    vendor_search = load_json(ROOT / "indexes/vendor-search.json")
    vendors_index = load_json(ROOT / "indexes/vendors.json")
    sources_index = load_json(ROOT / "indexes/sources.json")
    candidate_index = load_json(ROOT / "indexes/candidate-sources.json")
    unavailable_index = load_json(ROOT / "indexes/unavailable-sources.json")
    coverage_index = load_json(ROOT / "indexes/source-coverage.json")
    observations_index = load_json(ROOT / "indexes/observations.json")

    vendors_by_id = {
        row["vendor_id"]: row
        for row in vendors_index.get("items", [])
        if isinstance(row, dict) and isinstance(row.get("vendor_id"), str)
    }
    coverage_by_id = {
        row["vendor_id"]: row
        for row in coverage_index.get("vendor_coverage", [])
        if isinstance(row, dict) and isinstance(row.get("vendor_id"), str)
    }

    sources_by_vendor: dict[str, list[dict[str, Any]]] = {}
    compact_sources: list[dict[str, Any]] = []
    for row in sources_index.get("items", []):
        if not isinstance(row, dict):
            continue
        source = compact_source(row)
        compact_sources.append(source)
        vendor_id = str(source.get("vendor_id") or "")
        if vendor_id:
            sources_by_vendor.setdefault(vendor_id, []).append(source)

    candidates_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_index.get("items", []):
        if not isinstance(row, dict):
            continue
        candidate = compact_candidate(row)
        vendor_id = str(candidate.get("vendor_id") or "")
        if vendor_id:
            candidates_by_vendor.setdefault(vendor_id, []).append(candidate)

    unavailable_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for row in unavailable_index.get("items", []):
        if not isinstance(row, dict):
            continue
        unavailable = {**annotation("unavailable"), **row}
        vendor_id = str(unavailable.get("vendor_id") or "")
        if vendor_id:
            unavailable_by_vendor.setdefault(vendor_id, []).append(unavailable)

    observations_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for row in observations_index.get("items", []):
        if not isinstance(row, dict):
            continue
        observation = {**annotation("observation"), **row}
        vendor_id = str(observation.get("vendor_id") or "")
        if vendor_id:
            observations_by_vendor.setdefault(vendor_id, []).append(observation)

    vendor_summaries = []
    vendor_details = {}
    for row in vendor_search.get("items", []):
        if not isinstance(row, dict):
            continue
        vendor_id = row.get("vendor_id")
        if not isinstance(vendor_id, str) or not vendor_id:
            continue
        full = vendors_by_id.get(vendor_id, {})
        coverage = coverage_by_id.get(vendor_id, {})
        summary = {
            "vendor_id": vendor_id,
            "display_name": row.get("display_name"),
            "legal_name": row.get("legal_name"),
            "catalog_status": row.get("catalog_status") or row.get("status"),
            "official_domains": row.get("official_domains", []),
            "headquarters_country": row.get("headquarters_country"),
            "vendor_categories": full.get("vendor_categories", []),
            "source_types": row.get("source_types", []),
            "candidate_source_types": row.get("candidate_source_types", []),
            "unavailable_source_types": row.get("unavailable_source_types", []),
            "coverage": coverage,
            "detail_path": f"data/vendors/{vendor_id}.json",
        }
        vendor_summaries.append(summary)
        vendor_details[vendor_id] = {
            "vendor": summary,
            "canonical_sources": sources_by_vendor.get(vendor_id, []),
            "candidate_sources": candidates_by_vendor.get(vendor_id, []),
            "unavailable_sources": unavailable_by_vendor.get(vendor_id, []),
            "latest_observations": observations_by_vendor.get(vendor_id, []),
        }

    source_types = sorted({source.get("source_type") for source in compact_sources if source.get("source_type")})
    countries = sorted({vendor.get("headquarters_country") for vendor in vendor_summaries if vendor.get("headquarters_country")})
    categories = sorted({category for vendor in vendor_summaries for category in vendor.get("vendor_categories", []) if category})
    coverage_summary = {
        "vendor_coverage": coverage_index.get("vendor_coverage", []),
        "source_types": source_types,
        "countries": countries,
        "categories": categories,
    }

    meta = build_meta(pack, compact_sources, len(vendor_summaries))
    return {
        "meta": meta,
        "vendor_summaries": vendor_summaries,
        "vendor_details": vendor_details,
        "source_types": source_types,
        "coverage_summary": coverage_summary,
    }


def build_observation_feed() -> dict[str, Any]:
    return {
        "generated_at": None,
        "source_commit": commit_sha(),
        "workflow": None,
        "events": [],
        "empty_state": (
            "No live observation events are available yet. The live feed UI shell is ready, "
            "but real observation events require the observation ledger workflow, which will "
            "be added in a later PR."
        ),
        "contract": {
            "canonical": False,
            "catalog_tier": "observation",
            "review_state": ["auto_observed", "human_review_required"],
            "advisory_boundary": "non_advisory",
            "required_fields": [
                "event_type",
                "vendor_id",
                "source_id",
                "source_type",
                "observed_at",
                "result",
                "catalog_tier",
                "review_state",
                "canonical",
                "advisory_boundary",
            ],
        },
    }


def build_site(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    for path in (SITE_ROOT / "src").iterdir():
        if path.is_file():
            shutil.copy2(path, output_dir / path.name)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    compiled = build_compiled_catalog()
    write_json(output_dir / "data/meta.json", compiled["meta"])
    write_json(output_dir / "data/vendor-search.min.json", {"meta": compiled["meta"], "items": compiled["vendor_summaries"]})
    write_json(output_dir / "data/source-types.json", {"meta": compiled["meta"], "items": compiled["source_types"]})
    write_json(output_dir / "data/coverage-summary.json", {"meta": compiled["meta"], **compiled["coverage_summary"]})
    for vendor_id, detail in compiled["vendor_details"].items():
        write_json(output_dir / "data/vendors" / f"{vendor_id}.json", {"meta": compiled["meta"], **detail})
    write_json(output_dir / "data/observation-feed.json", build_observation_feed())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static OpenVA site.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Static output directory.")
    args = parser.parse_args()
    build_site(Path(args.out))
    print(f"Built OpenVA site at {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())