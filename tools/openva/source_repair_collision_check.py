from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from tools.openva.source_repair_actions import validate_report
from tools.openva.source_repair_plan import normalize_url as normalize_repair_url

REPORT_TYPE = "p0_source_repair_collision_check"

BLOCKING = "blocking"
WARNING = "warning"


@dataclass(frozen=True)
class SourceRecord:
    vendor_id: str
    source_id: str
    source_type: str
    source_url: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_url(url: str) -> str:
    """Normalize URLs for source identity checks without changing meaningful paths."""
    cleaned = normalize_repair_url(str(url or ""))
    if not cleaned:
        return ""
    parts = urlsplit(cleaned)
    if not parts.scheme and not parts.netloc:
        return cleaned.rstrip("#").rstrip("?").rstrip("/")
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or ""
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def sort_row(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_type") or ""),
        str(row.get("original_source_url") or ""),
        str(row.get("replacement_source_url") or ""),
    )


def affected_from_repair(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_id": row.get("vendor_id"),
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "original_source_url": row.get("original_source_url"),
        "replacement_source_url": row.get("replacement_source_url"),
    }


def affected_from_source(record: SourceRecord) -> dict[str, Any]:
    return {
        "vendor_id": record.vendor_id,
        "source_id": record.source_id,
        "source_type": record.source_type,
        "original_source_url": record.source_url,
        "replacement_source_url": record.source_url,
    }


def affected_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item.get("vendor_id") or ""),
        str(item.get("source_id") or ""),
        str(item.get("source_type") or ""),
        str(item.get("original_source_url") or ""),
        str(item.get("replacement_source_url") or ""),
    )


def load_catalog_sources(catalog_root: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for path in sorted(catalog_root.glob("*/sources/*.yaml")):
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected YAML mapping")
        relative = path.relative_to(catalog_root)
        vendor_id = str(data.get("vendor_id") or relative.parts[0])
        source_id = str(data.get("source_id") or path.stem)
        source_url = str(data.get("source_url") or "")
        records.append(
            SourceRecord(
                vendor_id=vendor_id,
                source_id=source_id,
                source_type=str(data.get("source_type") or ""),
                source_url=source_url,
            )
        )
    return records


def collision(
    *,
    collision_type: str,
    severity: str,
    vendor_id: str,
    normalized_url: str,
    affected_sources: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return {
        "collision_type": collision_type,
        "severity": severity,
        "vendor_id": vendor_id,
        "normalized_url": normalized_url,
        "affected_sources": sorted(affected_sources, key=affected_sort_key),
        "reason": reason,
    }


def collision_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    affected = item.get("affected_sources") or [{}]
    first = affected[0] if isinstance(affected, list) and affected else {}
    return (
        str(item.get("collision_type") or ""),
        str(item.get("severity") or ""),
        str(item.get("vendor_id") or ""),
        str(item.get("normalized_url") or ""),
        str(first.get("source_id") or ""),
    )


def replacement_final_url(row: dict[str, Any]) -> str:
    for field in ("replacement_final_url", "final_url", "replacement_resolved_final_url"):
        value = row.get(field)
        if value:
            return str(value)
    return ""


def build_collision_report(
    validation_report: dict[str, Any],
    *,
    catalog_root: Path,
    source_validation_report: str,
) -> dict[str, Any]:
    rows = sorted(validate_report(validation_report), key=sort_row)
    catalog = load_catalog_sources(catalog_root)
    catalog_by_vendor: dict[str, list[SourceRecord]] = {}
    for record in catalog:
        catalog_by_vendor.setdefault(record.vendor_id, []).append(record)

    collisions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    replacement_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        vendor_id = str(row.get("vendor_id") or "")
        normalized = normalize_url(str(row.get("replacement_source_url") or ""))
        replacement_groups.setdefault((vendor_id, normalized), []).append(row)
        if normalized == normalize_url(str(row.get("original_source_url") or "")):
            collisions.append(
                collision(
                    collision_type="replacement_url_same_as_original",
                    severity=BLOCKING,
                    vendor_id=vendor_id,
                    normalized_url=normalized,
                    affected_sources=[affected_from_repair(row)],
                    reason="replacement_source_url_normalizes_to_original_source_url",
                )
            )

    for (vendor_id, normalized), group in replacement_groups.items():
        if normalized and len(group) > 1:
            collisions.append(
                collision(
                    collision_type="intra_batch_duplicate_replacement_url",
                    severity=BLOCKING,
                    vendor_id=vendor_id,
                    normalized_url=normalized,
                    affected_sources=[affected_from_repair(row) for row in group],
                    reason="multiple_batch_rows_resolve_to_same_vendor_source_url",
                )
            )

    for row in rows:
        vendor_id = str(row.get("vendor_id") or "")
        source_id = str(row.get("source_id") or "")
        normalized = normalize_url(str(row.get("replacement_source_url") or ""))
        matches = [
            record
            for record in catalog_by_vendor.get(vendor_id, [])
            if record.source_id != source_id and normalize_url(record.source_url) == normalized
        ]
        if matches:
            collisions.append(
                collision(
                    collision_type="existing_catalog_duplicate_source_url",
                    severity=BLOCKING,
                    vendor_id=vendor_id,
                    normalized_url=normalized,
                    affected_sources=[affected_from_repair(row), *[affected_from_source(record) for record in matches]],
                    reason="replacement_source_url_already_exists_for_same_vendor",
                )
            )

    replacements_by_key = {
        (str(row.get("vendor_id") or ""), str(row.get("source_id") or "")): row for row in rows
    }
    changed_keys = set(replacements_by_key)
    post_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in catalog:
        row = replacements_by_key.get((record.vendor_id, record.source_id))
        if row is None:
            normalized = normalize_url(record.source_url)
            affected = affected_from_source(record)
        else:
            normalized = normalize_url(str(row.get("replacement_source_url") or ""))
            affected = affected_from_repair(row)
        post_groups.setdefault((record.vendor_id, normalized), []).append(affected)

    for (vendor_id, normalized), affected in post_groups.items():
        if not normalized or len(affected) <= 1:
            continue
        if not any((str(item.get("vendor_id") or ""), str(item.get("source_id") or "")) in changed_keys for item in affected):
            continue
        collisions.append(
            collision(
                collision_type="post_application_duplicate_source_url",
                severity=BLOCKING,
                vendor_id=vendor_id,
                normalized_url=normalized,
                affected_sources=affected,
                reason="hypothetical_repair_application_creates_duplicate_vendor_source_url",
            )
        )

    final_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        final_url = normalize_url(replacement_final_url(row))
        if final_url:
            final_groups.setdefault((str(row.get("vendor_id") or ""), final_url), []).append(row)
    for (vendor_id, normalized), group in final_groups.items():
        replacement_urls = {normalize_url(str(row.get("replacement_source_url") or "")) for row in group}
        if len(group) > 1 and len(replacement_urls) > 1:
            warnings.append(
                collision(
                    collision_type="final_url_collision",
                    severity=WARNING,
                    vendor_id=vendor_id,
                    normalized_url=normalized,
                    affected_sources=[affected_from_repair(row) for row in group],
                    reason="multiple_batch_rows_share_same_vendor_final_url",
                )
            )

    collisions = sorted(collisions, key=collision_sort_key)
    warnings = sorted(warnings, key=collision_sort_key)
    return {
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "report_type": REPORT_TYPE,
        "source_validation_report": source_validation_report,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "summary": {
            "checked_rows": len(rows),
            "collision_count": len(collisions) + len(warnings),
            "blocking_collision_count": len(collisions),
            "warning_count": len(warnings),
        },
        "collisions": collisions,
        "warnings": warnings,
    }


def build_markdown_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# P0 Source Repair Collision Summary",
        "",
        "## Counts",
        "",
        f"- Checked rows: `{summary['checked_rows']}`",
        f"- Collisions: `{summary['collision_count']}`",
        f"- Blocking collisions: `{summary['blocking_collision_count']}`",
        f"- Warnings: `{summary['warning_count']}`",
        "",
        "## Guardrails",
        "",
        "- Checked before source YAML changes are applied.",
        "- No catalog source records are mutated by this report.",
        "- Blocking duplicate source URLs require revising reviewed repair artifacts.",
        "",
    ]
    if report["collisions"]:
        lines.extend(["## Blocking Collisions", ""])
        for item in report["collisions"]:
            sources = ", ".join(
                f"`{source.get('vendor_id')}/{source.get('source_id')}`"
                for source in item.get("affected_sources", [])
            )
            lines.append(
                f"- `{item['collision_type']}` for `{item['vendor_id']}` at "
                f"`{item['normalized_url']}`: {sources}"
            )
        lines.append("")
    if report["warnings"]:
        lines.extend(["## Warnings", ""])
        for item in report["warnings"]:
            sources = ", ".join(
                f"`{source.get('vendor_id')}/{source.get('source_id')}`"
                for source in item.get("affected_sources", [])
            )
            lines.append(
                f"- `{item['collision_type']}` for `{item['vendor_id']}` at "
                f"`{item['normalized_url']}`: {sources}"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-collision-check")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--validation", type=Path, required=True)
    check.add_argument("--catalog-root", type=Path, default=Path("data/vendors"))
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--summary-output", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "check":
        report = build_collision_report(
            load_json(args.validation),
            catalog_root=args.catalog_root,
            source_validation_report=str(args.validation),
        )
        write_json(args.output, report)
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(build_markdown_summary(report), encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 1 if report["summary"]["blocking_collision_count"] else 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
