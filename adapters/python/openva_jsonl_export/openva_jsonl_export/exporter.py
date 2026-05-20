from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from openva_pack_reader import OpenVAPack

JsonlRow = dict[str, Any]
RowProvider = Callable[[OpenVAPack], Iterable[JsonlRow]]


def export_jsonl(pack_path: str | Path, output_dir: str | Path) -> list[Path]:
    pack = OpenVAPack.load(pack_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exports: list[tuple[str, RowProvider]] = [
        ("openva-vendors.jsonl", vendor_rows),
        ("openva-sources.jsonl", lambda current_pack: current_pack.canonical_sources()),
        ("openva-artifacts.jsonl", lambda current_pack: current_pack.artifacts()),
        ("openva-observations.jsonl", lambda current_pack: current_pack.observations()),
        ("openva-candidates.jsonl", lambda current_pack: current_pack.candidate_sources()),
        ("openva-unavailable-sources.jsonl", unavailable_source_rows),
        ("openva-source-coverage.jsonl", source_coverage_rows),
    ]

    written: list[Path] = []
    for filename, rows_for_pack in exports:
        path = out_dir / filename
        write_jsonl(path, rows_for_pack(pack))
        written.append(path)
    return written


def vendor_rows(pack: OpenVAPack) -> list[JsonlRow]:
    search_rows = {
        row.get("vendor_id"): row
        for row in pack.vendor_search()
        if isinstance(row, dict) and isinstance(row.get("vendor_id"), str)
    }
    rows: list[JsonlRow] = []
    for row in pack.vendors():
        exported = strip_deprecated_aliases(row)
        exported.pop("status", None)
        rows.append(exported)
    for row in rows:
        search_row = search_rows.get(row.get("vendor_id"), {})
        if isinstance(search_row, dict) and "manifest_path" in search_row:
            row["manifest_path"] = search_row["manifest_path"]
    return rows


def unavailable_source_rows(pack: OpenVAPack) -> list[JsonlRow]:
    rows: list[JsonlRow] = []
    for row in pack.unavailable_sources():
        exported = strip_deprecated_aliases(row)
        exported["unavailability_status"] = exported.pop("status", None)
        rows.append(exported)
    return rows


def source_coverage_rows(pack: OpenVAPack) -> list[JsonlRow]:
    coverage = pack.source_coverage()
    rows = coverage.get("vendor_coverage", [])
    if not isinstance(rows, list):
        return []
    return [strip_deprecated_aliases(row) for row in rows if isinstance(row, dict)]


def strip_deprecated_aliases(row: JsonlRow) -> JsonlRow:
    exported = dict(row)
    exported.pop("materiality", None)
    return exported


def write_jsonl(path: Path, rows: Iterable[JsonlRow]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(strip_deprecated_aliases(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            handle.write("\n")
