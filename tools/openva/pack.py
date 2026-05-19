from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, ROOT

PACK_PATH = ROOT / "openva-pack.json"
REQUIRED_INDEX_KEYS = {
    "vendors",
    "sources",
    "artifacts",
    "observations",
    "changes",
    "legal_entities",
    "entity_mentions",
    "candidate_sources",
    "unavailable_sources",
    "summary",
    "vendor_search",
    "source_coverage",
    "contracting_entity_resolution",
}
REQUIRED_REGISTRY_OUTPUT_KEYS = {"vendor_manifests"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def pack_digest() -> str:
    pack = load_json(PACK_PATH)
    digest_material: dict[str, Any] = {"openva-pack.json": pack}

    for key in sorted(pack.get("indexes", {})):
        rel_path = pack["indexes"][key]
        digest_material[rel_path] = load_json(ROOT / rel_path)
    registry_outputs = pack.get("registry_outputs", {})
    if registry_outputs.get("vendor_manifests") == "dist/vendors/{vendor_id}.json":
        for path in sorted((ROOT / "dist" / "vendors").glob("*.json")):
            rel_path = path.relative_to(ROOT).as_posix()
            digest_material[rel_path] = load_json(path)

    return sha256_bytes(canonical_json(digest_material))


def verify_export_contract(pack: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if pack.get("profileId") != EXPORT_PROFILE_ID:
        failures.append(f"openva-pack.json: profileId must be {EXPORT_PROFILE_ID}")
    if pack.get("schemaVersion") != EXPORT_SCHEMA_VERSION:
        failures.append(f"openva-pack.json: schemaVersion must be {EXPORT_SCHEMA_VERSION}")
    if pack.get("packId") != pack.get("pack_id"):
        failures.append("openva-pack.json: packId must match pack_id during transition")
    if pack.get("generatedAt") != pack.get("generated_at"):
        failures.append("openva-pack.json: generatedAt must match generated_at during transition")
    return failures


def verify_pack_integrity() -> list[str]:
    failures: list[str] = []

    if not PACK_PATH.exists():
        return ["openva-pack.json is missing"]

    pack = load_json(PACK_PATH)
    failures.extend(verify_export_contract(pack))

    indexes = pack.get("indexes")
    if not isinstance(indexes, dict):
        return [*failures, "openva-pack.json: indexes must be an object"]

    registry_outputs = pack.get("registry_outputs")
    if not isinstance(registry_outputs, dict):
        failures.append("openva-pack.json: registry_outputs must be an object")
        registry_outputs = {}

    missing_keys = sorted(REQUIRED_INDEX_KEYS - set(indexes))
    extra_keys = sorted(set(indexes) - REQUIRED_INDEX_KEYS)
    if missing_keys:
        failures.append(f"openva-pack.json: missing index keys {missing_keys}")
    if extra_keys:
        failures.append(f"openva-pack.json: unexpected index keys {extra_keys}")

    missing_registry_keys = sorted(REQUIRED_REGISTRY_OUTPUT_KEYS - set(registry_outputs))
    extra_registry_keys = sorted(set(registry_outputs) - REQUIRED_REGISTRY_OUTPUT_KEYS)
    if missing_registry_keys:
        failures.append(f"openva-pack.json: missing registry output keys {missing_registry_keys}")
    if extra_registry_keys:
        failures.append(f"openva-pack.json: unexpected registry output keys {extra_registry_keys}")
    if registry_outputs.get("vendor_manifests") != "dist/vendors/{vendor_id}.json":
        failures.append("openva-pack.json: registry_outputs.vendor_manifests must be dist/vendors/{vendor_id}.json")

    loaded_indexes: dict[str, Any] = {}
    for key, rel_path in indexes.items():
        path = ROOT / rel_path
        resolved_path = path.resolve()
        resolved_root = ROOT.resolve()
        if not str(resolved_path).startswith(str(resolved_root)):
            failures.append(f"openva-pack.json: index path for {key} escapes repository root: {rel_path}")
            continue
        if not path.exists():
            failures.append(f"openva-pack.json: index path for {key} does not exist: {rel_path}")
            continue
        if not path.is_file():
            failures.append(f"openva-pack.json: index path for {key} is not a file: {rel_path}")
            continue
        loaded_indexes[key] = load_json(path)

    for key in [
        "vendors",
        "sources",
        "artifacts",
        "observations",
        "changes",
        "legal_entities",
        "entity_mentions",
        "candidate_sources",
        "unavailable_sources",
    ]:
        index = loaded_indexes.get(key)
        if not index:
            continue
        items = index.get("items")
        count = index.get("count")
        if not isinstance(items, list):
            failures.append(f"indexes/{key}.json: items must be a list")
            continue
        if count != len(items):
            failures.append(f"indexes/{key}.json: count {count} does not match item count {len(items)}")

    summary = loaded_indexes.get("summary")
    if isinstance(summary, dict):
        counts = summary.get("counts", {})
        count_key_map = {
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
        for summary_key, index_key in count_key_map.items():
            index = loaded_indexes.get(index_key)
            if not index:
                continue
            expected = index.get("count")
            actual = counts.get(summary_key)
            if actual != expected:
                failures.append(f"indexes/summary.json: count for {summary_key} {actual} does not match {index_key} count {expected}")

    vendor_search = loaded_indexes.get("vendor_search")
    if isinstance(vendor_search, dict):
        manifests = vendor_search.get("items", [])
        if isinstance(manifests, list):
            for item in manifests:
                manifest_path = item.get("manifest_path") if isinstance(item, dict) else None
                if not isinstance(manifest_path, str):
                    failures.append("indexes/vendor-search.json: manifest_path must be a string")
                    continue
                path = ROOT / manifest_path
                if not path.exists():
                    failures.append(f"indexes/vendor-search.json: manifest path does not exist: {manifest_path}")

    guarantees = pack.get("guarantees", {})
    for guarantee in ["public_sources_only", "metadata_first", "non_advisory"]:
        if guarantees.get(guarantee) is not True:
            failures.append(f"openva-pack.json: guarantee {guarantee} must be true")
    if guarantees.get("raw_documents_mirrored_by_default") is not False:
        failures.append("openva-pack.json: raw_documents_mirrored_by_default must be false")

    return failures


def main() -> int:
    failures = verify_pack_integrity()
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(pack_digest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
