from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
EXPORT_PROFILE_ID = "openva.public-metadata.v1"
EXPORT_SCHEMA_VERSION = "openva-export-pack.v1"
GENERATED_AT = "1970-01-01T00:00:00Z"

RECORD_GLOBS = {
    "vendor": ["examples/vendors/*/vendor.yaml", "data/vendors/*/vendor.yaml"],
    "source": ["examples/vendors/*/sources/*.yaml", "data/vendors/*/sources/*.yaml"],
    "artifact": ["examples/vendors/*/artifacts/*.yaml", "data/vendors/*/artifacts/*.yaml"],
    "observation": ["examples/vendors/*/observations/*.yaml", "data/vendors/*/observations/*.yaml"],
    "change": ["examples/vendors/*/changes/*.yaml", "data/vendors/*/changes/*.yaml"],
    "candidate_source": ["examples/vendors/*/candidate_sources/*.yaml", "data/vendors/*/candidate_sources/*.yaml"],
    "unavailable_source": ["examples/vendors/*/unavailable_sources/*.yaml", "data/vendors/*/unavailable_sources/*.yaml"],
}

INDEX_FILES = {
    "vendor": "vendors.json",
    "source": "sources.json",
    "artifact": "artifacts.json",
    "observation": "observations.json",
    "change": "changes.json",
}


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def iter_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def record_key(kind: str, record: dict[str, Any]) -> str:
    keys = {
        "vendor": "vendor_id",
        "source": "source_id",
        "artifact": "artifact_id",
        "observation": "observation_id",
        "change": "change_id",
        "candidate_source": "candidate_source_id",
        "unavailable_source": "unavailable_source_id",
    }
    return str(record[keys[kind]])


def records_for(kind: str) -> list[dict[str, Any]]:
    records = []
    for path in iter_paths(RECORD_GLOBS[kind]):
        record = load_yaml(path)
        record["_openva_path"] = str(path.relative_to(ROOT))
        records.append(record)
    return sorted(records, key=lambda item: record_key(kind, item))


def records_by_vendor(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        vendor_id = record.get("vendor_id")
        if vendor_id:
            grouped[str(vendor_id)].append(record)
    return {vendor_id: sorted(items, key=lambda item: json.dumps(item, sort_keys=True)) for vendor_id, items in grouped.items()}


def vendor_manifest(
    vendor: dict[str, Any],
    sources: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    unavailable: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "vendor": vendor,
        "canonical_sources": sources,
        "artifacts": artifacts,
        "observations": observations,
        "changes": changes,
        "candidate_sources": candidates,
        "unavailable_sources": unavailable,
        "summary": {
            "canonical_source_count": len(sources),
            "artifact_count": len(artifacts),
            "candidate_source_count": len(candidates),
            "unavailable_source_count": len(unavailable),
            "source_types": sorted({str(source.get("source_type")) for source in sources if source.get("source_type")}),
            "candidate_source_types": sorted({str(source.get("source_type_candidate")) for source in candidates if source.get("source_type_candidate")}),
            "unavailable_source_types": sorted({str(source.get("source_type")) for source in unavailable if source.get("source_type")}),
        },
        "guarantees": {
            "public_sources_only": True,
            "metadata_first": True,
            "non_advisory": True,
            "raw_documents_mirrored_by_default": False,
        },
    }


def build_vendor_manifests(record_sets: dict[str, list[dict[str, Any]]]) -> None:
    dist_dir = ROOT / "dist" / "vendors"
    sources_by_vendor = records_by_vendor(record_sets["source"])
    artifacts_by_vendor = records_by_vendor(record_sets["artifact"])
    observations_by_vendor = records_by_vendor(record_sets["observation"])
    changes_by_vendor = records_by_vendor(record_sets["change"])
    candidates_by_vendor = records_by_vendor(record_sets["candidate_source"])
    unavailable_by_vendor = records_by_vendor(record_sets["unavailable_source"])

    for vendor in record_sets["vendor"]:
        vendor_id = str(vendor["vendor_id"])
        write_json(
            dist_dir / f"{vendor_id}.json",
            vendor_manifest(
                vendor,
                sources_by_vendor.get(vendor_id, []),
                artifacts_by_vendor.get(vendor_id, []),
                observations_by_vendor.get(vendor_id, []),
                changes_by_vendor.get(vendor_id, []),
                candidates_by_vendor.get(vendor_id, []),
                unavailable_by_vendor.get(vendor_id, []),
            ),
        )


def build_search_index(record_sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    sources_by_vendor = records_by_vendor(record_sets["source"])
    candidates_by_vendor = records_by_vendor(record_sets["candidate_source"])
    unavailable_by_vendor = records_by_vendor(record_sets["unavailable_source"])
    items = []
    for vendor in record_sets["vendor"]:
        vendor_id = str(vendor["vendor_id"])
        source_types = sorted({str(source.get("source_type")) for source in sources_by_vendor.get(vendor_id, []) if source.get("source_type")})
        candidate_types = sorted({str(source.get("source_type_candidate")) for source in candidates_by_vendor.get(vendor_id, []) if source.get("source_type_candidate")})
        unavailable_types = sorted({str(source.get("source_type")) for source in unavailable_by_vendor.get(vendor_id, []) if source.get("source_type")})
        items.append(
            {
                "vendor_id": vendor_id,
                "display_name": vendor.get("display_name"),
                "legal_name": vendor.get("legal_name"),
                "official_domains": vendor.get("official_domains", []),
                "headquarters_country": vendor.get("headquarters_country"),
                "status": vendor.get("status"),
                "source_types": source_types,
                "candidate_source_types": candidate_types,
                "unavailable_source_types": unavailable_types,
                "manifest_path": f"dist/vendors/{vendor_id}.json",
            }
        )
    return {"schema_version": SCHEMA_VERSION, "generated_at": GENERATED_AT, "count": len(items), "items": sorted(items, key=lambda item: item["vendor_id"])}


def build_source_coverage(record_sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    source_counter = Counter(str(source.get("source_type")) for source in record_sets["source"] if source.get("source_type"))
    candidate_counter = Counter(str(source.get("source_type_candidate")) for source in record_sets["candidate_source"] if source.get("source_type_candidate"))
    unavailable_counter = Counter(str(source.get("source_type")) for source in record_sets["unavailable_source"] if source.get("source_type"))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "source_type_counts": dict(sorted(source_counter.items())),
        "candidate_source_type_counts": dict(sorted(candidate_counter.items())),
        "unavailable_source_type_counts": dict(sorted(unavailable_counter.items())),
    }


def build_registry_outputs(record_sets: dict[str, list[dict[str, Any]]]) -> None:
    build_vendor_manifests(record_sets)
    write_json(ROOT / "indexes" / "vendor-search.json", build_search_index(record_sets))
    write_json(ROOT / "indexes" / "source-coverage.json", build_source_coverage(record_sets))


def build_indexes() -> int:
    index_dir = ROOT / "indexes"
    counts: dict[str, int] = {}
    record_sets: dict[str, list[dict[str, Any]]] = {}

    for kind in RECORD_GLOBS:
        record_sets[kind] = records_for(kind)

    for kind, filename in INDEX_FILES.items():
        records = record_sets[kind]
        counts[kind] = len(records)
        write_json(
            index_dir / filename,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": kind,
                "generated_at": GENERATED_AT,
                "count": len(records),
                "items": records,
            },
        )

    write_json(index_dir / "summary.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "counts": counts,
    })

    build_registry_outputs(record_sets)

    write_json(ROOT / "openva-pack.json", {
        "profileId": EXPORT_PROFILE_ID,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "packId": "open-vendor-assurance",
        "generatedAt": GENERATED_AT,
        "schema_version": SCHEMA_VERSION,
        "pack_id": "open-vendor-assurance",
        "name": "open-vendor-assurance",
        "description": "Public-source-only vendor assurance metadata substrate.",
        "publisher": "open-vendor-assurance",
        "license": {
            "metadata": "CC0-1.0",
            "code": "MIT",
            "vendor_materials": "Vendor materials remain owned by their respective owners.",
        },
        "generated_at": GENERATED_AT,
        "indexes": {
            "vendors": "indexes/vendors.json",
            "sources": "indexes/sources.json",
            "artifacts": "indexes/artifacts.json",
            "observations": "indexes/observations.json",
            "changes": "indexes/changes.json",
            "summary": "indexes/summary.json",
            "vendor_search": "indexes/vendor-search.json",
            "source_coverage": "indexes/source-coverage.json",
        },
        "registry_outputs": {
            "vendor_manifests": "dist/vendors/{vendor_id}.json"
        },
        "guarantees": {
            "public_sources_only": True,
            "metadata_first": True,
            "non_advisory": True,
            "raw_documents_mirrored_by_default": False,
        },
    })

    print("Built OpenVA indexes, registry outputs, and pack manifest.")
    return 0


def generated_paths() -> list[Path]:
    index_dir = ROOT / "indexes"
    return [ROOT / "openva-pack.json", *(index_dir.glob("*.json"))]


def check_generated_current() -> list[str]:
    before = {path: path.read_text(encoding="utf-8") if path.exists() else None for path in generated_paths()}
    build_indexes()
    after = {path: path.read_text(encoding="utf-8") if path.exists() else None for path in generated_paths()}
    failures = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            failures.append(f"{path.relative_to(ROOT)} is not up to date; run python -m tools.openva.validate build-indexes")
    return failures