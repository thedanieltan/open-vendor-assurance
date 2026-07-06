"""Resolver-first result-pack projection.

This module freezes the public/browser-facing result shape without changing the
live resolver or the pinned agent-export contract. Python callers use
``vendor_resolution`` as the matching and resolution authority, then this module
projects those results into a compact JSON/CSV contract suitable for static
browser output and Lovable/GitHub Pages integrations.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from typing import Any

from tools.openva import vendor_resolution

RESULT_PACK_VERSION = "1.0.0"

SOURCE_TYPES: tuple[str, ...] = (
    "trust_center",
    "dpa",
    "subprocessors_list",
    "privacy_notice",
    "security_page",
    "status_page",
)

SOURCE_STATUSES: tuple[str, ...] = (
    "found",
    "not_found",
    "gated",
    "unavailable",
    "not_applicable",
    "not_checked",
)

NO_MATCH_REASONS: tuple[str, ...] = (
    "not_in_reference",
    "multiple_plausible_entities",
    "no_public_identity",
    "inconclusive",
)

CANDIDATE_BASES: tuple[str, ...] = (
    "community_hint",
    "vendor_asserted",
    "cached_locator",
    "direct_input",
    "none",
)

VERIFICATION_BASES: tuple[str, ...] = (
    "not_checked",
    "verified_live",
    "live_unavailable",
    "live_gated",
    "live_not_found",
)

FLAT_RESULT_COLUMNS: tuple[str, ...] = (
    "openva_identity_status",
    "openva_no_match_reason",
    "openva_matched_vendor_id",
    "openva_matched_vendor_name",
    *(
        column
        for source_type in SOURCE_TYPES
        for column in (
            f"openva_{source_type}_status",
            f"openva_{source_type}_url",
            f"openva_{source_type}_candidate_basis",
            f"openva_{source_type}_verification_basis",
            f"openva_{source_type}_checked_at",
        )
    ),
    "openva_not_advice",
)


def normalize_source_types(source_types: Iterable[str] | None = None) -> list[str]:
    """Return contract source types in deterministic contract order."""
    if source_types is None:
        return list(SOURCE_TYPES)
    requested = {str(source_type) for source_type in source_types}
    unknown = sorted(requested.difference(SOURCE_TYPES))
    if unknown:
        raise ValueError(f"unsupported resolver result-pack source type(s): {', '.join(unknown)}")
    return [source_type for source_type in SOURCE_TYPES if source_type in requested]


def build_result_pack(
    rows: list[dict[str, Any]],
    required_source_types: Iterable[str] | None,
    *,
    catalog: vendor_resolution.ResolutionCatalog,
    freshness_mode: str = vendor_resolution.FRESHNESS_VERIFY,
    channel: str = vendor_resolution.DEFAULT_CHANNEL,
    fetcher: vendor_resolution.Fetcher | None = None,
    fetcher_factory: vendor_resolution.FetcherFactory = vendor_resolution.default_fetcher_factory,
    discovery: vendor_resolution.DiscoveryFn = vendor_resolution.bounded_discovery,
    ingress: Any | None = None,
    now: Callable[[], str] = vendor_resolution._now_default,
) -> list[dict[str, Any]]:
    """Resolve input rows through the existing resolver, then project them.

    Matching authority remains ``vendor_resolution.resolve_vendor_sources`` and
    the shared inventory matcher it wraps. This function only shapes output.
    """
    source_types = normalize_source_types(required_source_types)
    emitter = vendor_resolution.SessionEmitter(
        ingress if ingress is not None else vendor_resolution.RecordingIngress()
    )
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        resolution = vendor_resolution.resolve_vendor_sources(
            {
                "vendor": row,
                "required_source_types": source_types,
                "freshness_mode": freshness_mode,
                "channel": channel,
            },
            catalog=catalog,
            fetcher=fetcher,
            fetcher_factory=fetcher_factory,
            discovery=discovery,
            emitter=emitter,
            now=now,
        )
        projected.append(project_resolution(row, index, resolution, source_types))
    return projected


def project_resolution(
    input_row: dict[str, Any],
    input_index: int,
    resolution: vendor_resolution.VendorResolution | dict[str, Any],
    required_source_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Project one resolver result into one result-pack row."""
    payload = resolution.to_response() if hasattr(resolution, "to_response") else dict(resolution)
    vendor = dict(payload.get("vendor") or {})
    resolution_status = str(payload.get("resolution_status") or "")
    source_types = normalize_source_types(required_source_types)
    source_by_type = {
        str(source.get("source_type")): source
        for source in payload.get("sources", [])
        if isinstance(source, dict) and source.get("source_type") in SOURCE_TYPES
    }
    identity_status = _identity_status(vendor, resolution_status)
    no_match_reason = None if identity_status == "match" else _no_match_reason(input_row, resolution_status)

    return {
        "result_pack_version": RESULT_PACK_VERSION,
        "input_index": input_index,
        "input_vendor_name": _nullable_text(
            input_row.get("vendor_name") or input_row.get("business_entity_name")
        ),
        "input_domain": _nullable_text(input_row.get("domain")),
        "identity_status": identity_status,
        "no_match_reason": no_match_reason,
        "matched_vendor_id": _nullable_text(vendor.get("vendor_id")),
        "matched_vendor_name": _nullable_text(vendor.get("display_name")),
        "sources": [
            project_source(source_by_type.get(source_type), resolution_status, source_type)
            for source_type in source_types
        ],
        "not_advice": True,
    }


def project_source(
    source: dict[str, Any] | None,
    resolution_status: str,
    source_type: str,
) -> dict[str, Any]:
    """Project one resolver source; candidate inputs never imply live verification."""
    if source is None:
        return {
            "source_type": source_type,
            "status": "not_checked",
            "url": None,
            "candidate_basis": "none",
            "verification_basis": "not_checked",
            "checked_at": None,
        }
    live_checked = bool(source.get("live_checked"))
    status = _source_status(str(source.get("status") or resolution_status), source, live_checked)
    verification_basis = _verification_basis(status, live_checked)
    return {
        "source_type": source_type,
        "status": status,
        "url": _nullable_text(source.get("source_url") or source.get("candidate_url")),
        "candidate_basis": _candidate_basis(source),
        "verification_basis": verification_basis,
        "checked_at": (
            _nullable_text(source.get("checked_at"))
            if verification_basis != "not_checked"
            else None
        ),
    }


def flatten_result_row(input_row: dict[str, Any], result_row: dict[str, Any]) -> dict[str, Any]:
    """Append deterministic ``openva_*`` CSV columns to the original row."""
    flattened: dict[str, Any] = dict(input_row)
    flattened.update(
        {
            "openva_identity_status": result_row["identity_status"],
            "openva_no_match_reason": result_row["no_match_reason"],
            "openva_matched_vendor_id": result_row["matched_vendor_id"],
            "openva_matched_vendor_name": result_row["matched_vendor_name"],
            "openva_not_advice": "true" if result_row["not_advice"] else "false",
        }
    )
    source_by_type = {source["source_type"]: source for source in result_row["sources"]}
    for source_type in SOURCE_TYPES:
        source = source_by_type.get(source_type) or {
            "status": "not_checked",
            "url": None,
            "candidate_basis": "none",
            "verification_basis": "not_checked",
            "checked_at": None,
        }
        flattened[f"openva_{source_type}_status"] = source["status"]
        flattened[f"openva_{source_type}_url"] = source["url"]
        flattened[f"openva_{source_type}_candidate_basis"] = source["candidate_basis"]
        flattened[f"openva_{source_type}_verification_basis"] = source["verification_basis"]
        flattened[f"openva_{source_type}_checked_at"] = source["checked_at"]
    return flattened


def flatten_result_pack(
    input_rows: list[dict[str, Any]], result_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(input_rows) != len(result_rows):
        raise ValueError("input_rows and result_rows must have the same length")
    return [flatten_result_row(input_row, result_row) for input_row, result_row in zip(input_rows, result_rows)]


def flat_csv_columns(input_rows: Iterable[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in input_rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    for key in FLAT_RESULT_COLUMNS:
        if key not in columns:
            columns.append(key)
    return columns


def result_pack_csv(input_rows: list[dict[str, Any]], result_rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = flat_csv_columns(input_rows)
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in flatten_result_pack(input_rows, result_rows):
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in fieldnames})
    return output.getvalue()


def _identity_status(vendor: dict[str, Any], resolution_status: str) -> str:
    if resolution_status == vendor_resolution.RESULT_IDENTITY_AMBIGUOUS:
        return "no_match"
    return "match" if vendor.get("vendor_id") else "no_match"


def _no_match_reason(input_row: dict[str, Any], resolution_status: str) -> str:
    if resolution_status == vendor_resolution.RESULT_IDENTITY_AMBIGUOUS:
        return "multiple_plausible_entities"
    if not (input_row.get("vendor_name") or input_row.get("business_entity_name") or input_row.get("domain")):
        return "no_public_identity"
    if resolution_status == vendor_resolution.RESULT_VERIFICATION_INCONCLUSIVE:
        return "inconclusive"
    return "not_in_reference"


def _source_status(status: str, source: dict[str, Any], live_checked: bool) -> str:
    if not live_checked:
        return "not_checked"
    if status in {
        vendor_resolution.RESULT_CATALOG_CURRENT,
        vendor_resolution.RESULT_CATALOG_REFRESHED,
        vendor_resolution.RESULT_NEWLY_DISCOVERED,
        vendor_resolution.RESULT_CATALOGUED,
    }:
        return "found"
    if status == vendor_resolution.RESULT_SOURCE_UNAVAILABLE:
        return "unavailable"
    if status == vendor_resolution.RESULT_NOT_FOUND:
        return "not_found"
    if status == vendor_resolution.RESULT_CANDIDATE_PROCESSING:
        return "not_checked"
    if status == vendor_resolution.RESULT_VERIFICATION_INCONCLUSIVE:
        reasons = " ".join(str(reason).lower() for reason in source.get("reasons", []))
        if "gated" in reasons or "bot_protected" in reasons:
            return "gated"
        return "unavailable" if source.get("source_url") else "not_checked"
    return "not_checked"


def _candidate_basis(source: dict[str, Any]) -> str:
    explicit = str(source.get("candidate_basis") or "")
    if explicit in CANDIDATE_BASES:
        return explicit
    origin = str(source.get("origin") or "")
    if origin in {"community_hint", "community"}:
        return "community_hint"
    if origin in {"vendor_asserted", "vendor"}:
        return "vendor_asserted"
    if origin == "direct_input":
        return "direct_input"
    if source.get("source_url") or source.get("candidate_url") or source.get("previous_source_url"):
        return "cached_locator"
    return "none"


def _verification_basis(status: str, live_checked: bool) -> str:
    if not live_checked:
        return "not_checked"
    if status == "found":
        return "verified_live"
    if status == "gated":
        return "live_gated"
    if status == "not_found":
        return "live_not_found"
    if status == "unavailable":
        return "live_unavailable"
    return "not_checked"


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
