"""Local CSV compiler for human-facing vendor information downloads."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from tools.openva import resolver_result_pack as pack

ROOT = Path(__file__).resolve().parents[2]
MATCHER_PATH = ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher"
if str(MATCHER_PATH) not in sys.path:
    sys.path.insert(0, str(MATCHER_PATH))

from openva_vendor_inventory_matcher import core as matcher  # noqa: E402

INPUT_COLUMNS: tuple[str, ...] = (
    "vendor_name",
    "business_entity_name",
    "domain",
    "jurisdiction",
    "registration_number",
    "registered_address",
)


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [_clean_csv_row(row) for row in reader]


def load_vendor_match_index(catalog_root: Path = ROOT) -> dict[str, Any]:
    path = catalog_root / "indexes" / "vendor-match-index.json"
    return json.loads(path.read_text(encoding="utf-8"))


def compile_rows(
    input_rows: list[dict[str, Any]],
    source_types: list[str] | tuple[str, ...] | None = None,
    *,
    catalog_root: Path = ROOT,
) -> list[dict[str, Any]]:
    """Compile local CSV rows into simple vendor information rows."""
    requested_source_types = pack.normalize_source_types(source_types)
    index = load_vendor_match_index(catalog_root)
    vendors = [item for item in index.get("items", []) if isinstance(item, dict)]
    matcher_records = [matcher.vendor_record(vendor) for vendor in vendors]
    vendors_by_id = {str(vendor.get("vendor_id")): vendor for vendor in vendors if vendor.get("vendor_id")}

    rows: list[dict[str, Any]] = []
    for input_index, input_row in enumerate(input_rows):
        selected = matcher.select_match(_match_candidates(input_row, matcher_records))
        rows.append(_result_row(input_row, input_index, selected, vendors_by_id, requested_source_types))
    return rows


def compile_csv(
    input_csv: Path,
    *,
    source_types: list[str] | tuple[str, ...] | None,
    out_json: Path,
    out_csv: Path,
    catalog_root: Path = ROOT,
) -> list[dict[str, Any]]:
    input_rows = read_csv_rows(input_csv)
    result_rows = compile_rows(input_rows, source_types, catalog_root=catalog_root)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result_rows, indent=2) + "\n", encoding="utf-8")
    out_csv.write_text(pack.result_pack_csv(input_rows, result_rows), encoding="utf-8", newline="")
    return result_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.openva.resolve_csv",
        description="Compile a local vendor CSV into a structured vendor information JSON and CSV.",
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument(
        "--source-types",
        default=",".join(pack.SOURCE_TYPES),
        help="Comma-separated source types to include in the compiled source columns.",
    )
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-csv", required=True, type=Path)
    parser.add_argument("--catalog-root", default=ROOT, type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    source_types = _parse_source_types(args.source_types)
    compile_csv(
        args.input_csv,
        source_types=source_types,
        out_json=args.out_json,
        out_csv=args.out_csv,
        catalog_root=args.catalog_root,
    )
    return 0


def _clean_csv_row(row: dict[str | None, str | None]) -> dict[str, Any]:
    return {str(key): value for key, value in row.items() if key is not None}


def _parse_source_types(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _match_candidates(
    input_row: dict[str, Any],
    matcher_records: list[matcher.VendorRecord],
) -> list[matcher.MatchCandidate]:
    name = matcher.normalize_name(input_row.get("vendor_name") or input_row.get("business_entity_name"))
    domain = matcher.normalize_domain(input_row.get("domain"))
    return matcher.match_candidates(matcher_records, domain, name)


def _result_row(
    input_row: dict[str, Any],
    input_index: int,
    selected: matcher.MatchCandidate | None,
    vendors_by_id: dict[str, dict[str, Any]],
    source_types: list[str],
) -> dict[str, Any]:
    vendor = vendors_by_id.get(selected.vendor.vendor_id) if selected is not None else None
    source_urls = {
        source_type: _source_url_for_output(vendor, source_type) if vendor and source_type in source_types else None
        for source_type in pack.SOURCE_TYPES
    }
    return {
        "result_pack_version": pack.RESULT_PACK_VERSION,
        "input_index": input_index,
        "input_vendor_name": _nullable_text(input_row.get("vendor_name") or input_row.get("business_entity_name")),
        "input_domain": _nullable_text(input_row.get("domain")),
        "compiled_vendor_name": _nullable_text(vendor.get("display_name")) if vendor else None,
        "compiled_domain": _compiled_domain(vendor) if vendor else None,
        "dpa_url": source_urls["dpa"],
        "subprocessors_url": source_urls["subprocessors"],
        "privacy_notice_url": source_urls["privacy_notice"],
        "security_or_trust_url": source_urls["security_or_trust"],
        "status_page_url": source_urls["status_page"],
    }


def _source_url_for_output(vendor: dict[str, Any] | None, output_source_type: str) -> str | None:
    if vendor is None:
        return None
    for resolver_type in pack.RESOLVER_SOURCE_TYPES_BY_OUTPUT[output_source_type]:
        source = _source_for_type(vendor, resolver_type)
        url = _source_url(source)
        if url:
            return url
    return None


def _source_for_type(vendor: dict[str, Any] | None, source_type: str) -> dict[str, Any] | None:
    if vendor is None:
        return None
    primary_by_type = vendor.get("primary_source_by_type")
    if isinstance(primary_by_type, dict):
        primary = primary_by_type.get(source_type)
        if isinstance(primary, dict) and _source_url(primary):
            return primary
    for key in ("canonical_sources", "candidate_sources"):
        sources = [
            source
            for source in vendor.get(key, []) or []
            if isinstance(source, dict)
            and source.get("source_type") == source_type
            and _source_url(source)
        ]
        if sources:
            return sorted(
                sources,
                key=lambda source: (
                    str(source.get("source_id") or ""),
                    str(source.get("source_url") or source.get("candidate_url") or ""),
                ),
            )[0]
    return None


def _source_url(source: dict[str, Any] | None) -> str | None:
    if not isinstance(source, dict):
        return None
    return _nullable_text(source.get("source_url") or source.get("candidate_url"))


def _compiled_domain(vendor: dict[str, Any] | None) -> str | None:
    if vendor is None:
        return None
    domains = vendor.get("official_domains")
    if isinstance(domains, list):
        for domain in domains:
            text = _nullable_text(domain)
            if text:
                return text
    return _nullable_text(vendor.get("official_domain"))


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
