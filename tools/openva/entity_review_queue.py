from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.paths import relative_repo_path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "entity_review_queue"
LEGAL_SUFFIX_PATTERN = re.compile(
    r"\b(inc\.?|llc|ltd\.?|limited|corp\.?|corporation|gmbh|s\.?a\.?|n\.?v\.?|pte\.?\s+ltd\.?|private limited|pty ltd)\b",
    re.IGNORECASE,
)
REGIONAL_TERMS = {"singapore", "europe", "eu", "uk", "united kingdom", "australia", "japan", "india"}

CSV_FIELDS = [
    "vendor_id",
    "vendor_name",
    "legal_entity_name",
    "issue_type",
    "evidence",
    "recommended_review_action",
    "requires_human_review",
]

REVIEW_ACTIONS = {
    "missing_legal_entity": "Add or verify the contracting legal entity from public vendor-controlled sources.",
    "brand_entity_ambiguity": "Confirm whether the display name is a brand, product, or legal entity.",
    "regional_entity_ambiguity": "Verify whether the catalog record should name a regional contracting entity.",
    "source_entity_mismatch_possible": "Review source titles and publisher language for a possible entity mismatch.",
    "parent_subsidiary_ambiguity": "Confirm parent, subsidiary, and product-brand relationships before editing entity fields.",
}


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


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def queue_item(vendor: dict[str, Any], issue_type: str, evidence: str) -> dict[str, Any]:
    return {
        "vendor_id": vendor["vendor_id"],
        "vendor_name": vendor.get("display_name"),
        "legal_entity_name": vendor.get("legal_entity_name"),
        "issue_type": issue_type,
        "evidence": evidence,
        "recommended_review_action": REVIEW_ACTIONS[issue_type],
        "requires_human_review": True,
    }


def load_vendor_context(vendor_dir: Path, *, root: Path = ROOT) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    vendor_path = vendor_dir / "vendor.yaml"
    vendor_data: dict[str, Any] = {}
    if vendor_path.exists():
        try:
            vendor_data = load_yaml(vendor_path)
        except ValueError as exc:
            failures.append(str(exc))
    vendor = {
        "vendor_id": str(vendor_data.get("vendor_id") or vendor_dir.name),
        "display_name": vendor_data.get("display_name") or vendor_dir.name,
        "legal_entity_name": vendor_data.get("legal_entity_name") or vendor_data.get("legal_name"),
        "headquarters_country": vendor_data.get("headquarters_country"),
        "regions_served": vendor_data.get("regions_served") or [],
        "entity_surface": vendor_data.get("entity_surface"),
        "path": relative_repo_path(vendor_path, root) if vendor_path.exists() else None,
    }
    sources: list[dict[str, Any]] = []
    for path in source_paths(vendor_dir):
        try:
            source = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        sources.append(source)
    return vendor, sources, failures


def infer_issues(vendor: dict[str, Any], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    vendor_name = str(vendor.get("display_name") or "")
    legal_name = str(vendor.get("legal_entity_name") or "")
    normalized_vendor = normalize(vendor_name)
    normalized_legal = normalize(legal_name)

    if not legal_name:
        items.append(queue_item(vendor, "missing_legal_entity", "legal entity field is missing"))
    elif normalize(vendor_name) == normalize(legal_name) and not LEGAL_SUFFIX_PATTERN.search(legal_name):
        items.append(
            queue_item(
                vendor,
                "brand_entity_ambiguity",
                "display name and legal entity are identical and lack a legal suffix",
            )
        )

    region_text = " ".join(str(value) for value in vendor.get("regions_served") or [])
    combined_entity_text = f"{vendor_name} {legal_name} {region_text}".lower()
    if any(term in combined_entity_text for term in REGIONAL_TERMS) and vendor.get("entity_surface") == "global_brand":
        items.append(
            queue_item(
                vendor,
                "regional_entity_ambiguity",
                "global brand record references regional entity or region language",
            )
        )

    for source in sources:
        title = str(source.get("title_en") or source.get("title_native") or "")
        normalized_title = normalize(title)
        if LEGAL_SUFFIX_PATTERN.search(title) and normalized_vendor and normalized_vendor not in normalized_title and normalized_legal and normalized_legal not in normalized_title:
            items.append(
                queue_item(
                    vendor,
                    "source_entity_mismatch_possible",
                    f"source {source.get('source_id')} title names a different legal-looking entity",
                )
            )
            break

    if legal_name and any(term in normalize(legal_name) for term in ["holdings", "group", "parent"]) and vendor.get("entity_surface") == "global_brand":
        items.append(
            queue_item(
                vendor,
                "parent_subsidiary_ambiguity",
                "legal entity name suggests parent or group entity while record surface is global brand",
            )
        )

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        deduped[(item["vendor_id"], item["issue_type"])] = item
    return [deduped[key] for key in sorted(deduped)]


def build_entity_review_queue(root: Path = ROOT, *, generated_at: str | None = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    failures: list[str] = []
    for vendor_dir in vendor_dirs(root):
        vendor, sources, row_failures = load_vendor_context(vendor_dir, root=root)
        failures.extend(row_failures)
        items.extend(infer_issues(vendor, sources))
    items.sort(key=lambda item: (str(item["vendor_id"]), str(item["issue_type"])))
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
            "requires_human_review": True,
            "non_advisory": True,
        },
        "summary": {
            "queued_vendor_issue_count": len(items),
            "vendor_count": len(vendor_dirs(root)),
            "parse_failure_count": len(failures),
            "by_issue_type": {
                issue_type: sum(item["issue_type"] == issue_type for item in items)
                for issue_type in [
                    "missing_legal_entity",
                    "brand_entity_ambiguity",
                    "regional_entity_ambiguity",
                    "source_entity_mismatch_possible",
                    "parent_subsidiary_ambiguity",
                ]
            },
        },
        "items": items,
        "failures": failures,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(report: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in report["items"]:
            writer.writerow(item)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# OpenVA Entity Review Queue",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This queue surfaces conservative entity ambiguity signals for human review. It is not legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        f"- Queued vendor issues: `{summary['queued_vendor_issue_count']}`",
        f"- Vendors scanned: `{summary['vendor_count']}`",
        f"- Parse failures: `{summary['parse_failure_count']}`",
        "",
        "## Guardrails",
        "",
        "- Human review is required for every item.",
        "- Does not automatically correct entity fields.",
        "- Does not mutate catalog data.",
        "- Does not perform network calls.",
        "- Does not enable automerge.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-entity-review-queue")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("entity-review-queue.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("entity-review-queue.csv"))
    parser.add_argument("--markdown-output", type=Path, default=Path("entity-review-summary.md"))
    args = parser.parse_args(argv)

    report = build_entity_review_queue(args.root)
    write_json(report, args.output)
    write_csv(report, args.csv_output)
    write_markdown(report, args.markdown_output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
