"""Shared, dependency-neutral enrichment authority.

This module is the single authority for the *host-neutral* enrichment contract:
match one bounded vendor identity, filter that vendor's canonical public sources
by requested type, pick the primary source per type, and emit machine-state
notes. It is consumed by both transport adapters that expose enrichment:

- the match service ``/v1/enrich`` HTTP endpoint, and
- the MCP ``enrich_inventory`` tool.

Like :mod:`openva_vendor_inventory_matcher.core`, it has no CSV, pack, FastAPI,
or MCP dependency. Each adapter owns reading its own catalogue representation
(an in-memory pack index or a verified agent-export snapshot) and projecting
source rows; the *decision* — match status, candidate set, which source types
survive the filter, which source is primary per type, and the notes — comes from
here, so the two surfaces agree for the same evidence.

It deliberately performs *identity* matching only (domain / vendor name). Legal-
entity registration resolution is a richer, pack-only capability owned by
``matcher.py`` and is not part of the host-neutral enrichment contract: the
agent-export snapshot carries no legal-entity data, so binding enrichment to it
would make the two surfaces disagree by construction.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from openva_vendor_inventory_matcher.core import (
    VendorRecord,
    classify,
    match_candidates,
    normalize_domain,
    normalize_name,
    select_match,
)

# Canonical source-type -> human label, used only to phrase machine-state notes.
# Never a compliance conclusion. Shared so both surfaces word notes identically.
SOURCE_TYPE_LABELS: dict[str, str] = {
    "dpa": "DPA",
    "subprocessors_list": "subprocessors",
    "privacy_notice": "privacy notice",
    "security_page": "security",
    "trust_center": "trust centre",
    "compliance_page": "compliance",
    "terms_of_service": "terms of service",
    "other_public_source": "other public source",
}


def reverse_date_key(value: str) -> str:
    """Map a date string to a key that sorts newest-first under ascending sort."""
    return "".join(chr(255 - ord(character)) for character in value)


def primary_source_by_type(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Pick one primary source per ``source_type``.

    Deterministic and identity-stable across adapters: prefer a present
    ``effective_or_published_at`` (newest first), then the lowest ``source_id``.
    Missing or null ranking fields are coerced to the empty string so a snapshot
    row that omits a publication date ranks by ``source_id`` rather than raising.
    """
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        source_type = source.get("source_type") or ""
        if source_type:
            by_type[source_type].append(source)
    return {
        source_type: sorted(
            typed_sources,
            key=lambda item: (
                str(item.get("effective_or_published_at") or "") == "",
                reverse_date_key(str(item.get("effective_or_published_at") or "")),
                str(item.get("source_id") or ""),
            ),
        )[0]
        for source_type, typed_sources in sorted(by_type.items())
    }


def match_identity(
    vendors: list[VendorRecord],
    *,
    vendor_name: str | None,
    domain: str | None,
    business_entity_name: str | None,
    registration_number: str | None,
) -> tuple[dict[str, Any], Any]:
    """Resolve one identity through the shared core. Returns (match dict, selected).

    This is the *snapshot-grade* identity matcher: it matches on domain and name
    only. Status, confidence, method, and the candidate set come verbatim from the
    core matcher; ``ambiguous`` is never collapsed into ``matched`` and a weak
    identity stays ``no_match``.

    ``registration_number`` is accepted for signature parity with the shared
    identity contract but is **not** used here: registration-number / legal-entity
    resolution is a pack-backed capability (``MatcherIndex.enrich_row``) that
    depends on legal-entity data the agent-export snapshot does not carry. A surface
    that has that data (the match service over a catalogue pack) runs its own
    capability-aware matcher and feeds the result to :func:`assemble_enrichment`;
    the snapshot-backed MCP surface, which has no legal-entity data, does not. This
    is the honest parity boundary: the *projection* (filtering, ranking, notes) is
    shared and identical; the *matcher capability* follows the data each surface holds.
    """
    domain_normalized = normalize_domain(domain)
    name_normalized = normalize_name(vendor_name) or normalize_name(business_entity_name)
    candidates = match_candidates(vendors, domain_normalized, name_normalized)
    selected = select_match(candidates)
    status = classify(candidates, selected)
    match = {
        "status": status,
        "method": selected.method if selected else None,
        "confidence": selected.confidence if selected else None,
        "vendor_id": selected.vendor.vendor_id if selected else None,
        "display_name": selected.vendor.display_name if selected else None,
        "candidates": [
            {
                "vendor_id": candidate.vendor.vendor_id,
                "display_name": candidate.vendor.display_name,
                "match_confidence": candidate.confidence,
                "match_method": candidate.method,
            }
            for candidate in candidates
        ],
    }
    return match, selected


def build_notes(
    status: str,
    *,
    source_types: list[str] | None,
    primary_by_type: dict[str, dict[str, Any]],
    has_any_sources: bool,
) -> list[str]:
    """Machine-state notes only; never a compliance conclusion, never 'non-compliant'.

    A missing source type is recorded as a neutral coverage fact ("has no canonical
    X source"), not as a deficiency or a pass/fail judgement.
    """
    if status == "ambiguous":
        return ["Ambiguous vendor match"]
    if status != "matched":
        return ["No catalogue match"]
    notes: list[str] = []
    if source_types:
        for source_type in source_types:
            if source_type not in primary_by_type:
                label = SOURCE_TYPE_LABELS.get(source_type, source_type)
                notes.append(f"Matched vendor has no canonical {label} source")
    elif not has_any_sources:
        notes.append("Matched vendor has no canonical sources")
    return notes


def filter_and_rank(
    canonical_sources: list[dict[str, Any]],
    source_types: list[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Filter raw canonical sources by requested type and rank a primary per type.

    Returns (filtered raw rows in input order, primary raw row per type, urls per
    type). ``None`` source_types means all canonical types; an explicit list keeps
    only matching rows and an unknown type simply yields no rows for that type.
    """
    requested = set(source_types) if source_types else None
    filtered = [
        row
        for row in canonical_sources
        if requested is None or row.get("source_type") in requested
    ]
    primary = primary_source_by_type(filtered)
    urls_by_type: dict[str, list[str]] = {}
    for row in filtered:
        source_type = row.get("source_type")
        url = row.get("source_url")
        if source_type and url:
            urls_by_type.setdefault(source_type, []).append(url)
    return filtered, primary, urls_by_type


def assemble_enrichment(
    match: dict[str, Any],
    matched_vendor_id: str | None,
    *,
    sources_for: Callable[[str], list[dict[str, Any]]],
    source_types: list[str] | None = None,
    row_id: str | int | None = None,
    identity: dict[str, Any] | None = None,
    project_source: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the host-neutral enrichment result from an *already-decided* match.

    This is the **shared projection authority**: given a match decision and the
    matched vendor's raw canonical source rows, it performs source-type filtering,
    primary-source ranking, URL grouping, and machine-state notes — identically for
    every surface. The *matcher* that produced ``match`` is the caller's concern and
    may differ in capability (pack-backed legal-entity resolution for the match
    service; snapshot identity matching for MCP); only the projection is shared, so
    parity holds for the same decision and the same sources.

    ``match`` is the match dict (``status`` plus ``vendor_id`` / ``candidates`` …).
    ``sources_for`` returns the matched vendor's raw canonical source rows (each
    needs ``source_type``, ``source_url``, ``source_id``; ``effective_or_published_at``
    is used for ranking when present). ``project_source`` shapes each surviving raw
    row into the adapter's public source view. ``row_id`` and ``identity`` are echoed
    verbatim. No snapshot identity is attached here — the transport discloses that
    once at the response envelope.
    """
    sources: list[dict[str, Any]] = []
    primary_by_type: dict[str, dict[str, Any]] = {}
    urls_by_type: dict[str, list[str]] = {}
    if match.get("status") == "matched" and matched_vendor_id:
        raw = sources_for(matched_vendor_id) or []
        filtered_raw, primary_raw, urls_by_type = filter_and_rank(raw, source_types)
        project = project_source or (lambda row: row)
        sources = [project(row) for row in filtered_raw]
        # Map the ranked raw primary back onto the projected source by source_id so
        # the primary objects are the same projected views as in ``sources``.
        by_id = {source.get("source_id"): source for source in sources if source.get("source_id")}
        primary_by_type = {
            source_type: by_id[chosen.get("source_id")]
            for source_type, chosen in primary_raw.items()
            if chosen.get("source_id") in by_id
        }

    notes = build_notes(
        match.get("status", ""),
        source_types=source_types,
        primary_by_type=primary_by_type,
        has_any_sources=bool(sources),
    )

    return {
        "row_id": row_id,
        "input": identity or {},
        "match": match,
        "sources": sources,
        "primary_source_by_type": primary_by_type,
        "source_urls_by_type": urls_by_type,
        "notes": notes,
        "not_advice": True,
    }


def enrich_identity(
    vendors: list[VendorRecord],
    *,
    sources_for: Callable[[str], list[dict[str, Any]]],
    row_id: str | int | None = None,
    vendor_name: str | None = None,
    domain: str | None = None,
    business_entity_name: str | None = None,
    registration_number: str | None = None,
    source_types: list[str] | None = None,
    project_source: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Snapshot-grade enrichment: match on domain/name, then assemble the result.

    Convenience wrapper for surfaces whose only matcher is the snapshot identity
    matcher (the MCP ``enrich_inventory`` tool). It runs :func:`match_identity` and
    feeds the result to :func:`assemble_enrichment`. Surfaces with a richer,
    capability-aware matcher (the match service's pack-backed
    ``MatcherIndex.enrich_row``) call :func:`assemble_enrichment` directly with their
    own match decision so registration-number / legal-entity matches are preserved.
    """
    match, selected = match_identity(
        vendors,
        vendor_name=vendor_name,
        domain=domain,
        business_entity_name=business_entity_name,
        registration_number=registration_number,
    )
    return assemble_enrichment(
        match,
        selected.vendor.vendor_id if selected else None,
        sources_for=sources_for,
        source_types=source_types,
        row_id=row_id,
        identity={
            "vendor_name": vendor_name,
            "domain": domain,
            "business_entity_name": business_entity_name,
            "registration_number": registration_number,
        },
        project_source=project_source,
    )
