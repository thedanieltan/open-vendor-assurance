from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva.catalog_lifecycle import change_event, lifecycle_change_type
from tools.openva.indexes import build_indexes
from tools.openva.url_safety import validate_url_safety

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/openva/catalog-batch.schema.json"
SCHEMA_VERSION = "0.1.0"
RIGHTS_CLASS = "metadata_only"
HASH_TBD = "sha256:TBD"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any], *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path.relative_to(ROOT)} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def validate_manifest_schema(manifest: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(load_yaml(SCHEMA_PATH), format_checker=FormatChecker())
    failures: list[str] = []
    for error in sorted(validator.iter_errors(manifest), key=lambda err: list(err.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        failures.append(f"catalog batch manifest: {location}: {error.message}")
    return failures


def sources_for(vendor: dict[str, Any]) -> list[dict[str, Any]]:
    return list(vendor.get("sources", []))


def validate_manifest_rules(manifest: dict[str, Any], *, force: bool) -> list[str]:
    failures: list[str] = []
    vendor_ids: set[str] = set()
    source_ids: set[str] = set()
    artifact_ids: set[str] = set()
    source_urls: set[str] = set()
    operation = manifest["operation"]

    for vendor in manifest.get("vendors", []):
        vendor_id = vendor["vendor_id"]
        if vendor_id in vendor_ids:
            failures.append(f"{vendor_id}: duplicate vendor_id in batch")
        vendor_ids.add(vendor_id)

        vendor_path = ROOT / f"data/vendors/{vendor_id}/vendor.yaml"
        if operation == "create" and vendor_path.exists() and not force:
            failures.append(f"{vendor_path.relative_to(ROOT)} already exists")
        if operation in {"refresh", "deprecate"} and not vendor_path.exists():
            failures.append(f"{vendor_path.relative_to(ROOT)} does not exist")

        for source in sources_for(vendor):
            artifact = source["artifact"]
            source_id = source["source_id"]
            artifact_id = artifact["artifact_id"]
            source_url = source["source_url"]
            if source_id in source_ids:
                failures.append(f"{source_id}: duplicate source_id in batch")
            source_ids.add(source_id)
            if artifact_id in artifact_ids:
                failures.append(f"{artifact_id}: duplicate artifact_id in batch")
            artifact_ids.add(artifact_id)
            if source_url in source_urls:
                failures.append(f"{vendor_id}: duplicate source_url in batch: {source_url}")
            source_urls.add(source_url)
            for issue in validate_url_safety(str(source_url)):
                failures.append(f"{vendor_id}: source_url: {issue}")

            for path in (
                ROOT / f"data/vendors/{vendor_id}/sources/{source_id}.yaml",
                ROOT / f"data/vendors/{vendor_id}/artifacts/{artifact_id}.yaml",
            ):
                if operation == "create" and path.exists() and not force:
                    failures.append(f"{path.relative_to(ROOT)} already exists")
                if operation in {"refresh", "deprecate"} and not path.exists():
                    failures.append(f"{path.relative_to(ROOT)} does not exist")
    return failures


def vendor_record(vendor: dict[str, Any], operation: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "vendor_id": vendor["vendor_id"],
        "display_name": vendor["display_name"],
        "legal_name": vendor["legal_name"],
        "headquarters_country": vendor["headquarters_country"],
        "regions_served": vendor["regions_served"],
        "official_domains": vendor["official_domains"],
        "public_entrypoints": vendor["public_entrypoints"],
        "vendor_categories": vendor["vendor_categories"],
        "source_policy": {"public_sources_only": True, "gated_materials_excluded": True, "raw_documents_mirrored_by_default": False},
        "status": vendor.get("status", "deprecated" if operation == "deprecate" else "active"),
        "notes": vendor.get("notes") or f"Public-source catalog record for {vendor['display_name']}.",
    }


def source_record(vendor: dict[str, Any], source: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": source["source_id"],
        "vendor_id": vendor["vendor_id"],
        "source_type": source["source_type"],
        "title_native": source["title_native"],
        "title_en": source.get("title_en"),
        "source_url": source["source_url"],
        "source_language": source["source_language"],
        "access_class": source.get("access_class", "public_web"),
        "rights_class": RIGHTS_CLASS,
        "summary_native": source.get("summary_native"),
        "summary_en": source.get("summary_en"),
        "provenance": {"publisher": "vendor", "collected_at": manifest["collected_at"], "observer": manifest["observer"], "confidence": source.get("confidence", "medium")},
        "not_advice": True,
    }


def artifact_record(vendor: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    artifact = source["artifact"]
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": artifact["artifact_id"],
        "vendor_id": vendor["vendor_id"],
        "source_id": source["source_id"],
        "artifact_type": artifact["artifact_type"],
        "canonical_url": source["source_url"],
        "source_language": source["source_language"],
        "region_scope": artifact.get("region_scope", vendor["regions_served"]),
        "product_scope": artifact.get("product_scope", []),
        "access_class": source.get("access_class", "public_web"),
        "rights_class": RIGHTS_CLASS,
        "effective_or_published_at": artifact.get("effective_or_published_at"),
        "hashes": {"raw_sha256": HASH_TBD, "normalized_text_sha256": HASH_TBD, "hash_method": "metadata_plus_hash_only"},
        "storage": {"raw_document_stored": False, "extracted_text_stored": False, "screenshot_stored": False},
        "not_advice": True,
    }


def generated_paths_for(manifest: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for vendor in manifest["vendors"]:
        vendor_id = vendor["vendor_id"]
        paths.append(ROOT / f"data/vendors/{vendor_id}/vendor.yaml")
        for source in sources_for(vendor):
            paths.append(ROOT / f"data/vendors/{vendor_id}/sources/{source['source_id']}.yaml")
            paths.append(ROOT / f"data/vendors/{vendor_id}/artifacts/{source['artifact']['artifact_id']}.yaml")
            paths.append(ROOT / f"data/vendors/{vendor_id}/changes/{manifest['batch_id']}-{source['source_id']}.yaml")
    return paths


def change_record(manifest: dict[str, Any], vendor: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    operation = manifest["operation"]
    return change_event(
        change_id=f"{manifest['batch_id']}-{source['source_id']}",
        vendor_id=vendor["vendor_id"],
        source_id=source["source_id"],
        artifact_id=source["artifact"]["artifact_id"],
        change_type=lifecycle_change_type(operation),
        detected_at=manifest["collected_at"],
        summary=f"Catalog lifecycle operation {operation} recorded for public source metadata.",
    )


def generate_catalog_batch(manifest_path: Path, *, force: bool = False, build: bool = False) -> int:
    manifest = load_yaml(manifest_path)
    failures = validate_manifest_schema(manifest)
    if not failures:
        failures.extend(validate_manifest_rules(manifest, force=force))
    if failures:
        for failure in failures:
            print(failure)
        print(f"Catalog batch generation failed: {len(failures)} issue(s).")
        return 1

    operation = manifest["operation"]
    write_force = force or operation in {"refresh", "deprecate"}
    for vendor in manifest["vendors"]:
        vendor_id = vendor["vendor_id"]
        write_yaml(ROOT / f"data/vendors/{vendor_id}/vendor.yaml", vendor_record(vendor, operation), force=write_force)
        for source in sources_for(vendor):
            write_yaml(ROOT / f"data/vendors/{vendor_id}/sources/{source['source_id']}.yaml", source_record(vendor, source, manifest), force=write_force)
            write_yaml(ROOT / f"data/vendors/{vendor_id}/artifacts/{source['artifact']['artifact_id']}.yaml", artifact_record(vendor, source), force=write_force)
            write_yaml(ROOT / f"data/vendors/{vendor_id}/changes/{manifest['batch_id']}-{source['source_id']}.yaml", change_record(manifest, vendor, source), force=force)

    if build:
        build_indexes()
    for path in generated_paths_for(manifest):
        print(path.relative_to(ROOT))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-batch")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--force", action="store_true", help="overwrite generated vendor files")
    parser.add_argument("--build-indexes", action="store_true", help="rebuild indexes after generation")
    args = parser.parse_args()
    return generate_catalog_batch(args.manifest, force=args.force, build=args.build_indexes)


if __name__ == "__main__":
    raise SystemExit(main())
