"""Human-facing vendor-list compilation output.

This module keeps matching and source lookup separate from the downloadable CSV
shape. The CSV download is intentionally simple: preserve the uploaded columns
and append compiled vendor/source fields for CISO, DPO, and procurement review.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from typing import Any

from tools.openva import vendor_resolution

RESULT_PACK_VERSION = "2.0.0"

SOURCE_TYPES: tuple[str, ...] = (
    "dpa",
    "subprocessors",
    "privacy_notice",
    "security_or_trust",
    "status_page",
)

RESOLVER_SOURCE_TYPES: tuple[str, ...] = (
    "trust_center",
    "dpa",
    "subprocessors_list",
    "privacy_notice",
    "security_page",
    "status_page",
)

SOURCE_TYPE_ALIASES: dict[str, str] = {
    "subprocessors_list": "subprocessors",
    "trust_center": "security_or_trust",
    "security_page": "security_or_trust",
}

RESOLVER_SOURCE_TYPES_BY_OUTPUT: dict[str, tuple[str, ...]] = {
    "dpa": ("dpa",),
    "subprocessors": ("subprocessors_list",),
    "privacy_notice": ("privacy_notice",),
    "security_or_trust": ("trust_center", "security_page"),
    "status_page": ("status_page",),
}

FLAT_RESULT_COLUMNS: tuple[str, ...] = (
    "compiled_vendor_name",
    "compiled_domain",
    "dpa_url",
    "subprocessors_url",
    "privacy_notice_url",
    "security_or_trust_url",
    "status_page_url",
)


def normalize_source_types(source_types: Iterable[str] | None = None) -> list[str]:
    """Return output source types in deterministic human-template order."""
    if source_types is None:
        return list(SOURCE_TYPES)
    requested: set[str] = set()
    unknown: list[str] = []
    for source_type in source_types:
        canonical = SOURCE_TYPE_ALIASES.get(str(source_type), str(source_type))
        if canonical not in SOURCE_TYPES:
            unknown.append(str(source_type))
        else:
            requested.add(canonical)
    if unknown:
        raise ValueError(f"unsupported vendor compilation source type(s): {', '.join(sorted(unknown))}")
    return [source_type for source_type in SOURCE_TYPES if source_type in requested]


def resolver_source_types(source_types: Iterable[str] | None = None) -> list[str]:
    """Map human-template source types to resolver/catalog source types."""
    output_types = normalize_source_types(source_types)
    requested: list[str] = []
    for output_type in output_types:
        for resolver_type in RESOLVER_SOURCE_TYPES_BY_OUTPUT[output_type]:
            if resolver_type not in requested:
                requested.append(resolver_type)
    return requested


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
    """Resolve input rows, then project them to the compiled vendor-info shape."""
    output_source_types = normalize_source_types(required_source_types)
    requested_resolver_types = resolver_source_types(output_source_types)
    emitter = vendor_resolution.SessionEmitter(
        ingress if ingress is not None else vendor_resolution.RecordingIngress()
    )
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        resolution = vendor_resolution.resolve_vendor_sources(
            {
                "vendor": row,
                "required_source_types": requested_resolver_types,
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
        projected.append(project_resolution(row, index, resolution, output_source_types))
    return projected


def project_resolution(
    input_row: dict[str, Any],
    input_index: int,
    resolution: vendor_resolution.VendorResolution | dict[str, Any],
    required_source_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Project one resolver result into one compiled vendor-info row."""
    payload = resolution.to_response() if hasattr(resolution, "to_response") else dict(resolution)
    vendor = dict(payload.get("vendor") or {})
    source_types = normalize_source_types(required_source_types)
    source_by_type = {
        str(source.get("source_type")): source
        for source in payload.get("sources", [])
        if isinstance(source, dict) and source.get("source_type") in RESOLVER_SOURCE_TYPES
    }
    matched = bool(vendor.get("vendor_id"))
    source_urls = {
        source_type: (
            _source_url_for_output(source_by_type, source_type)
            if matched and source_type in source_types
            else None
        )
        for source_type in SOURCE_TYPES
    }

    return {
        "result_pack_version": RESULT_PACK_VERSION,
        "input_index": input_index,
        "input_vendor_name": _nullable_text(
            input_row.get("vendor_name") or input_row.get("business_entity_name")
        ),
        "input_domain": _nullable_text(input_row.get("domain")),
        "compiled_vendor_name": _nullable_text(vendor.get("display_name")) if matched else None,
        "compiled_domain": _compiled_domain(vendor) if matched else None,
        "dpa_url": source_urls["dpa"],
        "subprocessors_url": source_urls["subprocessors"],
        "privacy_notice_url": source_urls["privacy_notice"],
        "security_or_trust_url": source_urls["security_or_trust"],
        "status_page_url": source_urls["status_page"],
    }


def project_source(
    source: dict[str, Any] | None,
    resolution_status: str,
    source_type: str,
) -> dict[str, Any]:
    """Project one source to the simplified source shape used by the human template."""
    del resolution_status
    output_type = SOURCE_TYPE_ALIASES.get(str(source_type), str(source_type))
    if output_type not in SOURCE_TYPES:
        raise ValueError(f"unsupported vendor compilation source type: {source_type}")
    return {
        "source_type": output_type,
        "url": _source_url(source),
    }


def flatten_result_row(input_row: dict[str, Any], result_row: dict[str, Any]) -> dict[str, Any]:
    """Append deterministic human-download columns to the original row."""
    flattened: dict[str, Any] = dict(input_row)
    for column in FLAT_RESULT_COLUMNS:
        flattened[column] = result_row.get(column)
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


def _source_url_for_output(source_by_type: dict[str, dict[str, Any]], output_source_type: str) -> str | None:
    for resolver_type in RESOLVER_SOURCE_TYPES_BY_OUTPUT[output_source_type]:
        url = _source_url(source_by_type.get(resolver_type))
        if url:
            return url
    return None


def _source_url(source: dict[str, Any] | None) -> str | None:
    if not isinstance(source, dict):
        return None
    return _nullable_text(source.get("source_url") or source.get("candidate_url"))


def _compiled_domain(vendor: dict[str, Any]) -> str | None:
    domain = _nullable_text(vendor.get("official_domain"))
    if domain:
        return domain
    official_domains = vendor.get("official_domains")
    if isinstance(official_domains, list):
        for item in official_domains:
            domain = _nullable_text(item)
            if domain:
                return domain
    return None


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
