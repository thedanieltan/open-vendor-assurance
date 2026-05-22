from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable

from openva_pack_reader import OpenVAPack

SqlRow = dict[str, Any]
RowProvider = Callable[[OpenVAPack], Iterable[SqlRow]]

ANNOTATION_COLUMNS = {
    "record_class": "TEXT NOT NULL",
    "canonical": "INTEGER NOT NULL",
    "catalog_tier": "TEXT NOT NULL",
    "review_state": "TEXT NOT NULL",
    "advisory_boundary": "TEXT NOT NULL",
}

TABLES: dict[str, tuple[dict[str, str], RowProvider]] = {}


def register_table(name: str, columns: dict[str, str], rows: RowProvider) -> None:
    TABLES[name] = ({**ANNOTATION_COLUMNS, **columns}, rows)


def export_sqlite(pack_path: str | Path, output_path: str | Path) -> Path:
    """Export an OpenVA pack to a fresh SQLite database.

    If ``output_path`` already exists, it is replaced before export. This
    adapter does not append to or migrate existing SQLite files.
    """
    pack = OpenVAPack.load(pack_path)
    db_path = Path(output_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for table_name, (columns, rows_for_pack) in TABLES.items():
            create_table(connection, table_name, columns)
            insert_rows(connection, table_name, columns, rows_for_pack(pack))
        connection.execute("PRAGMA user_version = 1")
    return db_path


def create_table(connection: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    column_sql = ", ".join(f"{column_name} {column_type}" for column_name, column_type in columns.items())
    connection.execute(f"CREATE TABLE {table_name} ({column_sql})")


def insert_rows(
    connection: sqlite3.Connection,
    table_name: str,
    columns: dict[str, str],
    rows: Iterable[SqlRow],
) -> None:
    column_names = list(columns)
    placeholders = ", ".join("?" for _ in column_names)
    column_sql = ", ".join(column_names)
    values = [[cell_value(row.get(column_name)) for column_name in column_names] for row in rows]
    if values:
        connection.executemany(f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})", values)


def cell_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int | float | str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def vendor_rows(pack: OpenVAPack) -> list[SqlRow]:
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


def unavailable_source_rows(pack: OpenVAPack) -> list[SqlRow]:
    rows: list[SqlRow] = []
    for row in pack.unavailable_sources():
        exported = dict(row)
        exported["unavailability_status"] = exported.pop("status", None)
        rows.append(exported)
    return rows


def source_coverage_rows(pack: OpenVAPack) -> list[SqlRow]:
    coverage = pack.source_coverage()
    rows = coverage.get("vendor_coverage", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


register_table(
    "vendors",
    {
        "vendor_id": "TEXT NOT NULL PRIMARY KEY",
        "display_name": "TEXT NOT NULL",
        "legal_name": "TEXT",
        "catalog_status": "TEXT",
        "headquarters_country": "TEXT",
        "vendor_categories": "TEXT",
        "regions_served": "TEXT",
        "official_domains": "TEXT",
        "public_entrypoints": "TEXT",
        "entity_surface": "TEXT",
        "entity_family": "TEXT",
        "manifest_path": "TEXT",
        "_openva_path": "TEXT",
    },
    vendor_rows,
)

register_table(
    "canonical_sources",
    {
        "vendor_id": "TEXT NOT NULL",
        "source_id": "TEXT NOT NULL PRIMARY KEY",
        "source_type": "TEXT NOT NULL",
        "source_url": "TEXT NOT NULL",
        "title_en": "TEXT",
        "summary_en": "TEXT",
        "source_authority_class": "TEXT",
        "access_class": "TEXT",
        "rights_class": "TEXT",
        "source_language": "TEXT",
        "not_advice": "INTEGER",
        "_openva_path": "TEXT",
    },
    lambda pack: pack.canonical_sources(),
)

register_table(
    "artifacts",
    {
        "vendor_id": "TEXT NOT NULL",
        "artifact_id": "TEXT NOT NULL PRIMARY KEY",
        "source_id": "TEXT",
        "artifact_type": "TEXT",
        "canonical_url": "TEXT",
        "effective_or_published_at": "TEXT",
        "region_scope": "TEXT",
        "product_scope": "TEXT",
        "access_class": "TEXT",
        "rights_class": "TEXT",
        "source_language": "TEXT",
        "not_advice": "INTEGER",
        "hashes": "TEXT",
        "storage": "TEXT",
        "_openva_path": "TEXT",
    },
    lambda pack: pack.artifacts(),
)

register_table(
    "observations",
    {
        "vendor_id": "TEXT NOT NULL",
        "observation_id": "TEXT PRIMARY KEY",
        "source_id": "TEXT",
        "artifact_id": "TEXT",
        "observed_at": "TEXT",
        "result": "TEXT",
        "http_status": "INTEGER",
        "final_url": "TEXT",
        "access_class": "TEXT",
        "not_advice": "INTEGER",
        "hashes": "TEXT",
        "storage": "TEXT",
        "notes": "TEXT",
        "_openva_path": "TEXT",
    },
    lambda pack: pack.observations(),
)

register_table(
    "candidate_sources",
    {
        "vendor_id": "TEXT NOT NULL",
        "candidate_source_id": "TEXT PRIMARY KEY",
        "source_type_candidate": "TEXT",
        "candidate_url": "TEXT",
        "discovery_method": "TEXT",
        "confidence": "TEXT",
        "requires_review": "INTEGER",
        "discovered_at": "TEXT",
        "discovered_by": "TEXT",
        "not_advice": "INTEGER",
        "evidence": "TEXT",
        "notes": "TEXT",
        "_openva_path": "TEXT",
    },
    lambda pack: pack.candidate_sources(),
)

register_table(
    "unavailable_sources",
    {
        "vendor_id": "TEXT NOT NULL",
        "unavailable_source_id": "TEXT NOT NULL PRIMARY KEY",
        "source_type": "TEXT",
        "unavailability_status": "TEXT",
        "reason": "TEXT",
        "reviewed_at": "TEXT",
        "reviewed_by": "TEXT",
        "next_review_after": "TEXT",
        "not_advice": "INTEGER",
        "related_vendor_ids": "TEXT",
        "candidate_urls_checked": "TEXT",
        "notes": "TEXT",
        "_openva_path": "TEXT",
    },
    unavailable_source_rows,
)

register_table(
    "changes",
    {
        "vendor_id": "TEXT NOT NULL",
        "change_id": "TEXT NOT NULL PRIMARY KEY",
        "change_type": "TEXT",
        "source_id": "TEXT",
        "artifact_id": "TEXT",
        "detected_at": "TEXT",
        "catalog_change_significance": "TEXT",
        "review_state": "TEXT",
        "summary": "TEXT",
        "from_hash": "TEXT",
        "to_hash": "TEXT",
        "not_advice": "INTEGER",
        "_openva_path": "TEXT",
    },
    lambda pack: pack.changes(),
)

register_table(
    "source_coverage",
    {
        "vendor_id": "TEXT NOT NULL PRIMARY KEY",
        "canonical_source_types": "TEXT",
        "candidate_source_types": "TEXT",
        "unavailable_source_types": "TEXT",
        "missing_core_source_types": "TEXT",
    },
    source_coverage_rows,
)
