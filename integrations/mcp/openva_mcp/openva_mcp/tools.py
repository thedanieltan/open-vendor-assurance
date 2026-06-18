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

from openva_vendor_inventory_matcher.enrichment import enrich_identity

from openva_mcp.matching import _vendor_records, match_row
from openva_mcp.snapshot import Snapshot

# Vendor-identity fields a caller may supply for matching. No other field is read,
# so unrelated workspace columns an agent might hold never enter matching.
_IDENTITY_FIELDS = ("vendor_name", "domain", "business_entity_name", "registration_number")


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
        # Tier A disclosure: projected verbatim so consumers can distinguish a
        # legacy export (field absent -> null) from an explicit false. Absence is
        # never "gated content observed"; a true is schema-impossible.
        "verified_scope": row.get("verified_scope"),
        "gated_child_content_observed": row.get("gated_child_content_observed"),
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


def _enrich_source_view(row: dict[str, Any]) -> dict[str, Any]:
    """Project a snapshot source row into the enrichment public source view.

    Preserves the original vendor-published URL and observation provenance; carries
    no vendor identity field beyond the source's own and no workspace metadata.
    """
    return {
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "source_url": row.get("source_url"),
        "canonical_confidence": row.get("canonical_confidence"),
        "retrieval_method": row.get("retrieval_method"),
        "machine_readable": row.get("machine_readable"),
        "source_health": row.get("source_health"),
        "last_observed_at": row.get("last_observed_at"),
        "material_change_since_baseline": row.get("material_change_since_baseline"),
        "verified_scope": row.get("verified_scope"),
        "gated_child_content_observed": row.get("gated_child_content_observed"),
    }


def _has_identity(row: dict[str, Any]) -> bool:
    return any(str(row.get(field) or "").strip() for field in _IDENTITY_FIELDS)


def enrich_inventory(
    snapshot: Snapshot,
    rows: list[dict[str, Any]],
    source_types: list[str] | None = None,
) -> dict[str, Any]:
    """Match a bounded batch of vendor-identity rows and attach public sources.

    This is the composite tool for agents that have already read a user-controlled
    workspace through their own connector: it accepts only bounded vendor-identity
    fields and requested source types, never workspace content. Matching, source-type
    filtering, primary-source ranking, and notes are delegated to the shared
    ``enrich_identity`` authority — the same one the match service ``/v1/enrich``
    endpoint uses — so the two surfaces agree for the same evidence. Input order and
    duplicates are preserved, ``row_id`` is echoed verbatim, ``ambiguous`` stays
    ambiguous, and ``no_match`` stays no-match. The snapshot identity is disclosed
    once on the envelope; OpenVA performs no workspace write and makes no compliance,
    suitability, or risk conclusion.
    """
    for row in rows:
        if not _has_identity(row or {}):
            raise ValueError(
                "each row requires at least one of vendor_name, domain, "
                "business_entity_name, registration_number"
            )

    vendors = _vendor_records(snapshot.vendors_index().get("vendors", []))

    def sources_for(vendor_id: str) -> list[dict[str, Any]]:
        export = snapshot.vendor_export(vendor_id)
        return export.get("sources", []) if export else []

    results = [
        enrich_identity(
            vendors,
            sources_for=sources_for,
            row_id=(row or {}).get("row_id"),
            vendor_name=(row or {}).get("vendor_name"),
            domain=(row or {}).get("domain"),
            business_entity_name=(row or {}).get("business_entity_name"),
            registration_number=(row or {}).get("registration_number"),
            source_types=source_types,
            project_source=_enrich_source_view,
        )
        for row in rows
    ]

    summary = {"matched": 0, "ambiguous": 0, "no_match": 0}
    for result in results:
        summary[result["match"]["status"]] += 1
    return _envelope(
        snapshot,
        count=len(results),
        source_types=source_types,
        summary=summary,
        results=results,
    )


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
