from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva.publication import load_publication_config
from tools.openva.site_discovery import build_discovery, render_index_html

ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = SITE_ROOT / "dist"
DEFAULT_SOURCE_HEALTH_SNAPSHOT = ROOT / "public" / "source-health-snapshot.json"
DEFAULT_ASSURANCE_INTELLIGENCE_SNAPSHOT = ROOT / "public" / "assurance-intelligence.json"
DEFAULT_CATALOG_COMPLETENESS_REPORT = ROOT / "reports" / "catalog-completeness-report.json"
DEFAULT_ENTITY_REVIEW_QUEUE = ROOT / "reports" / "entity-review-queue.json"
DEFAULT_FIELD_PROVENANCE_COVERAGE = ROOT / "reports" / "field-provenance-coverage.json"
SOURCE_HEALTH_BUCKET_COUNTS = {
    "healthy": 0,
    "warning": 0,
    "unavailable": 0,
    "ambiguous": 0,
}
SOURCE_HEALTH_LABELS = {
    "healthy": "Reachable at last check",
    "warning": "Retrieval requires review",
    "unavailable": "Unavailable at last check",
    "ambiguous": "Access result ambiguous",
    "missing": "No source-health observation",
}
SOURCE_HEALTH_DESCRIPTIONS = {
    "healthy": "Reachable in the latest maintenance snapshot.",
    "warning": "Retrieval requires review based on the latest maintenance snapshot.",
    "unavailable": "Unavailable in the latest maintenance snapshot.",
    "ambiguous": "Access result ambiguous in the latest maintenance snapshot.",
    "missing": "No source-health observation is available in the latest maintenance snapshot.",
}
SOURCE_HEALTH_NOTICE = "Source health is based on the latest maintenance snapshot and may change."
CONFIDENCE_NOTICE = "Catalog confidence labels are metadata about OpenVA review coverage, not advice."
COMPLETENESS_LABELS = {
    "complete_enough_for_review": "Complete enough for review",
    "partial": "Partial",
    "source_coverage_incomplete": "Source coverage incomplete",
    "entity_review_needed": "Entity review needed",
    "minimal": "Minimal",
    "missing": "Not reviewed",
}
ENTITY_REVIEW_LABELS = {
    "reviewed": "Reviewed",
    "needs_review": "Needs review",
    "not_reviewed": "Not reviewed",
}
FIELD_PROVENANCE_LABELS = {
    "strong": "Strong",
    "mixed": "Mixed",
    "partial": "Mixed",
    "missing": "Missing",
}
ASSURANCE_INTELLIGENCE_NOTICE = (
    "Assurance Intelligence is derived from materialized public-safe projections. "
    "Verification is based on admitted assurance observations; freshness describes "
    "the age of the decisive verification basis; evidence-set state describes "
    "completeness and internal coherence. Source reachability is separate from "
    "assurance verification."
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def empty_source_health_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": None,
        "report_type": "source_health_public_snapshot",
        "source": "latest-source-health",
        "snapshot_type": "missing",
        "metadata": {
            "snapshot_notice": SOURCE_HEALTH_NOTICE,
            "missing_snapshot": True,
            "non_advisory": True,
            "network_fetch_performed": False,
            "catalog_mutation_performed": False,
            "historical_ledger_committed": False,
            "ui_generated": False,
            "release_policy_changed": False,
        },
        "summary": {
            "source_count": 0,
            "status_bucket_counts": dict(SOURCE_HEALTH_BUCKET_COUNTS),
        },
        "health": [],
    }


def load_source_health_snapshot(path: Path = DEFAULT_SOURCE_HEALTH_SNAPSHOT) -> dict[str, Any]:
    if not path.exists():
        print(f"Warning: source health snapshot not found at {path}; site will show No source-health observation labels.")
        return empty_source_health_snapshot()
    snapshot = load_json(path)
    if not isinstance(snapshot, dict) or snapshot.get("report_type") != "source_health_public_snapshot":
        print(f"Warning: invalid source health snapshot at {path}; site will show No source-health observation labels.")
        return empty_source_health_snapshot()
    if not isinstance(snapshot.get("health"), list):
        print(f"Warning: source health snapshot at {path} has no health list; site will show No source-health observation labels.")
        return empty_source_health_snapshot()
    return snapshot


def empty_assurance_intelligence_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "report_type": "assurance_intelligence_public_snapshot",
        "snapshot_type": "empty",
        "projection_profile": "openva.assurance-intelligence.v1",
        "publication_policy": {
            "id": "openva.assurance-intelligence-publication.default",
            "version": "0.1.0",
        },
        "summary": {"assurance_count": 0, "axis_count": 5},
        "entries": [],
        "advisory_boundary": "non_advisory",
    }


def load_assurance_intelligence_snapshot(path: Path = DEFAULT_ASSURANCE_INTELLIGENCE_SNAPSHOT) -> dict[str, Any]:
    if not path.exists():
        print(f"Warning: assurance intelligence snapshot not found at {path}; site will show unavailable labels.")
        return empty_assurance_intelligence_snapshot()
    snapshot = load_json(path)
    if not isinstance(snapshot, dict) or snapshot.get("report_type") != "assurance_intelligence_public_snapshot":
        print(f"Warning: invalid assurance intelligence snapshot at {path}; site will show unavailable labels.")
        return empty_assurance_intelligence_snapshot()
    if not isinstance(snapshot.get("entries"), list):
        print(f"Warning: assurance intelligence snapshot at {path} has no entries list; site will show unavailable labels.")
        return empty_assurance_intelligence_snapshot()
    text = json.dumps(snapshot, sort_keys=True)
    for forbidden in (
        "input_digest",
        "projection_ref",
        "maintenance/",
        "caused_by",
        "assurance_observation_ids",
        "source_observation_ids",
    ):
        if forbidden in text:
            print(f"Warning: assurance intelligence snapshot at {path} contains internal field text; site will show unavailable labels.")
            return empty_assurance_intelligence_snapshot()
    return snapshot


def load_optional_report(path: Path, report_type: str) -> dict[str, Any] | None:
    if not path.exists():
        print(f"Warning: optional catalog confidence report not found at {path}; site will use fallback labels.")
        return None
    report = load_json(path)
    if not isinstance(report, dict) or report.get("report_type") != report_type:
        print(f"Warning: invalid catalog confidence report at {path}; site will use fallback labels.")
        return None
    return report


def vendor_keyed_rows(report: dict[str, Any] | None, field: str) -> dict[str, dict[str, Any]]:
    if not report:
        return {}
    rows = report.get(field) or []
    if not isinstance(rows, list):
        return {}
    return {
        str(row["vendor_id"]): row
        for row in rows
        if isinstance(row, dict) and row.get("vendor_id")
    }


def entity_review_index(report: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if not report:
        return {}
    rows = report.get("items") or []
    index: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(rows, list):
        return index
    for row in rows:
        if isinstance(row, dict) and row.get("vendor_id"):
            index.setdefault(str(row["vendor_id"]), []).append(row)
    return index


def catalog_confidence_for_vendor(
    vendor_id: str,
    completeness: dict[str, dict[str, Any]],
    entity_reviews: dict[str, list[dict[str, Any]]],
    provenance: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    completeness_row = completeness.get(vendor_id)
    completeness_bucket = str(completeness_row.get("completeness_bucket") if completeness_row else "missing")
    if completeness_bucket not in COMPLETENESS_LABELS:
        completeness_bucket = "partial"

    entity_items = entity_reviews.get(vendor_id)
    if entity_items is None:
        entity_status = "not_reviewed"
    elif entity_items:
        entity_status = "needs_review"
    else:
        entity_status = "reviewed"

    provenance_row = provenance.get(vendor_id)
    provenance_bucket = str(provenance_row.get("coverage_bucket") if provenance_row else "missing")
    if provenance_bucket not in FIELD_PROVENANCE_LABELS:
        provenance_bucket = "missing"

    return {
        "notice": CONFIDENCE_NOTICE,
        "source_health_separate": True,
        "catalog_completeness": {
            "bucket": completeness_bucket,
            "label": COMPLETENESS_LABELS[completeness_bucket],
            "missing_expected_sources": completeness_row.get("missing_expected_sources", []) if completeness_row else [],
            "missing_required_fields": completeness_row.get("missing_required_fields", []) if completeness_row else [],
        },
        "entity_review": {
            "status": entity_status,
            "label": ENTITY_REVIEW_LABELS[entity_status],
            "issue_count": len(entity_items or []),
            "issue_types": sorted({str(item.get("issue_type")) for item in entity_items or [] if item.get("issue_type")}),
        },
        "field_provenance": {
            "bucket": provenance_bucket,
            "label": FIELD_PROVENANCE_LABELS[provenance_bucket],
            "covered_fields": provenance_row.get("covered_fields", []) if provenance_row else [],
            "missing_fields": provenance_row.get("missing_fields", []) if provenance_row else [],
        },
    }


def source_health_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_url") or ""),
    )


def source_health_index(snapshot: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows = snapshot.get("health", [])
    if not isinstance(rows, list):
        return {}
    return {
        source_health_key(row): row
        for row in rows
        if isinstance(row, dict) and all(source_health_key(row))
    }


def source_health_for_source(source: dict[str, Any], health_index: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any]:
    health = health_index.get(source_health_key(source))
    if not health:
        return {
            "status_bucket": "missing",
            "label": SOURCE_HEALTH_LABELS["missing"],
            "description": SOURCE_HEALTH_DESCRIPTIONS["missing"],
            "status": None,
            "http_status": None,
            "final_url": None,
            "verified_at": None,
            "run_id": None,
            "observer": None,
            "snapshot_notice": SOURCE_HEALTH_NOTICE,
        }

    bucket = str(health.get("status_bucket") or "ambiguous")
    if bucket not in SOURCE_HEALTH_LABELS:
        bucket = "ambiguous"
    return {
        "status_bucket": bucket,
        "label": SOURCE_HEALTH_LABELS[bucket],
        "description": SOURCE_HEALTH_DESCRIPTIONS[bucket],
        "status": health.get("status"),
        "http_status": health.get("http_status"),
        "final_url": health.get("final_url"),
        "verified_at": health.get("verified_at"),
        "run_id": health.get("run_id"),
        "observer": health.get("observer"),
        "snapshot_notice": SOURCE_HEALTH_NOTICE,
    }


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


def compact_source(source: dict[str, Any], source_health: dict[str, Any] | None = None) -> dict[str, Any]:
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
        "source_health": source_health or source_health_for_source(source, {}),
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
    config = load_publication_config()
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
        "canonical_base_url": config.canonical_base_url,
        "non_advisory": True,
        "compiled_distribution": True,
        "site_data_contract": "openva-site-compiled-catalog.v1",
        "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def build_compiled_catalog(
    source_health_snapshot_path: Path = DEFAULT_SOURCE_HEALTH_SNAPSHOT,
    assurance_intelligence_snapshot_path: Path = DEFAULT_ASSURANCE_INTELLIGENCE_SNAPSHOT,
    catalog_completeness_path: Path = DEFAULT_CATALOG_COMPLETENESS_REPORT,
    entity_review_path: Path = DEFAULT_ENTITY_REVIEW_QUEUE,
    field_provenance_path: Path = DEFAULT_FIELD_PROVENANCE_COVERAGE,
) -> dict[str, Any]:
    pack = load_json(ROOT / "openva-pack.json")
    vendor_search = load_json(ROOT / "indexes/vendor-search.json")
    vendors_index = load_json(ROOT / "indexes/vendors.json")
    sources_index = load_json(ROOT / "indexes/sources.json")
    candidate_index = load_json(ROOT / "indexes/candidate-sources.json")
    unavailable_index = load_json(ROOT / "indexes/unavailable-sources.json")
    coverage_index = load_json(ROOT / "indexes/source-coverage.json")
    observations_index = load_json(ROOT / "indexes/observations.json")
    source_health_snapshot = load_source_health_snapshot(source_health_snapshot_path)
    assurance_intelligence_snapshot = load_assurance_intelligence_snapshot(assurance_intelligence_snapshot_path)
    health_index = source_health_index(source_health_snapshot)
    completeness_report = load_optional_report(catalog_completeness_path, "catalog_completeness_report")
    entity_review_report = load_optional_report(entity_review_path, "entity_review_queue")
    provenance_report = load_optional_report(field_provenance_path, "field_provenance_coverage")
    completeness_by_vendor = vendor_keyed_rows(completeness_report, "vendors")
    entity_reviews_by_vendor = entity_review_index(entity_review_report)
    provenance_by_vendor = vendor_keyed_rows(provenance_report, "vendors")

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
        source = compact_source(row, source_health_for_source(row, health_index))
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

    assurance_intelligence_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for row in assurance_intelligence_snapshot.get("entries", []):
        if not isinstance(row, dict):
            continue
        vendor_id = str(row.get("vendor_id") or "")
        if vendor_id:
            assurance_intelligence_by_vendor.setdefault(vendor_id, []).append(row)

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
            "catalog_confidence": catalog_confidence_for_vendor(
                vendor_id,
                completeness_by_vendor,
                entity_reviews_by_vendor,
                provenance_by_vendor,
            ),
            "assurance_intelligence_count": len(assurance_intelligence_by_vendor.get(vendor_id, [])),
            "detail_path": f"data/vendors/{vendor_id}.json",
        }
        source_records = sources_by_vendor.get(vendor_id, [])
        vendor_summaries.append(summary)
        vendor_details[vendor_id] = {
            "vendor": summary,
            "source_records": source_records,
            # Legacy alias retained while browser and downstream consumers migrate.
            "canonical_sources": source_records,
            "candidate_sources": candidates_by_vendor.get(vendor_id, []),
            "unavailable_sources": unavailable_by_vendor.get(vendor_id, []),
            "latest_observations": observations_by_vendor.get(vendor_id, []),
            "assurance_intelligence": assurance_intelligence_by_vendor.get(vendor_id, []),
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
        "source_health_snapshot": source_health_snapshot,
        "assurance_intelligence_snapshot": assurance_intelligence_snapshot,
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


def build_site(
    output_dir: Path,
    source_health_snapshot_path: Path = DEFAULT_SOURCE_HEALTH_SNAPSHOT,
    assurance_intelligence_snapshot_path: Path = DEFAULT_ASSURANCE_INTELLIGENCE_SNAPSHOT,
    catalog_completeness_path: Path = DEFAULT_CATALOG_COMPLETENESS_REPORT,
    entity_review_path: Path = DEFAULT_ENTITY_REVIEW_QUEUE,
    field_provenance_path: Path = DEFAULT_FIELD_PROVENANCE_COVERAGE,
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    config = load_publication_config()
    for path in (SITE_ROOT / "src").iterdir():
        if not path.is_file():
            continue
        if path.name == "index.html":
            # Homepage OpenVA-owned metadata URLs derive from publication config.
            rendered = render_index_html(path.read_text(encoding="utf-8"), config)
            (output_dir / path.name).write_text(rendered, encoding="utf-8", newline="\n")
        else:
            shutil.copy2(path, output_dir / path.name)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    compiled = build_compiled_catalog(
        source_health_snapshot_path,
        assurance_intelligence_snapshot_path,
        catalog_completeness_path,
        entity_review_path,
        field_provenance_path,
    )
    write_json(output_dir / "data/meta.json", compiled["meta"])
    write_json(output_dir / "data/vendor-search.min.json", {"meta": compiled["meta"], "items": compiled["vendor_summaries"]})
    write_json(output_dir / "data/source-types.json", {"meta": compiled["meta"], "items": compiled["source_types"]})
    write_json(output_dir / "data/coverage-summary.json", {"meta": compiled["meta"], **compiled["coverage_summary"]})
    write_json(output_dir / "data/source-health-snapshot.json", compiled["source_health_snapshot"])
    write_json(output_dir / "data/assurance-intelligence.json", compiled["assurance_intelligence_snapshot"])
    for vendor_id, detail in compiled["vendor_details"].items():
        write_json(output_dir / "data/vendors" / f"{vendor_id}.json", {"meta": compiled["meta"], **detail})
    write_json(output_dir / "data/observation-feed.json", build_observation_feed())

    meta = compiled["meta"]
    build_discovery(
        output_dir,
        config,
        vendor_summaries=compiled["vendor_summaries"],
        vendor_details=compiled["vendor_details"],
        commit_sha=str(meta.get("commit_sha") or "unknown"),
        # Derived from the committed snapshot date (commit date / source / pack),
        # never wall-clock time, so the discovery surface is build-deterministic.
        generated_at=str(meta.get("catalog_snapshot_date") or meta.get("pack_generated_at") or ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static OpenVA site.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Static output directory.")
    parser.add_argument(
        "--source-health-snapshot",
        default=str(DEFAULT_SOURCE_HEALTH_SNAPSHOT),
        help="Optional public source health snapshot JSON.",
    )
    parser.add_argument(
        "--assurance-intelligence-snapshot",
        default=str(DEFAULT_ASSURANCE_INTELLIGENCE_SNAPSHOT),
        help="Optional public assurance intelligence snapshot JSON.",
    )
    parser.add_argument("--catalog-completeness-report", default=str(DEFAULT_CATALOG_COMPLETENESS_REPORT))
    parser.add_argument("--entity-review-queue", default=str(DEFAULT_ENTITY_REVIEW_QUEUE))
    parser.add_argument("--field-provenance-coverage", default=str(DEFAULT_FIELD_PROVENANCE_COVERAGE))
    args = parser.parse_args()
    build_site(
        Path(args.out),
        Path(args.source_health_snapshot),
        Path(args.assurance_intelligence_snapshot),
        Path(args.catalog_completeness_report),
        Path(args.entity_review_queue),
        Path(args.field_provenance_coverage),
    )
    print(f"Built OpenVA site at {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
