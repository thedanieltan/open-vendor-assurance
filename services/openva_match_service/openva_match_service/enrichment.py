"""Read-only projection logic for the /v1 enrichment API.

Everything here operates on the immutable ServiceState loaded at startup. It reuses the
existing matcher (identity semantics + primary-source ranking) and the pack reader's
canonical annotations. It performs no network I/O, no persistence, and no catalogue
mutation. Internal pack filesystem paths are never exposed.
"""

from __future__ import annotations

import json
from typing import Any

from openva_vendor_inventory_matcher.matcher import canonical_source_json, primary_source_by_type

from .config import ServiceConfig
from .service_state import ServiceState

# Stable spreadsheet column -> canonical source type. One mapping shared by every
# integration. If the canonical vocabulary changes, preserve the real vocabulary here.
SPREADSHEET_TYPE_MAP: dict[str, str] = {
    "openva_dpa": "dpa",
    "openva_subprocessors": "subprocessors_list",
    "openva_privacy_notice": "privacy_notice",
    "openva_security": "security_page",
    "openva_trust_center": "trust_center",
    "openva_compliance": "compliance_page",
}

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


def strip_internal(record: dict[str, Any]) -> dict[str, Any]:
    """Drop internal keys (e.g. _openva_path) so no pack filesystem path leaks."""
    return {key: value for key, value in record.items() if not str(key).startswith("_")}


def build_snapshot(state: ServiceState, config: ServiceConfig) -> dict[str, Any]:
    meta = state.meta
    return {
        "profile_id": meta.profile_id,
        "schema_version": meta.schema_version,
        "generated_at": meta.generated_at,
        "vendor_count": int(meta.counts.get("vendors", 0)),
        "source_count": int(meta.counts.get("sources", 0)),
        "snapshot_digest": state.snapshot_digest,
        "catalog_commit_sha": config.catalog_commit_sha,
    }


def project_source(raw: dict[str, Any], state: ServiceState) -> dict[str, Any]:
    """Normalize one canonical source row into the public source model.

    Observation fields come only from the loaded observations index (per source_id) and
    are null when no deterministic observation exists. No live URL check is performed."""
    source_id = raw.get("source_id")
    observation = state.latest_observation_by_source.get(source_id) if isinstance(source_id, str) else None
    return {
        "source_id": _scalar(raw.get("source_id")),
        "source_type": _scalar(raw.get("source_type")),
        "source_url": _scalar(raw.get("source_url")),
        "access_class": _scalar(raw.get("access_class")),
        "source_language": _scalar(raw.get("source_language")),
        "catalog_status": _scalar(raw.get("catalog_status")),
        "record_class": _scalar(raw.get("record_class")),
        "canonical": raw.get("canonical") if isinstance(raw.get("canonical"), bool) else None,
        "catalog_tier": _scalar(raw.get("catalog_tier")),
        "review_state": _scalar(raw.get("review_state")),
        "advisory_boundary": _scalar(raw.get("advisory_boundary")),
        "last_observed_at": _scalar(observation.get("observed_at")) if observation else None,
        "latest_observation_status": _scalar(observation.get("result")) if observation else None,
    }


def match_one(
    state: ServiceState,
    *,
    vendor_name: str | None,
    domain: str | None,
    business_entity_name: str | None,
    registration_number: str | None,
) -> dict[str, Any]:
    """Resolve one identity through the existing matcher. Status/method/confidence are
    taken verbatim from the matcher; ambiguous is never collapsed into matched."""
    enriched = state.matcher_index.enrich_row(
        {
            "vendor_name": vendor_name or "",
            "domain": domain or "",
            "business_entity_name": business_entity_name or "",
            "registration_number": registration_number or "",
        }
    )
    confidence_cell = enriched.get("match_confidence") or ""
    candidates_cell = enriched.get("candidate_matches_json") or "[]"
    return {
        "status": enriched.get("match_status") or "no_match",
        "method": enriched.get("match_method") or None,
        "confidence": float(confidence_cell) if confidence_cell != "" else None,
        "vendor_id": enriched.get("matched_vendor_id") or None,
        "display_name": enriched.get("matched_display_name") or None,
        "candidates": json.loads(candidates_cell),
    }


def vendor_sources(
    state: ServiceState, vendor_id: str, source_types: list[str] | None
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Return (canonical sources after type filter, primary source per type, urls per type).

    Primary selection reuses the matcher's existing ranking; no competing ranking is
    introduced. Candidate sources are never included."""
    raw_sources = state.matcher_index.canonical_sources_by_vendor.get(vendor_id, [])
    requested = set(source_types) if source_types else None
    filtered_raw = [row for row in raw_sources if requested is None or row.get("source_type") in requested]

    sources = [project_source(row, state) for row in filtered_raw]

    # Reuse the matcher's primary-source-by-type ranking, then map back to the public
    # source model by source_id.
    ranking_input = [canonical_source_json(row) for row in filtered_raw]
    primary_ranked = primary_source_by_type(ranking_input)
    by_id = {source["source_id"]: source for source in sources if source.get("source_id")}
    primary_by_type = {
        source_type: by_id[chosen["source_id"]]
        for source_type, chosen in primary_ranked.items()
        if chosen.get("source_id") in by_id
    }

    urls_by_type: dict[str, list[str]] = {}
    for source in sources:
        source_type = source.get("source_type")
        url = source.get("source_url")
        if source_type and url:
            urls_by_type.setdefault(source_type, []).append(url)

    return sources, primary_by_type, urls_by_type


def build_notes(
    status: str,
    *,
    source_types: list[str] | None,
    primary_by_type: dict[str, dict[str, Any]],
    has_any_sources: bool,
) -> list[str]:
    """Machine-state notes only; never a compliance conclusion, never 'non-compliant'."""
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


def build_spreadsheet(
    match: dict[str, Any],
    primary_by_type: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    snapshot_digest: str,
    notes: list[str],
) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "openva_match_status": match["status"],
        "openva_vendor_id": match.get("vendor_id"),
        "openva_vendor_name": match.get("display_name"),
    }
    for column, source_type in SPREADSHEET_TYPE_MAP.items():
        chosen = primary_by_type.get(source_type)
        projection[column] = chosen.get("source_url") if chosen else None
    observed = [s.get("last_observed_at") for s in sources if s.get("last_observed_at")]
    projection["openva_last_observed_at"] = max(observed) if observed else None
    projection["openva_snapshot_digest"] = snapshot_digest
    projection["openva_notes"] = "; ".join(notes)
    return projection


def enrich_one(
    state: ServiceState,
    *,
    row_id: str | int | None,
    vendor_name: str | None,
    domain: str | None,
    business_entity_name: str | None,
    registration_number: str | None,
    source_types: list[str] | None,
) -> dict[str, Any]:
    match = match_one(
        state,
        vendor_name=vendor_name,
        domain=domain,
        business_entity_name=business_entity_name,
        registration_number=registration_number,
    )
    sources: list[dict[str, Any]] = []
    primary_by_type: dict[str, dict[str, Any]] = {}
    urls_by_type: dict[str, list[str]] = {}
    if match["status"] == "matched" and match.get("vendor_id"):
        sources, primary_by_type, urls_by_type = vendor_sources(state, match["vendor_id"], source_types)

    notes = build_notes(
        match["status"],
        source_types=source_types,
        primary_by_type=primary_by_type,
        has_any_sources=bool(sources),
    )
    spreadsheet = build_spreadsheet(match, primary_by_type, sources, state.snapshot_digest, notes)
    return {
        "row_id": row_id,
        "input": {
            "vendor_name": vendor_name,
            "domain": domain,
            "business_entity_name": business_entity_name,
            "registration_number": registration_number,
        },
        "match": match,
        "sources": sources,
        "primary_source_by_type": primary_by_type,
        "source_urls_by_type": urls_by_type,
        "spreadsheet": spreadsheet,
        "notes": notes,
        "not_advice": True,
    }


def vendor_detail(state: ServiceState, vendor_id: str) -> dict[str, Any]:
    """Vendor object + canonical sources from the pack reader's vendor accessor.

    Raises the pack reader's PackError for an unknown vendor (the route maps it to 404).
    Internal filesystem paths are stripped; candidate sources are not included here."""
    manifest = state.pack.vendor(vendor_id)
    vendor_obj = manifest.get("vendor") if isinstance(manifest.get("vendor"), dict) else {}
    canonical = manifest.get("canonical_sources") or []
    sources = [project_source(row, state) for row in canonical if isinstance(row, dict)]
    return {
        "vendor": strip_internal(vendor_obj),
        "canonical_sources": sources,
    }


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
