from __future__ import annotations

import json
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
    }
    return str(record[keys[kind]])


def records_for(kind: str) -> list[dict[str, Any]]:
    records = []
    for path in iter_paths(RECORD_GLOBS[kind]):
        record = load_yaml(path)
        record["_openva_path"] = str(path.relative_to(ROOT))
        records.append(record)
    return sorted(records, key=lambda item: record_key(kind, item))


def build_indexes() -> int:
    index_dir = ROOT / "indexes"
    counts: dict[str, int] = {}

    for kind, filename in INDEX_FILES.items():
        records = records_for(kind)
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
        },
        "guarantees": {
            "public_sources_only": True,
            "metadata_first": True,
            "non_advisory": True,
            "raw_documents_mirrored_by_default": False,
        },
    })

    print("Built OpenVA indexes and pack manifest.")
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
