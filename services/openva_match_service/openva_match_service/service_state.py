from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openva_pack_reader import OpenVAPack
from openva_vendor_inventory_matcher.matcher import MatcherIndex


@dataclass(frozen=True)
class PackMeta:
    profile_id: str
    schema_version: str
    generated_at: str
    counts: dict[str, int]
    non_advisory: bool = True


@dataclass(frozen=True)
class ServiceState:
    pack: OpenVAPack
    matcher_index: MatcherIndex
    meta: PackMeta
    # Deterministic SHA-256 over the loaded pack manifest + referenced index files
    # (prefixed "sha256:"). This is a content snapshot identity, NOT a git commit SHA.
    snapshot_digest: str = "sha256:"
    # Latest observation per source_id (by observed_at). Empty when the loaded pack
    # carries no observations. Built once at startup; immutable thereafter.
    latest_observation_by_source: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Manifest-declared guarantees from the loaded pack (authoritative, not hardcoded).
    guarantees: dict[str, bool] = field(default_factory=dict)


def load_service_state(pack_path: str) -> ServiceState:
    pack = OpenVAPack.load(pack_path)
    return ServiceState(
        pack=pack,
        matcher_index=MatcherIndex.from_pack(pack),
        meta=pack_meta(pack),
        snapshot_digest=compute_snapshot_digest(pack),
        latest_observation_by_source=build_latest_observation_by_source(pack),
        guarantees=load_guarantees(pack),
    )


def pack_meta(pack: OpenVAPack) -> PackMeta:
    manifest = pack.manifest
    return PackMeta(
        profile_id=str(manifest.get("profileId", "")),
        schema_version=str(manifest.get("schemaVersion", "")),
        generated_at=str(manifest.get("generated_at") or manifest.get("generatedAt") or ""),
        counts={
            "vendors": index_count(pack.indexes.get("vendors")),
            "sources": index_count(pack.indexes.get("sources")),
            "candidate_sources": index_count(pack.indexes.get("candidate_sources")),
            "unavailable_sources": index_count(pack.indexes.get("unavailable_sources")),
        },
    )


def index_count(index: dict[str, Any] | None) -> int:
    if not isinstance(index, dict):
        return 0
    count = index.get("count")
    return count if isinstance(count, int) else 0


def load_guarantees(pack: OpenVAPack) -> dict[str, bool]:
    raw = pack.manifest.get("guarantees")
    if not isinstance(raw, dict):
        return {}
    return {str(key): bool(value) for key, value in raw.items()}


def compute_snapshot_digest(pack: OpenVAPack) -> str:
    """Deterministic content digest of the loaded pack.

    Hashes the raw bytes of ``openva-pack.json`` plus every referenced index file,
    in deterministic (sorted relative-path) order, with unambiguous path boundaries
    so two different file layouts cannot collide. Computed once at startup. This is a
    snapshot identity, not a git commit SHA.
    """
    digest = hashlib.sha256()
    entries: list[tuple[str, Path]] = [("openva-pack.json", pack.pack_root / "openva-pack.json")]
    indexes = pack.manifest.get("indexes", {})
    if isinstance(indexes, dict):
        for rel_path in sorted(str(value) for value in indexes.values()):
            entries.append((rel_path, pack.pack_root / rel_path))
    for rel_path, path in sorted(entries, key=lambda item: item[0]):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


def build_latest_observation_by_source(pack: OpenVAPack) -> dict[str, dict[str, Any]]:
    """Latest observation per source_id, by observed_at. Deterministic; empty when the
    pack has no observations. Observations without a source_id cannot be attributed to a
    source and are skipped (per-source observation is null for them)."""
    latest: dict[str, dict[str, Any]] = {}
    for row in pack.observations():
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            continue
        observed_at = str(row.get("observed_at") or "")
        current = latest.get(source_id)
        if current is None or observed_at > str(current.get("observed_at") or ""):
            latest[source_id] = row
    return latest
