"""Read-only tool implementations over a verified snapshot.

Each function is a pure transformation of a loaded ``Snapshot`` and returns a
plain dict (the MCP layer in ``server.py`` is a thin wrapper). Every result
carries the snapshot identity and ``not_advice=true``; every source-oriented
result preserves the original vendor-published URL, observed health and last
observation where known. Nothing here mutates state, scores, ranks, or reaches
GitHub.
"""

from __future__ import annotations

from typing import Any

from openva_mcp.matching import match_row
from openva_mcp.snapshot import Snapshot


def _envelope(snapshot: Snapshot, **payload: Any) -> dict[str, Any]:
    return {
        **payload,
        "snapshot": {
            "mode": snapshot.mode,
            "commit_sha": snapshot.commit_sha,
            "digest": snapshot.digest,
            "generated_at": snapshot.generated_at,
            "from_cache": snapshot.from_cache,
        },
        "not_advice": True,
    }


def _source_view(vendor_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """A source row with vendor_id guaranteed present and field order stable."""
    return {
        "vendor_id": vendor_id,
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "source_url": row.get("source_url"),
        "canonical_confidence": row.get("canonical_confidence"),
        "retrieval_method": row.get("retrieval_method"),
        "machine_readable": row.get("machine_readable"),
        "source_health": row.get("source_health"),
        "last_observed_at": row.get("last_observed_at"),
        "material_change_since_baseline": row.get("material_change_since_baseline"),
    }


def search_vendors(snapshot: Snapshot, query: str | None = None, limit: int = 50) -> dict[str, Any]:
    rows = snapshot.vendors_index().get("vendors", [])
    if query:
        needle = query.strip().lower()
        rows = [
            row
            for row in rows
            if needle in str(row.get("vendor_id", "")).lower()
            or needle in str(row.get("canonical_name", "")).lower()
            or any(needle in str(domain).lower() for domain in row.get("domains", []))
        ]
    total = len(rows)
    rows = rows[: max(0, int(limit))]
    return _envelope(snapshot, query=query, count=len(rows), total_matches=total, vendors=rows)


def get_vendor(snapshot: Snapshot, vendor_id: str) -> dict[str, Any]:
    vendor = snapshot.vendor_export(vendor_id)
    if vendor is None:
        return _envelope(snapshot, vendor_id=vendor_id, found=False, vendor=None)
    return _envelope(snapshot, vendor_id=vendor_id, found=True, vendor=vendor)


def list_vendor_sources(snapshot: Snapshot, vendor_id: str) -> dict[str, Any]:
    vendor = snapshot.vendor_export(vendor_id)
    if vendor is None:
        return _envelope(snapshot, vendor_id=vendor_id, found=False, sources=[])
    sources = [_source_view(vendor_id, row) for row in vendor.get("sources", [])]
    return _envelope(snapshot, vendor_id=vendor_id, found=True, count=len(sources), sources=sources)


def get_source(snapshot: Snapshot, source_id: str) -> dict[str, Any]:
    for row in snapshot.sources_index().get("sources", []):
        if row.get("source_id") == source_id:
            return _envelope(
                snapshot,
                source_id=source_id,
                found=True,
                source=_source_view(str(row.get("vendor_id") or ""), row),
            )
    return _envelope(snapshot, source_id=source_id, found=False, source=None)


def get_source_health(snapshot: Snapshot, source_id: str) -> dict[str, Any]:
    # Prefer the richer observation row; fall back to the source row's health.
    for row in snapshot.observations_latest().get("sources", []):
        if row.get("source_id") == source_id:
            return _envelope(
                snapshot,
                source_id=source_id,
                found=True,
                vendor_id=row.get("vendor_id"),
                source_url=row.get("source_url"),
                source_health=row.get("source_health"),
                last_observed_at=row.get("observed_at"),
                http_status=row.get("http_status"),
                final_url=row.get("final_url"),
                freshness=row.get("freshness"),
                observation_input=snapshot.observations_latest().get("observation_input"),
            )
    for row in snapshot.sources_index().get("sources", []):
        if row.get("source_id") == source_id:
            return _envelope(
                snapshot,
                source_id=source_id,
                found=True,
                vendor_id=row.get("vendor_id"),
                source_url=row.get("source_url"),
                source_health=row.get("source_health"),
                last_observed_at=row.get("last_observed_at"),
                http_status=None,
                final_url=None,
                freshness=None,
                observation_input=snapshot.observations_latest().get("observation_input"),
            )
    return _envelope(snapshot, source_id=source_id, found=False)


def get_vendor_changes(snapshot: Snapshot, vendor_id: str) -> dict[str, Any]:
    rows = [row for row in snapshot.changes_latest().get("sources", []) if row.get("vendor_id") == vendor_id]
    return _envelope(snapshot, vendor_id=vendor_id, count=len(rows), changes=rows)


def match_inventory(snapshot: Snapshot, rows: list[dict[str, Any]]) -> dict[str, Any]:
    vendors = snapshot.vendors_index().get("vendors", [])
    results = [match_row(vendors, row or {}) for row in rows]
    summary = {"matched": 0, "ambiguous": 0, "no_match": 0}
    for result in results:
        summary[result["match_status"]] += 1
    return _envelope(snapshot, count=len(results), summary=summary, results=results)


def get_snapshot_metadata(snapshot: Snapshot) -> dict[str, Any]:
    index = snapshot.agent_index
    return _envelope(
        snapshot,
        counts=index.get("counts"),
        guarantees=index.get("guarantees"),
        observation_input=index.get("observation_input"),
        vendor_export_count=len(snapshot.vendor_export_paths()),
    )


def verify_snapshot(snapshot: Snapshot) -> dict[str, Any]:
    return _envelope(snapshot, verification=snapshot.verify())
