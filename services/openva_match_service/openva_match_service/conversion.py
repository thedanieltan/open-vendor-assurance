from __future__ import annotations

import csv
import io
import json
from typing import Any

from openva_vendor_inventory_matcher.matcher import ENRICHMENT_COLUMNS, MATCH_INPUT_COLUMNS, MatcherIndex

JSON_FIELD_RENAMES = {
    "candidate_matches_json": "candidate_matches",
    "official_domains_json": "official_domains",
    "canonical_source_types_json": "canonical_source_types",
    "candidate_source_types_json": "candidate_source_types",
    "unavailable_source_types_json": "unavailable_source_types",
    "missing_core_source_types_json": "missing_core_source_types",
    "canonical_sources_json": "canonical_sources",
    "candidate_sources_json": "candidate_sources",
    "primary_source_by_type_json": "primary_source_by_type",
    "legal_entity_registered_address_json": "legal_entity_registered_address",
    "legal_entities_json": "legal_entities",
    "candidate_legal_entities_json": "candidate_legal_entities",
}

BOOLEAN_FIELDS = {
    "canonical",
    "canonical_sources_available",
    "candidate_sources_available",
    "unavailable_sources_recorded",
}


def match_csv_bytes(
    csv_bytes: bytes, matcher_index: MatcherIndex, *, max_rows: int | None = None
) -> list[dict[str, Any]]:
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("inventory_csv must be UTF-8 CSV") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = list(reader.fieldnames or [])
    if not MATCH_INPUT_COLUMNS.intersection(fieldnames):
        raise ValueError("input CSV must include domain, vendor_name, business_entity_name, or registration_number")

    rows: list[dict[str, Any]] = []
    for input_row in reader:
        if max_rows is not None and len(rows) >= max_rows:
            raise ValueError(f"inventory_csv exceeds the maximum of {max_rows} rows")
        enriched = {column: "" for column in ENRICHMENT_COLUMNS}
        enriched.update({key: value or "" for key, value in input_row.items()})
        enriched.update(matcher_index.enrich_row({key: value or "" for key, value in input_row.items()}))
        rows.append(typed_row(enriched, fieldnames))
    return rows


def typed_row(row: dict[str, str], original_fieldnames: list[str]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    original_fields = set(original_fieldnames)
    for key, value in row.items():
        if key in JSON_FIELD_RENAMES:
            converted[JSON_FIELD_RENAMES[key]] = parse_json_cell(value)
        elif key in BOOLEAN_FIELDS:
            converted[key] = parse_bool_cell(value)
        elif key == "match_confidence":
            converted[key] = parse_confidence(value)
        elif key in original_fields:
            converted[key] = value
        else:
            converted[key] = value if value != "" else None
    return converted


def parse_json_cell(value: str) -> Any:
    if value == "":
        return None
    return json.loads(value)


def parse_bool_cell(value: str) -> bool | None:
    if value == "":
        return None
    return value.lower() == "true"


def parse_confidence(value: str) -> float | None:
    if value == "":
        return None
    return float(value)
