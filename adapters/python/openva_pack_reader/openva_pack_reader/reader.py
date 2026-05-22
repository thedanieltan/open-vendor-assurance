from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PROFILE_ID = "openva.public-metadata.v1"
SCHEMA_VERSION = "openva-export-pack.v1"
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
REQUIRED_GUARANTEES = {
    "public_sources_only": True,
    "metadata_first": True,
    "non_advisory": True,
    "raw_documents_mirrored_by_default": False,
}
ADAPTER_REVIEW_ANNOTATIONS = {
    "canonical": ("human_reviewed", "human_reviewed"),
    "candidate": ("discovery", "human_review_required"),
    "observation": ("observation", "auto_observed"),
}


class PackError(ValueError):
    """Raised when a pack cannot be read under the OpenVA adapter contract."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_pack_root(path_or_dir: str | Path) -> Path:
    path = Path(path_or_dir)
    if path.is_dir():
        return path
    if path.name == "openva-pack.json":
        return path.parent
    raise PackError(f"{path}: expected a pack directory or openva-pack.json")


def relative_pack_path(pack_root: Path, rel_path: str) -> Path:
    path = Path(rel_path)
    if path.is_absolute() or ".." in path.parts:
        raise PackError(f"openva-pack.json: path escapes pack root: {rel_path}")
    resolved = (pack_root / path).resolve()
    root = pack_root.resolve()
    if not str(resolved).startswith(str(root)):
        raise PackError(f"openva-pack.json: path escapes pack root: {rel_path}")
    return resolved


def annotated(record: dict[str, Any], *, record_class: str, canonical: bool) -> dict[str, Any]:
    normalized = copy.deepcopy(record)
    normalized["record_class"] = record_class
    normalized["canonical"] = canonical
    catalog_tier, review_state = ADAPTER_REVIEW_ANNOTATIONS.get(
        record_class,
        ("human_reviewed", "human_reviewed"),
    )
    normalized["catalog_tier"] = catalog_tier
    normalized["review_state"] = review_state
    normalized["advisory_boundary"] = "non_advisory"
    if record_class == "vendor":
        catalog_status = normalized.get("catalog_status", normalized.get("status"))
        if catalog_status is not None:
            normalized["catalog_status"] = catalog_status
    if record_class == "change":
        significance = normalized.get("catalog_change_significance", normalized.get("materiality"))
        if significance is not None:
            normalized["catalog_change_significance"] = significance
    return normalized


class OpenVAPack:
    def __init__(self, pack_root: Path, manifest: dict[str, Any], indexes: dict[str, dict[str, Any]]):
        self.pack_root = pack_root
        self.manifest = manifest
        self.indexes = indexes

    @classmethod
    def load(cls, path_or_dir: str | Path) -> "OpenVAPack":
        pack_root = resolve_pack_root(path_or_dir)
        pack_path = pack_root / "openva-pack.json"
        if not pack_path.exists():
            raise PackError(f"{pack_path}: missing openva-pack.json")

        manifest = load_json(pack_path)
        cls._validate_manifest(manifest)

        indexes: dict[str, dict[str, Any]] = {}
        for key, rel_path in manifest["indexes"].items():
            path = relative_pack_path(pack_root, rel_path)
            if not path.is_file():
                raise PackError(f"openva-pack.json: index path for {key} does not exist: {rel_path}")
            index = load_json(path)
            if not isinstance(index, dict):
                raise PackError(f"{rel_path}: index must be a JSON object")
            indexes[key] = index

        cls._validate_index_counts(indexes)
        return cls(pack_root, manifest, indexes)

    @staticmethod
    def _validate_manifest(manifest: dict[str, Any]) -> None:
        if manifest.get("profileId") != PROFILE_ID:
            raise PackError(f"openva-pack.json: profileId must be {PROFILE_ID}")
        if manifest.get("schemaVersion") != SCHEMA_VERSION:
            raise PackError(f"openva-pack.json: schemaVersion must be {SCHEMA_VERSION}")

        indexes = manifest.get("indexes")
        if not isinstance(indexes, dict):
            raise PackError("openva-pack.json: indexes must be an object")
        missing = sorted(REQUIRED_INDEX_KEYS - set(indexes))
        extra = sorted(set(indexes) - REQUIRED_INDEX_KEYS)
        if missing:
            raise PackError(f"openva-pack.json: missing index keys {missing}")
        if extra:
            raise PackError(f"openva-pack.json: unexpected index keys {extra}")

        guarantees = manifest.get("guarantees")
        if not isinstance(guarantees, dict):
            raise PackError("openva-pack.json: guarantees must be an object")
        for key, expected in REQUIRED_GUARANTEES.items():
            if guarantees.get(key) is not expected:
                raise PackError(f"openva-pack.json: guarantee {key} must be {expected}")

    @staticmethod
    def _validate_index_counts(indexes: dict[str, dict[str, Any]]) -> None:
        for key in REQUIRED_INDEX_KEYS - {"source_coverage", "summary", "contracting_entity_resolution"}:
            index = indexes.get(key)
            if not isinstance(index, dict) or "items" not in index:
                continue
            items = index.get("items")
            if not isinstance(items, list):
                raise PackError(f"{key}: items must be a list")
            if index.get("count") != len(items):
                raise PackError(f"{key}: count {index.get('count')} does not match item count {len(items)}")

    def _items(self, key: str) -> list[dict[str, Any]]:
        items = self.indexes[key].get("items", [])
        if not isinstance(items, list):
            raise PackError(f"{key}: items must be a list")
        return copy.deepcopy(items)

    def vendors(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="vendor", canonical=False) for item in self._items("vendors")]

    def canonical_sources(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="canonical", canonical=True) for item in self._items("sources")]

    def artifacts(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="artifact", canonical=False) for item in self._items("artifacts")]

    def observations(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="observation", canonical=False) for item in self._items("observations")]

    def changes(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="change", canonical=False) for item in self._items("changes")]

    def legal_entities(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="legal_entity", canonical=False) for item in self._items("legal_entities")]

    def candidate_sources(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="candidate", canonical=False) for item in self._items("candidate_sources")]

    def unavailable_sources(self) -> list[dict[str, Any]]:
        return [annotated(item, record_class="unavailable", canonical=False) for item in self._items("unavailable_sources")]

    def source_coverage(self) -> dict[str, Any]:
        coverage = copy.deepcopy(self.indexes["source_coverage"])
        rows = coverage.get("vendor_coverage", [])
        if isinstance(rows, list):
            coverage["vendor_coverage"] = [annotated(row, record_class="coverage", canonical=False) for row in rows]
        return coverage

    def contracting_entity_resolution(self) -> dict[str, Any]:
        return copy.deepcopy(self.indexes["contracting_entity_resolution"])

    def vendor_search(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._items("vendor_search"))

    def vendor(self, vendor_id: str) -> dict[str, Any]:
        search_rows = {item["vendor_id"]: item for item in self.vendor_search() if item.get("vendor_id")}
        row = search_rows.get(vendor_id)
        if not row:
            raise PackError(f"{vendor_id}: vendor not found")
        manifest_path = row.get("manifest_path")
        if not isinstance(manifest_path, str):
            raise PackError(f"{vendor_id}: manifest_path must be a string")
        manifest = load_json(relative_pack_path(self.pack_root, manifest_path))
        if not isinstance(manifest, dict):
            raise PackError(f"{manifest_path}: vendor manifest must be an object")
        return self._annotated_manifest(manifest)

    def _annotated_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(manifest)
        if isinstance(normalized.get("vendor"), dict):
            normalized["vendor"] = annotated(normalized["vendor"], record_class="vendor", canonical=False)
        for key, record_class, canonical in [
            ("canonical_sources", "canonical", True),
            ("artifacts", "artifact", False),
            ("observations", "observation", False),
            ("changes", "change", False),
            ("candidate_sources", "candidate", False),
            ("unavailable_sources", "unavailable", False),
        ]:
            records = normalized.get(key, [])
            if isinstance(records, list):
                normalized[key] = [
                    annotated(record, record_class=record_class, canonical=canonical)
                    for record in records
                    if isinstance(record, dict)
                ]
        return normalized
