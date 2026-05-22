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
    return {
        **annotation("canonical"),
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


def build_catalog_data() -> dict[str, Any]:
    pack = load_json(ROOT / "openva-pack.json")
    vendor_search = load_json(ROOT / "indexes/vendor-search.json")
    vendors_index = load_json(ROOT / "indexes/vendors.json")
    sources_index = load_json(ROOT / "indexes/sources.json")
    candidate_index = load_json(ROOT / "indexes/candidate-sources.json")
    unavailable_index = load_json(ROOT / "indexes/unavailable-sources.json")
    coverage_index = load_json(ROOT / "indexes/source-coverage.json")

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

    vendors = []
    for row in vendor_search.get("items", []):
        vendor_id = row.get("vendor_id")
        full = vendors_by_id.get(vendor_id, {})
        vendors.append(
            {
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
                "coverage": coverage_by_id.get(vendor_id, {}),
            }
        )

    sources = [compact_source(row) for row in sources_index.get("items", []) if isinstance(row, dict)]
    candidates = [
        compact_candidate(row)
        for row in candidate_index.get("items", [])
        if isinstance(row, dict)
    ]
    unavailable = [
        {**annotation("unavailable"), **row}
        for row in unavailable_index.get("items", [])
        if isinstance(row, dict)
    ]
    sha = commit_sha()
    tag = release_tag()
    date = commit_date() or source_date(sources) or str(pack.get("generated_at") or pack.get("generatedAt") or "")

    return {
        "meta": {
            "profileId": pack.get("profileId"),
            "schemaVersion": pack.get("schemaVersion"),
            "packId": pack.get("packId"),
            "schema_version": pack.get("schema_version"),
            "release_tag": tag,
            "commit_sha": sha,
            "catalog_snapshot_identity": tag or sha,
            "catalog_snapshot_date": date,
            "pack_generated_at": pack.get("generated_at") or pack.get("generatedAt"),
            "vendor_count": len(vendors),
            "source_count": len(sources),
            "github_releases_url": "https://github.com/thedanieltan/open-vendor-assurance/releases",
            "non_advisory": True,
            "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
        "vendors": vendors,
        "sources": sources,
        "candidate_sources": candidates,
        "unavailable_sources": unavailable,
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
    write_json(output_dir / "data/catalog-data.json", build_catalog_data())
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
