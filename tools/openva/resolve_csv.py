"""Local hint-only CSV compiler for OpenVA resolver result packs."""

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
    """Compile local CSV rows into hint-only resolver result-pack rows."""
    requested_source_types = pack.normalize_source_types(source_types)
    index = load_vendor_match_index(catalog_root)
    vendors = [item for item in index.get("items", []) if isinstance(item, dict)]
    matcher_records = [matcher.vendor_record(vendor) for vendor in vendors]
    vendors_by_id = {str(vendor.get("vendor_id")): vendor for vendor in vendors if vendor.get("vendor_id")}

    rows: list[dict[str, Any]] = []
    for input_index, input_row in enumerate(input_rows):
        selected = _select_vendor(input_row, matcher_records)
        rows.append(
            _result_row(
                input_row,
                input_index,
                selected.vendor.vendor_id if selected is not None else None,
                vendors_by_id,
                requested_source_types,
                _match_status(input_row, matcher_records, selected),
            )
        )
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
        description="Compile a local vendor CSV into hint-only OpenVA resolver result-pack JSON and CSV.",
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument(
        "--source-types",
        default=",".join(pack.SOURCE_TYPES),
        help="Comma-separated source types to include, in resolver result-pack taxonomy.",
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


def _select_vendor(
    input_row: dict[str, Any],
    matcher_records: list[matcher.VendorRecord],
) -> matcher.MatchCandidate | None:
    candidates = _match_candidates(input_row, matcher_records)
    return matcher.select_match(candidates)


def _match_status(
    input_row: dict[str, Any],
    matcher_records: list[matcher.VendorRecord],
    selected: matcher.MatchCandidate | None,
) -> str:
    return matcher.classify(_match_candidates(input_row, matcher_records), selected)


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
    vendor_id: str | None,
    vendors_by_id: dict[str, dict[str, Any]],
    source_types: list[str],
    match_status: str,
) -> dict[str, Any]:
    vendor = vendors_by_id.get(vendor_id or "")
    identity_status = "match" if vendor is not None else "no_match"
    return {
        "result_pack_version": pack.RESULT_PACK_VERSION,
        "input_index": input_index,
        "input_vendor_name": _nullable_text(input_row.get("vendor_name") or input_row.get("business_entity_name")),
        "input_domain": _nullable_text(input_row.get("domain")),
        "identity_status": identity_status,
        "no_match_reason": None if identity_status == "match" else _no_match_reason(input_row, match_status),
        "matched_vendor_id": _nullable_text(vendor.get("vendor_id")) if vendor else None,
        "matched_vendor_name": _nullable_text(vendor.get("display_name")) if vendor else None,
        "sources": [_source_result(vendor, source_type) for source_type in source_types],
        "not_advice": True,
    }


def _source_result(vendor: dict[str, Any] | None, source_type: str) -> dict[str, Any]:
    source = _source_for_type(vendor, source_type) if vendor is not None else None
    url = _source_url(source)
    return {
        "source_type": source_type,
        "status": "not_checked",
        "url": url,
        "candidate_basis": _candidate_basis(source, url),
        "verification_basis": "not_checked",
        "checked_at": None,
    }


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


def _candidate_basis(source: dict[str, Any] | None, url: str | None) -> str:
    if not isinstance(source, dict) or url is None:
        return "none"
    explicit = str(source.get("candidate_basis") or "")
    if explicit in pack.CANDIDATE_BASES:
        return explicit
    origin = str(source.get("origin") or "")
    if origin in {"community", "community_hint"}:
        return "community_hint"
    if origin in {"vendor", "vendor_asserted"}:
        return "vendor_asserted"
    if origin == "direct_input":
        return "direct_input"
    return "cached_locator"


def _no_match_reason(input_row: dict[str, Any], match_status: str) -> str:
    if match_status == matcher.STATUS_AMBIGUOUS:
        return "multiple_plausible_entities"
    if not (input_row.get("vendor_name") or input_row.get("business_entity_name") or input_row.get("domain")):
        return "no_public_identity"
    return "not_in_reference"


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
