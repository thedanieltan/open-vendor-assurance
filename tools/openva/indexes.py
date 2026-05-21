from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from tools.openva.paths import relative_repo_path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
EXPORT_PROFILE_ID = "openva.public-metadata.v1"
EXPORT_SCHEMA_VERSION = "openva-export-pack.v1"
GENERATED_AT = "1970-01-01T00:00:00Z"

RECORD_GLOBS = {
    "vendor": ["data/vendors/*/vendor.yaml"],
    "source": ["data/vendors/*/sources/*.yaml"],
    "artifact": ["data/vendors/*/artifacts/*.yaml"],
    "observation": ["data/vendors/*/observations/*.yaml"],
    "change": ["data/vendors/*/changes/*.yaml"],
    "legal_entity": ["data/vendors/*/legal_entities/*.yaml"],
    "entity_mention": ["data/vendors/*/entity_mentions/*.yaml"],
    "candidate_source": ["data/vendors/*/candidate_sources/*.yaml"],
    "unavailable_source": ["data/vendors/*/unavailable_sources/*.yaml"],
}
INDEX_FILES = {
    "vendor": "vendors.json",
    "source": "sources.json",
    "artifact": "artifacts.json",
    "observation": "observations.json",
    "change": "changes.json",
    "legal_entity": "legal-entities.json",
    "entity_mention": "entity-mentions.json",
    "candidate_source": "candidate-sources.json",
    "unavailable_source": "unavailable-sources.json",
}
REGISTRY_INDEX_FILES = {
    "vendor_search": "vendor-search.json",
    "source_coverage": "source-coverage.json",
    "contracting_entity_resolution": "contracting-entity-resolution.json",
}
VENDOR_MATCH_INDEX_FILE = "vendor-match-index.json"
ID_KEYS = {
    "vendor": "vendor_id",
    "source": "source_id",
    "artifact": "artifact_id",
    "observation": "observation_id",
    "change": "change_id",
    "legal_entity": "entity_id",
    "entity_mention": "mention_id",
    "candidate_source": "candidate_source_id",
    "unavailable_source": "unavailable_source_id",
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def iter_paths(patterns: list[str]) -> list[Path]:
    return sorted(path for pattern in patterns for path in ROOT.glob(pattern) if path.is_file())


def records_for(kind: str) -> list[dict[str, Any]]:
    records = []
    for path in iter_paths(RECORD_GLOBS[kind]):
        record = load_yaml(path)
        if kind == "vendor":
            catalog_status = record.get("catalog_status", record.get("status"))
            if catalog_status is not None:
                record["catalog_status"] = catalog_status
                record.setdefault("status", catalog_status)
        if kind == "change":
            significance = record.get("catalog_change_significance", record.get("materiality"))
            if significance is not None:
                record["catalog_change_significance"] = significance
                record.setdefault("materiality", significance)
        record["_openva_path"] = relative_repo_path(path, ROOT)
        records.append(record)
    return sorted(records, key=lambda record: str(record[ID_KEYS[kind]]))


def by_vendor(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("vendor_id"):
            grouped[str(record["vendor_id"])].append(record)
    return dict(grouped)


def types(records: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(record[key]) for record in records if record.get(key)})


def vendor_manifest(
    vendor: dict[str, Any],
    sources: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    legal_entities: list[dict[str, Any]],
    entity_mentions: list[dict[str, Any]],
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
        "legal_entities": legal_entities,
        "entity_mentions": entity_mentions,
        "candidate_sources": candidates,
        "unavailable_sources": unavailable,
        "summary": {
            "canonical_source_count": len(sources),
            "artifact_count": len(artifacts),
            "candidate_source_count": len(candidates),
            "unavailable_source_count": len(unavailable),
            "legal_entity_count": len(legal_entities),
            "entity_mention_count": len(entity_mentions),
            "source_types": types(sources, "source_type"),
            "candidate_source_types": types(candidates, "source_type_candidate"),
            "unavailable_source_types": types(unavailable, "source_type"),
        },
        "guarantees": {"public_sources_only": True, "metadata_first": True, "non_advisory": True, "raw_documents_mirrored_by_default": False},
    }


def build_search_index(record_sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    sources = by_vendor(record_sets["source"])
    candidates = by_vendor(record_sets["candidate_source"])
    unavailable = by_vendor(record_sets["unavailable_source"])
    items = []
    for vendor in record_sets["vendor"]:
        vendor_id = str(vendor["vendor_id"])
        items.append({
            "vendor_id": vendor_id,
            "display_name": vendor.get("display_name"),
            "legal_name": vendor.get("legal_name"),
            "official_domains": vendor.get("official_domains", []),
            "headquarters_country": vendor.get("headquarters_country"),
            "catalog_status": vendor.get("catalog_status", vendor.get("status")),
            "status": vendor.get("status", vendor.get("catalog_status")),
            "source_types": types(sources.get(vendor_id, []), "source_type"),
            "candidate_source_types": types(candidates.get(vendor_id, []), "source_type_candidate"),
            "unavailable_source_types": types(unavailable.get(vendor_id, []), "source_type"),
            "manifest_path": f"dist/vendors/{vendor_id}.json",
        })
    return {"schema_version": SCHEMA_VERSION, "generated_at": GENERATED_AT, "count": len(items), "items": sorted(items, key=lambda item: item["vendor_id"])}


def build_source_coverage(record_sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    sources = by_vendor(record_sets["source"])
    candidates = by_vendor(record_sets["candidate_source"])
    unavailable = by_vendor(record_sets["unavailable_source"])
    vendor_coverage = []
    core_source_types = {"dpa", "privacy_notice", "security_page", "subprocessors_list"}
    for vendor in record_sets["vendor"]:
        vendor_id = str(vendor["vendor_id"])
        canonical_types = types(sources.get(vendor_id, []), "source_type")
        candidate_types = types(candidates.get(vendor_id, []), "source_type_candidate")
        unavailable_types = types(unavailable.get(vendor_id, []), "source_type")
        covered_types = set(canonical_types) | set(candidate_types) | set(unavailable_types)
        vendor_coverage.append(
            {
                "vendor_id": vendor_id,
                "canonical_source_types": canonical_types,
                "candidate_source_types": candidate_types,
                "unavailable_source_types": unavailable_types,
                "missing_core_source_types": sorted(core_source_types - covered_types),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "source_type_counts": dict(sorted(Counter(str(item["source_type"]) for item in record_sets["source"] if item.get("source_type")).items())),
        "candidate_source_type_counts": dict(sorted(Counter(str(item["source_type_candidate"]) for item in record_sets["candidate_source"] if item.get("source_type_candidate")).items())),
        "unavailable_source_type_counts": dict(sorted(Counter(str(item["source_type"]) for item in record_sets["unavailable_source"] if item.get("source_type")).items())),
        "vendor_coverage": sorted(vendor_coverage, key=lambda item: item["vendor_id"]),
    }


def build_contracting_entity_resolution(record_sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for entity in record_sets["legal_entity"]:
        if entity.get("catalog_status") != "canonical":
            continue
        entity_id = str(entity["entity_id"])
        vendor_id = str(entity["vendor_id"])
        for mapping in entity.get("contracting_jurisdictions", []) or []:
            status = "resolved" if mapping.get("role") == "primary_contracting_entity" else "candidate"
            items.append(
                {
                    "vendor_id": vendor_id,
                    "jurisdiction": mapping.get("jurisdiction"),
                    "resolution_status": status,
                    "resolved_entity_id": entity_id if status == "resolved" else None,
                    "candidate_entity_ids": [entity_id],
                    "ambiguity_reasons": [],
                    "evidence_source_ids": [mapping.get("source_id")] if mapping.get("source_id") else [],
                    "resolution_confidence": mapping.get("confidence", "medium"),
                    "summary": mapping.get("summary"),
                    "pack_generated_at": GENERATED_AT,
                }
            )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[(str(item["vendor_id"]), str(item["jurisdiction"]))].append(item)

    resolved_items: list[dict[str, Any]] = []
    for group in grouped.values():
        if len(group) == 1:
            resolved_items.append(group[0])
            continue
        entity_ids = sorted({entity_id for item in group for entity_id in item["candidate_entity_ids"]})
        evidence_source_ids = sorted({source_id for item in group for source_id in item["evidence_source_ids"]})
        confidences = {str(item.get("resolution_confidence", "medium")) for item in group}
        resolved_items.append(
            {
                "vendor_id": group[0]["vendor_id"],
                "jurisdiction": group[0]["jurisdiction"],
                "resolution_status": "ambiguous",
                "resolved_entity_id": None,
                "candidate_entity_ids": entity_ids,
                "ambiguity_reasons": ["jurisdiction_overlap"],
                "evidence_source_ids": evidence_source_ids,
                "resolution_confidence": "high" if confidences == {"high"} else "medium" if "medium" in confidences else "low",
                "summary": "Multiple public sources identify candidate contracting entities for this jurisdiction.",
                "pack_generated_at": GENERATED_AT,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "count": len(resolved_items),
        "items": sorted(
            resolved_items,
            key=lambda item: (str(item["vendor_id"]), str(item["jurisdiction"]), str(item.get("resolved_entity_id"))),
        ),
    }


def source_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "source_url": source.get("source_url"),
        "title": source.get("title_en") or source.get("title_native"),
        "confidence": source.get("confidence"),
        "effective_or_published_at": source.get("effective_or_published_at"),
    }


def candidate_source_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": candidate.get("candidate_source_id"),
        "source_type": candidate.get("source_type_candidate"),
        "source_url": candidate.get("candidate_url"),
        "title": candidate.get("title_en") or candidate.get("title_native"),
        "confidence": candidate.get("confidence"),
    }


def primary_source_by_type(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        source_type = source.get("source_type")
        if isinstance(source_type, str) and source_type:
            grouped[source_type].append(source)
    return {
        source_type: sorted(
            typed_sources,
            key=lambda item: (
                item.get("effective_or_published_at") in (None, ""),
                reverse_date_key(str(item.get("effective_or_published_at") or "")),
                str(item.get("source_id") or ""),
            ),
        )[0]
        for source_type, typed_sources in sorted(grouped.items())
    }


def reverse_date_key(value: str) -> str:
    return "".join(chr(255 - ord(character)) for character in value)


def build_vendor_match_index(record_sets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    sources = by_vendor(record_sets["source"])
    candidates = by_vendor(record_sets["candidate_source"])
    coverage = {
        row["vendor_id"]: row
        for row in build_source_coverage(record_sets)["vendor_coverage"]
        if isinstance(row.get("vendor_id"), str)
    }
    items = []
    for vendor in record_sets["vendor"]:
        vendor_id = str(vendor["vendor_id"])
        canonical_sources = [source_payload(source) for source in sources.get(vendor_id, [])]
        candidate_sources = [candidate_source_payload(candidate) for candidate in candidates.get(vendor_id, [])]
        coverage_row = coverage.get(vendor_id, {})
        items.append(
            {
                "vendor_id": vendor_id,
                "display_name": vendor.get("display_name"),
                "legal_name": vendor.get("legal_name"),
                "catalog_status": vendor.get("catalog_status", vendor.get("status")),
                "official_domains": vendor.get("official_domains", []),
                "manifest_path": f"dist/vendors/{vendor_id}.json",
                "canonical_source_types": coverage_row.get("canonical_source_types", []),
                "candidate_source_types": coverage_row.get("candidate_source_types", []),
                "unavailable_source_types": coverage_row.get("unavailable_source_types", []),
                "missing_core_source_types": coverage_row.get("missing_core_source_types", []),
                "canonical_sources": canonical_sources,
                "candidate_sources": candidate_sources,
                "primary_source_by_type": primary_source_by_type(canonical_sources),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "profileId": EXPORT_PROFILE_ID,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "advisory_boundary": "non_advisory",
        "non_advisory": True,
        "count": len(items),
        "items": sorted(items, key=lambda item: item["vendor_id"]),
    }


def build_registry_outputs(record_sets: dict[str, list[dict[str, Any]]]) -> None:
    manifest_dir = ROOT / "dist" / "vendors"
    sources = by_vendor(record_sets["source"])
    artifacts = by_vendor(record_sets["artifact"])
    observations = by_vendor(record_sets["observation"])
    changes = by_vendor(record_sets["change"])
    legal_entities = by_vendor(record_sets["legal_entity"])
    entity_mentions = by_vendor(record_sets["entity_mention"])
    candidates = by_vendor(record_sets["candidate_source"])
    unavailable = by_vendor(record_sets["unavailable_source"])
    vendor_ids = {str(vendor["vendor_id"]) for vendor in record_sets["vendor"]}
    if manifest_dir.exists():
        for stale in manifest_dir.glob("*.json"):
            if stale.stem not in vendor_ids:
                stale.unlink()
    for vendor in record_sets["vendor"]:
        vendor_id = str(vendor["vendor_id"])
        write_json(
            manifest_dir / f"{vendor_id}.json",
            vendor_manifest(
                vendor,
                sources.get(vendor_id, []),
                artifacts.get(vendor_id, []),
                observations.get(vendor_id, []),
                changes.get(vendor_id, []),
                legal_entities.get(vendor_id, []),
                entity_mentions.get(vendor_id, []),
                candidates.get(vendor_id, []),
                unavailable.get(vendor_id, []),
            ),
        )
    write_json(ROOT / "indexes" / "vendor-search.json", build_search_index(record_sets))
    write_json(ROOT / "indexes" / "source-coverage.json", build_source_coverage(record_sets))
    write_json(ROOT / "indexes" / "contracting-entity-resolution.json", build_contracting_entity_resolution(record_sets))
    write_json(ROOT / "indexes" / VENDOR_MATCH_INDEX_FILE, build_vendor_match_index(record_sets))


def build_indexes() -> int:
    index_dir = ROOT / "indexes"
    record_sets = {kind: records_for(kind) for kind in RECORD_GLOBS}
    counts = {}
    for kind, filename in INDEX_FILES.items():
        records = record_sets[kind]
        counts[kind] = len(records)
        write_json(index_dir / filename, {"schema_version": SCHEMA_VERSION, "kind": kind, "generated_at": GENERATED_AT, "count": len(records), "items": records})
    write_json(index_dir / "summary.json", {"schema_version": SCHEMA_VERSION, "generated_at": GENERATED_AT, "counts": counts})
    build_registry_outputs(record_sets)
    index_names = {
        "vendor": "vendors",
        "source": "sources",
        "artifact": "artifacts",
        "observation": "observations",
        "change": "changes",
        "legal_entity": "legal_entities",
        "entity_mention": "entity_mentions",
        "candidate_source": "candidate_sources",
        "unavailable_source": "unavailable_sources",
    }
    index_paths = {
        **{index_names[key]: f"indexes/{filename}" for key, filename in INDEX_FILES.items()},
        "summary": "indexes/summary.json",
        "vendor_search": "indexes/vendor-search.json",
        "source_coverage": "indexes/source-coverage.json",
        "contracting_entity_resolution": "indexes/contracting-entity-resolution.json",
    }
    write_json(ROOT / "openva-pack.json", {
        "profileId": EXPORT_PROFILE_ID,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "packId": "open-vendor-assurance",
        "generatedAt": GENERATED_AT,
        "schema_version": SCHEMA_VERSION,
        "pack_id": "open-vendor-assurance",
        "name": "open-vendor-assurance",
        "description": "Public-source-only vendor assurance metadata substrate. Entity resolution reflects observed public evidence, not current corporate status or legal advice.",
        "publisher": "open-vendor-assurance",
        "license": {"metadata": "CC0-1.0", "code": "MIT", "vendor_materials": "Vendor materials remain owned by their respective owners."},
        "generated_at": GENERATED_AT,
        "indexes": index_paths,
        "registry_outputs": {"vendor_manifests": "dist/vendors/{vendor_id}.json"},
        "guarantees": {"public_sources_only": True, "metadata_first": True, "non_advisory": True, "raw_documents_mirrored_by_default": False},
    })
    print("Built OpenVA indexes, registry outputs, and pack manifest.")
    return 0


def generated_paths() -> list[Path]:
    index_dir = ROOT / "indexes"
    manifest_dir = ROOT / "dist" / "vendors"
    vendor_ids = {str(record["vendor_id"]) for record in records_for("vendor")}
    existing_manifests = set(manifest_dir.glob("*.json")) if manifest_dir.exists() else set()
    expected_manifests = {manifest_dir / f"{vendor_id}.json" for vendor_id in vendor_ids}
    manifests = sorted(existing_manifests | expected_manifests)
    return [
        ROOT / "openva-pack.json",
        *(index_dir / filename for filename in INDEX_FILES.values()),
        *(index_dir / filename for filename in REGISTRY_INDEX_FILES.values()),
        index_dir / VENDOR_MATCH_INDEX_FILE,
        index_dir / "summary.json",
        *manifests,
    ]


def check_generated_current() -> list[str]:
    paths = generated_paths()
    before = {path: path.read_text(encoding="utf-8") if path.exists() else None for path in paths}
    build_indexes()
    after = {path: path.read_text(encoding="utf-8") if path.exists() else None for path in paths}
    return [
        f"{relative_repo_path(path, ROOT)} is not up to date; run python -m tools.openva.validate build-indexes"
        for path in paths
        if before.get(path) != after.get(path)
    ]
