"""Inventory matching adapter over the shared matching core.

The matching *decision* (status, vendor id, confidence, method, candidates) is
owned by ``openva_vendor_inventory_matcher.core`` — the same authority the CSV
adapter uses — so both agree for the same evidence and share one vocabulary:
``match_status`` is ``matched``, ``ambiguous``, or ``no_match``. This module only
adapts the verified vendor-index rows into core records and shapes a result.

The hosted export tree carries no legal-entity data, so legal-entity resolution
here is always ``unresolved``; that is the same result the core produces from an
empty legal-entity set.
"""

from __future__ import annotations

from typing import Any

from openva_vendor_inventory_matcher.core import (
    classify,
    match_candidates,
    normalize_domain,
    normalize_name,
    resolve_legal_entity,
    select_match,
    vendor_record,
)


def _vendor_records(vendor_rows: list[dict[str, Any]]) -> list:
    # Map agent-export vendor-index rows onto the core's vendor record. The
    # export has no legal_name, so identity matching relies on id, canonical
    # name, and official domains.
    return [
        vendor_record(
            {
                "vendor_id": row.get("vendor_id"),
                "display_name": row.get("canonical_name"),
                "legal_name": "",
                "official_domains": row.get("domains", []),
                "manifest_path": row.get("export_path", ""),
                "catalog_status": row.get("catalog_status"),
            }
        )
        for row in vendor_rows
    ]


def match_row(vendor_rows: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    vendors = _vendor_records(vendor_rows)
    domain = normalize_domain(row.get("domain"))
    name = normalize_name(row.get("vendor_name")) or normalize_name(row.get("business_entity_name"))
    candidates = match_candidates(vendors, domain, name)
    selected = select_match(candidates)
    status = classify(candidates, selected)
    legal = resolve_legal_entity(row, selected.vendor if selected else None, by_registration={}, by_id={}, contracting_by_key={})
    return {
        "input": row,
        "match_status": status,
        "matched_vendor_id": selected.vendor.vendor_id if selected else None,
        "matched_canonical_name": selected.vendor.display_name if selected else None,
        "match_confidence": selected.confidence if selected else None,
        "match_method": selected.method if selected else None,
        "candidates": [
            {
                "vendor_id": c.vendor.vendor_id,
                "canonical_name": c.vendor.display_name,
                "confidence": c.confidence,
                "method": c.method,
            }
            for c in candidates
        ],
        "legal_entity_resolution": {
            "method": legal.method,
            "confidence": legal.confidence,
            "matched_entity_id": legal.matched_entity.entity_id if legal.matched_entity else None,
        },
    }
