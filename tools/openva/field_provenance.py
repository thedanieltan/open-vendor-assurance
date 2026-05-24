from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.paths import relative_repo_path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "field_provenance_coverage"

TRACKED_FIELDS = [
    "legal_entity_name",
    "homepage_url",
    "privacy_notice_url",
    "dpa_url",
    "subprocessor_url",
    "security_url",
    "compliance_url",
    "certification_claims",
    "data_processing_region",
]

CSV_FIELDS = [
    "vendor_id",
    "display_name",
    "tracked_field_count",
    "provenance_record_count",
    "covered_fields",
    "missing_fields",
    "coverage_bucket",
    "requires_human_review",
]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{relative_repo_path(path, ROOT)}: expected YAML mapping")
    return data


def vendor_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/vendor.yaml"))


def provenance_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/provenance/*.yaml"))


def coverage_bucket(covered_count: int) -> str:
    if covered_count >= len(TRACKED_FIELDS):
        return "strong"
    if covered_count >= 4:
        return "mixed"
    if covered_count > 0:
        return "partial"
    return "missing"


def build_field_provenance_coverage(root: Path = ROOT, *, generated_at: str | None = None) -> dict[str, Any]:
    vendors: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for path in vendor_paths(root):
        try:
            vendor = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        vendor_id = str(vendor.get("vendor_id") or path.parent.name)
        vendors[vendor_id] = {
            "vendor_id": vendor_id,
            "display_name": vendor.get("display_name"),
        }

    provenance_by_vendor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in provenance_paths(root):
        try:
            record = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        provenance_by_vendor[str(record.get("vendor_id") or path.parents[1].name)].append(record)

    rows: list[dict[str, Any]] = []
    for vendor_id, vendor in sorted(vendors.items()):
        records = provenance_by_vendor.get(vendor_id, [])
        covered_fields = sorted({str(record.get("field_name")) for record in records if record.get("field_name") in TRACKED_FIELDS})
        missing_fields = [field for field in TRACKED_FIELDS if field not in covered_fields]
        bucket = coverage_bucket(len(covered_fields))
        rows.append(
            {
                **vendor,
                "tracked_field_count": len(TRACKED_FIELDS),
                "provenance_record_count": len(records),
                "covered_fields": covered_fields,
                "missing_fields": missing_fields,
                "coverage_bucket": bucket,
                "requires_human_review": bucket != "strong",
            }
        )

    bucket_counts = Counter(row["coverage_bucket"] for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": REPORT_TYPE,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "tracked_fields": TRACKED_FIELDS,
        "summary": {
            "vendor_count": len(rows),
            "field_provenance_record_count": sum(row["provenance_record_count"] for row in rows),
            "strong_count": bucket_counts.get("strong", 0),
            "mixed_count": bucket_counts.get("mixed", 0),
            "partial_count": bucket_counts.get("partial", 0),
            "missing_count": bucket_counts.get("missing", 0),
            "parse_failure_count": len(failures),
        },
        "vendors": rows,
        "failures": failures,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(report: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in report["vendors"]:
            writer.writerow(
                {
                    **row,
                    "covered_fields": ";".join(row["covered_fields"]),
                    "missing_fields": ";".join(row["missing_fields"]),
                }
            )


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# OpenVA Field Provenance Coverage",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This report measures field-level provenance coverage only. It is not legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        f"- Vendors: `{summary['vendor_count']}`",
        f"- Field provenance records: `{summary['field_provenance_record_count']}`",
        f"- Strong: `{summary['strong_count']}`",
        f"- Mixed: `{summary['mixed_count']}`",
        f"- Partial: `{summary['partial_count']}`",
        f"- Missing: `{summary['missing_count']}`",
        "",
        "## Guardrails",
        "",
        "- Does not backfill vendor records.",
        "- Does not infer field values.",
        "- Does not mutate catalog data.",
        "- Does not perform network calls.",
        "- Does not enable automerge.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-field-provenance")
    parser.add_argument("command", choices={"coverage"})
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("field-provenance-coverage.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("field-provenance-coverage.csv"))
    parser.add_argument("--markdown-output", type=Path, default=Path("field-provenance-summary.md"))
    args = parser.parse_args(argv)

    report = build_field_provenance_coverage(args.root)
    write_json(report, args.output)
    write_csv(report, args.csv_output)
    write_markdown(report, args.markdown_output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
