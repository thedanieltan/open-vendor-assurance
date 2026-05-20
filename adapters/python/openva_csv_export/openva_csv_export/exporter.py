from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from openva_pack_reader import OpenVAPack

CsvRow = dict[str, Any]
RowProvider = Callable[[OpenVAPack], Iterable[CsvRow]]

ANNOTATION_COLUMNS = ["record_class", "canonical", "advisory_boundary"]

VENDOR_COLUMNS = [
    *ANNOTATION_COLUMNS,
    "vendor_id",
    "display_name",
    "legal_name",
    "catalog_status",
    "headquarters_country",
    "vendor_categories",
    "regions_served",
    "official_domains",
    "public_entrypoints",
    "entity_surface",
    "entity_family",
    "manifest_path",
    "_openva_path",
]

SOURCE_COLUMNS = [
    *ANNOTATION_COLUMNS,
    "vendor_id",
    "source_id",
    "source_type",
    "source_url",
    "title_en",
    "summary_en",
    "source_authority_class",
    "access_class",
    "rights_class",
    "source_language",
    "not_advice",
    "_openva_path",
]

ARTIFACT_COLUMNS = [
    *ANNOTATION_COLUMNS,
    "vendor_id",
    "artifact_id",
    "source_id",
    "artifact_type",
    "canonical_url",
    "effective_or_published_at",
    "region_scope",
    "product_scope",
    "access_class",
    "rights_class",
    "source_language",
    "not_advice",
    "hashes",
    "storage",
    "_openva_path",
]

OBSERVATION_COLUMNS = [
    *ANNOTATION_COLUMNS,
    "vendor_id",
    "observation_id",
    "source_id",
    "artifact_id",
    "observed_at",
    "result",
    "http_status",
    "final_url",
    "access_class",
    "not_advice",
    "hashes",
    "storage",
    "notes",
    "_openva_path",
]

CANDIDATE_SOURCE_COLUMNS = [
    *ANNOTATION_COLUMNS,
    "vendor_id",
    "candidate_source_id",
    "source_type_candidate",
    "candidate_url",
    "discovery_method",
    "confidence",
    "requires_review",
    "discovered_at",
    "discovered_by",
    "not_advice",
    "evidence",
    "notes",
    "_openva_path",
]

UNAVAILABLE_SOURCE_COLUMNS = [
    *ANNOTATION_COLUMNS,
    "vendor_id",
    "unavailable_source_id",
    "source_type",
    "unavailability_status",
    "reason",
    "reviewed_at",
    "reviewed_by",
    "next_review_after",
    "not_advice",
    "related_vendor_ids",
    "candidate_urls_checked",
    "notes",
    "_openva_path",
]

SOURCE_COVERAGE_COLUMNS = [
    *ANNOTATION_COLUMNS,
    "vendor_id",
    "canonical_source_types",
    "candidate_source_types",
    "unavailable_source_types",
    "missing_core_source_types",
]


def export_csvs(pack_path: str | Path, output_dir: str | Path) -> list[Path]:
    pack = OpenVAPack.load(pack_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exports: list[tuple[str, list[str], RowProvider]] = [
        ("vendors.csv", VENDOR_COLUMNS, vendor_rows),
        ("sources.csv", SOURCE_COLUMNS, lambda current_pack: current_pack.canonical_sources()),
        ("artifacts.csv", ARTIFACT_COLUMNS, lambda current_pack: current_pack.artifacts()),
        ("observations.csv", OBSERVATION_COLUMNS, lambda current_pack: current_pack.observations()),
        ("candidate_sources.csv", CANDIDATE_SOURCE_COLUMNS, lambda current_pack: current_pack.candidate_sources()),
        ("unavailable_sources.csv", UNAVAILABLE_SOURCE_COLUMNS, unavailable_source_rows),
        ("source_coverage.csv", SOURCE_COVERAGE_COLUMNS, source_coverage_rows),
    ]

    written: list[Path] = []
    for filename, columns, rows_for_pack in exports:
        path = out_dir / filename
        write_csv(path, columns, rows_for_pack(pack))
        written.append(path)
    return written


def vendor_rows(pack: OpenVAPack) -> list[CsvRow]:
    search_rows = {
        row.get("vendor_id"): row
        for row in pack.vendor_search()
        if isinstance(row, dict) and isinstance(row.get("vendor_id"), str)
    }
    rows = pack.vendors()
    for row in rows:
        search_row = search_rows.get(row.get("vendor_id"), {})
        if isinstance(search_row, dict) and "manifest_path" in search_row:
            row["manifest_path"] = search_row["manifest_path"]
    return rows


def unavailable_source_rows(pack: OpenVAPack) -> list[CsvRow]:
    rows: list[CsvRow] = []
    for row in pack.unavailable_sources():
        exported = dict(row)
        exported["unavailability_status"] = exported.pop("status", "")
        rows.append(exported)
    return rows


def source_coverage_rows(pack: OpenVAPack) -> list[CsvRow]:
    coverage = pack.source_coverage()
    rows = coverage.get("vendor_coverage", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def write_csv(path: Path, columns: list[str], rows: Iterable[CsvRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: cell_value(row.get(column)) for column in columns})


def cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
