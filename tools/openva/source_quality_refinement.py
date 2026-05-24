from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_TYPE = "source_quality_refinement_queue"
SCHEMA_VERSION = "0.1.0"

QUALITY_STATUSES = {
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "suspect_inferred_url",
}

RECOMMENDED_REVIEW_ACTIONS = {
    "homepage_or_generic_redirect": "Find a more specific vendor-controlled source URL.",
    "possible_mismatch": "Verify semantic match against source_type before replacing.",
    "suspect_inferred_url": "Confirm whether this inferred URL is real and authoritative.",
}

CSV_FIELDS = [
    "vendor_id",
    "source_id",
    "source_type",
    "source_url",
    "final_url",
    "http_status",
    "verification_status",
    "reason",
    "recommended_review_action",
    "requires_human_review",
]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def validate_source_verification_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != "source_verification_report":
        raise ValueError("expected report_type=source_verification_report")
    sources = report.get("sources")
    if not isinstance(sources, list):
        raise ValueError("expected sources list")
    rows: list[dict[str, Any]] = []
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("expected each source verification row to be an object")
        required = ("vendor_id", "source_id", "source_url", "verification_status")
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ValueError(f"source verification row missing required field(s): {', '.join(missing)}")
        rows.append(row)
    return rows


def quality_reason(status: str) -> str:
    if status == "homepage_or_generic_redirect":
        return "source_resolves_to_homepage_or_generic_redirect"
    if status == "possible_mismatch":
        return "source_content_may_not_match_source_type"
    if status == "suspect_inferred_url":
        return "source_url_appears_inferred_and_needs_authority_review"
    return "source_quality_review_required"


def queue_item(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row["verification_status"])
    return {
        "vendor_id": row.get("vendor_id"),
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "source_url": row.get("source_url"),
        "final_url": row.get("final_url"),
        "http_status": row.get("http_status"),
        "verification_status": status,
        "reason": quality_reason(status),
        "recommended_review_action": RECOMMENDED_REVIEW_ACTIONS[status],
        "requires_human_review": True,
    }


def bounded_counter(items: list[dict[str, Any]], field: str, *, limit: int = 25) -> dict[str, int]:
    counts = Counter(str(item.get(field) or "unknown") for item in items)
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit])


def build_source_quality_refinement_queue(
    source_verification_report: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    rows = validate_source_verification_report(source_verification_report)
    items = [
        queue_item(row)
        for row in rows
        if str(row.get("verification_status") or "") in QUALITY_STATUSES
    ]
    items.sort(
        key=lambda item: (
            str(item["verification_status"]),
            str(item.get("vendor_id") or ""),
            str(item.get("source_id") or ""),
            str(item.get("source_url") or ""),
        )
    )
    status_counts = Counter(item["verification_status"] for item in items)
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
        "inputs": {
            "source_verification_report_type": source_verification_report.get("report_type"),
            "source_verification_generated_at": source_verification_report.get("generated_at"),
        },
        "summary": {
            "total_quality_review_count": len(items),
            "homepage_or_generic_redirect_count": status_counts.get("homepage_or_generic_redirect", 0),
            "possible_mismatch_count": status_counts.get("possible_mismatch", 0),
            "suspect_inferred_url_count": status_counts.get("suspect_inferred_url", 0),
            "by_source_type": bounded_counter(items, "source_type"),
            "by_vendor_id": bounded_counter(items, "vendor_id"),
        },
        "items": items,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(report: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in report["items"]:
            writer.writerow(item)


def markdown_row(values: list[Any]) -> str:
    return "| " + " | ".join("" if value is None else str(value).replace("|", "\\|") for value in values) + " |"


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# OpenVA Source Quality Refinement Queue",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This queue identifies reachable but poor-quality source records for human review.",
        "",
        "It is operational metadata only. It is not legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        f"- Total quality review count: `{summary['total_quality_review_count']}`",
        f"- Homepage or generic redirect: `{summary['homepage_or_generic_redirect_count']}`",
        f"- Possible mismatch: `{summary['possible_mismatch_count']}`",
        f"- Suspect inferred URL: `{summary['suspect_inferred_url_count']}`",
        "",
        "## Queue",
        "",
    ]
    if not report["items"]:
        lines.append("No source quality refinement items were produced.")
    else:
        lines.extend(
            [
                "| Vendor | Source | Source type | Status | HTTP | Final URL | Recommended review action |",
                "|---|---|---|---|---:|---|---|",
            ]
        )
        for item in report["items"]:
            lines.append(
                markdown_row(
                    [
                        item.get("vendor_id"),
                        item.get("source_id"),
                        item.get("source_type"),
                        item.get("verification_status"),
                        item.get("http_status"),
                        item.get("final_url"),
                        item.get("recommended_review_action"),
                    ]
                )
            )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Human review is required for every item.",
            "- Does not replace source URLs.",
            "- Does not mutate the catalog.",
            "- Does not create repair PRs.",
            "- Does not enable automerge.",
            "- Does not perform live network fetches.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-quality-refinement")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--source-verification-report", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, default=Path("source-quality-refinement-queue.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("source-quality-refinement-queue.csv"))
    parser.add_argument("--markdown-output", type=Path, default=Path("source-quality-refinement-summary.md"))
    args = parser.parse_args(argv)

    report = build_source_quality_refinement_queue(load_json(args.source_verification_report))
    write_json(report, args.json_output)
    write_csv(report, args.csv_output)
    write_markdown(report, args.markdown_output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
