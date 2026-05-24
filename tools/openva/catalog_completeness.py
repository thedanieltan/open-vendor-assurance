from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.paths import relative_repo_path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "catalog_completeness_report"

PRIVACY_TYPES = {"privacy_notice"}
DPA_TYPES = {"dpa"}
SUBPROCESSOR_TYPES = {"subprocessors_list"}
SECURITY_TYPES = {"security_page", "trust_center"}
COMPLIANCE_TYPES = {"compliance_page", "certification_reference"}
EXPECTED_SOURCE_GROUPS = {
    "privacy_notice": PRIVACY_TYPES,
    "dpa": DPA_TYPES,
    "subprocessors_list": SUBPROCESSOR_TYPES,
    "security": SECURITY_TYPES,
    "compliance": COMPLIANCE_TYPES,
}

CSV_FIELDS = [
    "vendor_id",
    "display_name",
    "legal_entity_name",
    "has_vendor_record",
    "has_legal_entity_name",
    "has_homepage",
    "has_privacy_notice_source",
    "has_dpa_source",
    "has_subprocessor_source",
    "has_security_source",
    "has_compliance_source",
    "has_source_health",
    "has_jurisdiction_or_region",
    "has_vendor_category",
    "source_count",
    "missing_required_fields",
    "missing_expected_sources",
    "completeness_bucket",
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


def vendor_dirs(root: Path = ROOT) -> list[Path]:
    return sorted(path for path in (root / "data" / "vendors").glob("*") if path.is_dir())


def source_paths(vendor_dir: Path) -> list[Path]:
    return sorted((vendor_dir / "sources").glob("*.yaml"))


def source_types(sources: list[dict[str, Any]]) -> set[str]:
    return {str(source.get("source_type") or "") for source in sources if source.get("source_type")}


def has_any(types: set[str], expected: set[str]) -> bool:
    return bool(types & expected)


def completeness_bucket(
    *,
    missing_required_fields: list[str],
    missing_expected_sources: list[str],
    source_count: int,
) -> str:
    if "legal_entity_name" in missing_required_fields:
        return "entity_review_needed"
    if source_count == 0:
        return "minimal"
    if len(missing_expected_sources) >= 3:
        return "source_coverage_incomplete"
    if missing_required_fields or missing_expected_sources:
        return "partial"
    return "complete_enough_for_review"


def vendor_report(vendor_dir: Path, *, root: Path = ROOT) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    vendor_path = vendor_dir / "vendor.yaml"
    vendor: dict[str, Any] = {}
    if vendor_path.exists():
        try:
            vendor = load_yaml(vendor_path)
        except ValueError as exc:
            failures.append(str(exc))
    vendor_id = str(vendor.get("vendor_id") or vendor_dir.name)

    sources: list[dict[str, Any]] = []
    for path in source_paths(vendor_dir):
        try:
            source = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        sources.append(source)

    types = source_types(sources)
    legal_entity_name = vendor.get("legal_entity_name") or vendor.get("legal_name")
    homepage_values = vendor.get("public_entrypoints") or []
    if isinstance(homepage_values, str):
        homepage_values = [homepage_values]

    has_privacy = has_any(types, PRIVACY_TYPES)
    has_dpa = has_any(types, DPA_TYPES)
    has_subprocessor = has_any(types, SUBPROCESSOR_TYPES)
    has_security = has_any(types, SECURITY_TYPES)
    has_compliance = has_any(types, COMPLIANCE_TYPES)
    has_region = bool(vendor.get("regions_served") or vendor.get("headquarters_country"))
    has_category = bool(vendor.get("vendor_categories"))

    missing_required_fields = []
    if not legal_entity_name:
        missing_required_fields.append("legal_entity_name")
    if not homepage_values:
        missing_required_fields.append("homepage")
    if not has_region:
        missing_required_fields.append("jurisdiction_or_region")
    if not has_category:
        missing_required_fields.append("vendor_category")

    missing_expected_sources = []
    source_group_results = {
        "privacy_notice": has_privacy,
        "dpa": has_dpa,
        "subprocessors_list": has_subprocessor,
        "security": has_security,
        "compliance": has_compliance,
    }
    for group, present in source_group_results.items():
        if not present:
            missing_expected_sources.append(group)

    bucket = completeness_bucket(
        missing_required_fields=missing_required_fields,
        missing_expected_sources=missing_expected_sources,
        source_count=len(sources),
    )
    return (
        {
            "vendor_id": vendor_id,
            "display_name": vendor.get("display_name"),
            "legal_entity_name": legal_entity_name,
            "has_vendor_record": vendor_path.exists() and not failures,
            "has_legal_entity_name": bool(legal_entity_name),
            "has_homepage": bool(homepage_values),
            "has_privacy_notice_source": has_privacy,
            "has_dpa_source": has_dpa,
            "has_subprocessor_source": has_subprocessor,
            "has_security_source": has_security,
            "has_compliance_source": has_compliance,
            "has_source_health": bool(sources),
            "has_jurisdiction_or_region": has_region,
            "has_vendor_category": has_category,
            "source_count": len(sources),
            "source_types": sorted(types),
            "missing_required_fields": missing_required_fields,
            "missing_expected_sources": missing_expected_sources,
            "completeness_bucket": bucket,
            "requires_human_review": bucket != "complete_enough_for_review",
            "path": relative_repo_path(vendor_path, root) if vendor_path.exists() else None,
        },
        failures,
    )


def build_catalog_completeness(root: Path = ROOT, *, generated_at: str | None = None) -> dict[str, Any]:
    vendors: list[dict[str, Any]] = []
    failures: list[str] = []
    for vendor_dir in vendor_dirs(root):
        report, row_failures = vendor_report(vendor_dir, root=root)
        vendors.append(report)
        failures.extend(row_failures)
    vendors.sort(key=lambda item: str(item["vendor_id"]))

    bucket_counts = Counter(vendor["completeness_bucket"] for vendor in vendors)
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
        "inputs": {
            "vendor_glob": "data/vendors/*/vendor.yaml",
            "source_glob": "data/vendors/*/sources/*.yaml",
        },
        "summary": {
            "vendor_count": len(vendors),
            "complete_enough_for_review_count": bucket_counts.get("complete_enough_for_review", 0),
            "partial_count": bucket_counts.get("partial", 0),
            "source_coverage_incomplete_count": bucket_counts.get("source_coverage_incomplete", 0),
            "entity_review_needed_count": bucket_counts.get("entity_review_needed", 0),
            "minimal_count": bucket_counts.get("minimal", 0),
            "missing_privacy_notice_count": sum(not vendor["has_privacy_notice_source"] for vendor in vendors),
            "missing_dpa_count": sum(not vendor["has_dpa_source"] for vendor in vendors),
            "missing_subprocessor_count": sum(not vendor["has_subprocessor_source"] for vendor in vendors),
            "missing_security_count": sum(not vendor["has_security_source"] for vendor in vendors),
            "missing_compliance_count": sum(not vendor["has_compliance_source"] for vendor in vendors),
            "parse_failure_count": len(failures),
        },
        "vendors": vendors,
        "failures": failures,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(report: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for vendor in report["vendors"]:
            row = {
                **vendor,
                "missing_required_fields": ";".join(vendor["missing_required_fields"]),
                "missing_expected_sources": ";".join(vendor["missing_expected_sources"]),
            }
            writer.writerow(row)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# OpenVA Catalog Completeness Audit",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This report measures catalog completeness only. It is not legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        f"- Vendors: `{summary['vendor_count']}`",
        f"- Complete enough for review: `{summary['complete_enough_for_review_count']}`",
        f"- Partial: `{summary['partial_count']}`",
        f"- Source coverage incomplete: `{summary['source_coverage_incomplete_count']}`",
        f"- Entity review needed: `{summary['entity_review_needed_count']}`",
        f"- Minimal: `{summary['minimal_count']}`",
        f"- Missing privacy notice source: `{summary['missing_privacy_notice_count']}`",
        f"- Missing DPA source: `{summary['missing_dpa_count']}`",
        f"- Missing subprocessors source: `{summary['missing_subprocessor_count']}`",
        f"- Missing security source: `{summary['missing_security_count']}`",
        f"- Missing compliance source: `{summary['missing_compliance_count']}`",
        "",
        "## Guardrails",
        "",
        "- Reads committed catalog records only.",
        "- Does not fetch the network.",
        "- Does not discover sources.",
        "- Does not mutate catalog data.",
        "- Does not create repair PRs.",
        "- Does not enable automerge.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-completeness")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("catalog-completeness-report.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("catalog-completeness-vendors.csv"))
    parser.add_argument("--markdown-output", type=Path, default=Path("catalog-completeness-summary.md"))
    args = parser.parse_args(argv)

    report = build_catalog_completeness(args.root)
    write_json(report, args.output)
    write_csv(report, args.csv_output)
    write_markdown(report, args.markdown_output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
