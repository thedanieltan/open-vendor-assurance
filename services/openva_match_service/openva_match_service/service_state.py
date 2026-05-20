from __future__ import annotations

from dataclasses import dataclass
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


def load_service_state(pack_path: str) -> ServiceState:
    pack = OpenVAPack.load(pack_path)
    return ServiceState(
        pack=pack,
        matcher_index=MatcherIndex.from_pack(pack),
        meta=pack_meta(pack),
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
