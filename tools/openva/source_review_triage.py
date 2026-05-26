from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "source_review_triage_plan"

MANUAL_CANONICAL_URL_REVIEW = "manual_canonical_url_review"
ACCESS_AMBIGUOUS_REVIEW = "access_ambiguous_review"
SOFT_NOT_FOUND_REVIEW = "soft_not_found_review"
SOURCE_QUALITY_REVIEW = "source_quality_review"
MARK_NO_REPLACEMENT_AVAILABLE = "mark_no_replacement_available"
DEFER_VENDOR_SOURCE_UNPUBLISHED = "defer_vendor_source_unpublished"

SELF_CERTIFYING_FIELDS = {"eligible", "eligible_for_automerge", "tool_recommendation"}

ACCESS_AMBIGUOUS_STATUSES = {
    "bot_protected",
    "forbidden_unknown",
    "gated_or_login_required",
    "rate_limited",
    "unreachable",
}
QUALITY_STATUSES = {
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "suspect_inferred_url",
}
SOFT_NOT_FOUND_STATUSES = {"soft_not_found", "soft_404_detected"}
CANONICAL_REVIEW_REASONS = {
    "redirect_canonical_drift",
    "replacement_final_url_missing",
    "weak_semantic_match",
    "semantic_status_not_strong",
}
QUALITY_REVIEW_REASONS = {
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "suspect_inferred_url",
    "source_type_ambiguous",
    "source_type_changed",
    "weak_semantic_match",
}
UNPUBLISHED_HINT_REASONS = {
    "source_not_available",
    "source_unpublished",
    "vendor_source_unpublished",
    "vendor_does_not_publish_source",
}

RECOMMENDED_NEXT_ACTION = {
    MANUAL_CANONICAL_URL_REVIEW: "Review final canonical URL and semantic match before any repair.",
    ACCESS_AMBIGUOUS_REVIEW: "Review source access manually; do not infer content validity from blocked access.",
    SOFT_NOT_FOUND_REVIEW: "Confirm whether the source is a soft 404 before considering any replacement.",
    SOURCE_QUALITY_REVIEW: "Review source quality, authority, and source_type match before repair.",
    MARK_NO_REPLACEMENT_AVAILABLE: "Keep source unavailable / not available until a public vendor source is verified.",
    DEFER_VENDOR_SOURCE_UNPUBLISHED: "Defer until the vendor publishes a usable public source.",
}

CSV_FIELDS = [
    "vendor_id",
    "source_id",
    "source_type",
    "source_url",
    "final_url",
    "http_status",
    "verification_status",
    "bucket",
    "reason_codes",
    "recommended_next_action",
    "requires_human_review",
    "may_repair_automatically",
    "notes",
]

BUCKET_ORDER = (
    MANUAL_CANONICAL_URL_REVIEW,
    ACCESS_AMBIGUOUS_REVIEW,
    SOFT_NOT_FOUND_REVIEW,
    SOURCE_QUALITY_REVIEW,
    MARK_NO_REPLACEMENT_AVAILABLE,
    DEFER_VENDOR_SOURCE_UNPUBLISHED,
)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def read_optional_text(path: Path | None) -> str | None:
    if path is None:
        return None
    return path.read_text(encoding="utf-8")


def normalize_reason_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def find_self_certifying_fields(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SELF_CERTIFYING_FIELDS:
                found.append(key)
            found.extend(find_self_certifying_fields(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_self_certifying_fields(child))
    return found


def validate_sweep_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != "source_repair_sweep":
        raise ValueError("expected sweep report_type=source_repair_sweep")
    records = report.get("records")
    if isinstance(records, list):
        rows = records
    else:
        rows = []
        for field in ("human_review_required", "no_replacement_found"):
            value = report.get(field)
            if isinstance(value, list):
                rows.extend(value)
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("expected sweep rows to be objects")
    return [row for row in rows if row.get("bucket") in {"human_review_required", "no_replacement_found"}]


def has_truthy(row: dict[str, Any], field: str) -> bool:
    value = row.get(field)
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def classify_bucket(row: dict[str, Any]) -> str:
    status = str(row.get("original_status") or row.get("verification_status") or "")
    reasons = set(normalize_reason_codes(row.get("reason_codes")))
    if row.get("bucket") == "no_replacement_found":
        if reasons & UNPUBLISHED_HINT_REASONS:
            return DEFER_VENDOR_SOURCE_UNPUBLISHED
        return MARK_NO_REPLACEMENT_AVAILABLE
    if has_truthy(row, "soft_404_detected") or status in SOFT_NOT_FOUND_STATUSES or reasons & {"soft_404_detected", "soft_not_found"}:
        return SOFT_NOT_FOUND_REVIEW
    if status in ACCESS_AMBIGUOUS_STATUSES or "access_ambiguous" in reasons:
        return ACCESS_AMBIGUOUS_REVIEW
    if has_truthy(row, "redirect_canonical_drift") or reasons & CANONICAL_REVIEW_REASONS:
        return MANUAL_CANONICAL_URL_REVIEW
    if status in QUALITY_STATUSES or reasons & QUALITY_REVIEW_REASONS:
        return SOURCE_QUALITY_REVIEW
    return MANUAL_CANONICAL_URL_REVIEW


def row_notes(row: dict[str, Any], bucket: str) -> str:
    if bucket == ACCESS_AMBIGUOUS_REVIEW:
        return "Access is ambiguous or blocked; do not treat endpoint reachability as content verification."
    if bucket == SOFT_NOT_FOUND_REVIEW:
        return "HTTP success may be a soft 404; verify content manually before any repair."
    if bucket == SOURCE_QUALITY_REVIEW:
        return "Source may be generic, mismatched, inferred, or source-type ambiguous."
    if bucket == MARK_NO_REPLACEMENT_AVAILABLE:
        return "No verified public vendor-controlled replacement was found in the sweep."
    if bucket == DEFER_VENDOR_SOURCE_UNPUBLISHED:
        return "Vendor source appears unpublished; defer until a public source is available."
    return "Canonical final URL or semantic fit needs manual confirmation."


def triage_row(row: dict[str, Any]) -> dict[str, Any]:
    bucket = classify_bucket(row)
    return {
        "vendor_id": row.get("vendor_id"),
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "source_url": row.get("original_source_url") or row.get("source_url"),
        "final_url": row.get("original_final_url") or row.get("final_url"),
        "http_status": row.get("original_http_status") or row.get("http_status"),
        "verification_status": row.get("original_status") or row.get("verification_status"),
        "bucket": bucket,
        "reason_codes": normalize_reason_codes(row.get("reason_codes")),
        "recommended_next_action": RECOMMENDED_NEXT_ACTION[bucket],
        "requires_human_review": True,
        "may_repair_automatically": False,
        "notes": row_notes(row, bucket),
    }


def sort_key(row: dict[str, Any]) -> tuple[int, str, str, str, str]:
    bucket = str(row.get("bucket") or "")
    try:
        bucket_index = BUCKET_ORDER.index(bucket)
    except ValueError:
        bucket_index = len(BUCKET_ORDER)
    return (
        bucket_index,
        str(row.get("vendor_id") or ""),
        str(row.get("source_type") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_url") or ""),
    )


def bounded_counter(rows: list[dict[str, Any]], field: str, limit: int = 25) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "unknown") for row in rows)
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit])


def posture() -> dict[str, bool]:
    return {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "report_only": True,
        "non_advisory": True,
    }


def build_source_review_triage_plan(
    sweep_report: dict[str, Any],
    *,
    human_review_csv: str | None = None,
    no_replacement_csv: str | None = None,
    sweep_summary_md: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    rows = validate_sweep_report(sweep_report)
    triage_rows = [triage_row(row) for row in rows]
    triage_rows.sort(key=sort_key)
    bucket_counts = Counter(row["bucket"] for row in triage_rows)
    reason_counts = Counter(reason for row in triage_rows for reason in row.get("reason_codes", []))
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": REPORT_TYPE,
        "posture": posture(),
        "inputs": {
            "source_repair_sweep_report_type": sweep_report.get("report_type"),
            "source_repair_sweep_generated_at": sweep_report.get("generated_at"),
            "human_review_csv_provided": human_review_csv is not None,
            "no_replacement_csv_provided": no_replacement_csv is not None,
            "sweep_summary_md_provided": sweep_summary_md is not None,
        },
        "summary": {
            "triage_rows": len(triage_rows),
            "bucket_counts": dict(sorted(bucket_counts.items())),
            "reason_code_counts": dict(sorted(reason_counts.items())),
            "top_source_types": bounded_counter(triage_rows, "source_type"),
            "top_vendor_ids": bounded_counter(triage_rows, "vendor_id"),
            "may_repair_automatically_count": sum(1 for row in triage_rows if row["may_repair_automatically"]),
            "requires_human_review_count": sum(1 for row in triage_rows if row["requires_human_review"]),
        },
        "items": triage_rows,
    }
    if find_self_certifying_fields(report):
        raise ValueError("triage report contains self-certifying fields")
    return report


def write_json(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def csv_row(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["reason_codes"] = ";".join(normalize_reason_codes(output.get("reason_codes")))
    return output


def write_csv(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in report["items"]:
            writer.writerow(csv_row(row))


def counter_lines(counter: dict[str, int]) -> list[str]:
    if not counter:
        return ["- None"]
    return [f"- `{key}`: `{value}`" for key, value in counter.items()]


def build_markdown_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# OpenVA Source Review Triage Summary",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This report translates non-strict source repair sweep rows into maintainer review queues.",
        "",
        "It is operational metadata only. It does not mutate catalog sources, replace URLs, generate repair PRs, or enable automerge.",
        "",
        "## Summary",
        "",
        f"- Triage rows: `{summary['triage_rows']}`",
        f"- Requires human review: `{summary['requires_human_review_count']}`",
        f"- May repair automatically: `{summary['may_repair_automatically_count']}`",
        "",
        "## Bucket Counts",
        "",
        *counter_lines(summary["bucket_counts"]),
        "",
        "## Top Source Types",
        "",
        *counter_lines(summary["top_source_types"]),
        "",
        "## Top Vendors",
        "",
        *counter_lines(summary["top_vendor_ids"]),
        "",
        "## Guardrails",
        "",
        "- Human-review rows must not enter strict repair PRs.",
        "- No-replacement rows must remain unavailable until a public vendor source is verified.",
        "- Do not invent vendor URLs.",
        "- Do not infer content validity from access-blocked or bot-protected endpoints.",
        "- Do not automatically repair soft 404s, redirect drift, weak matches, inferred URLs, or source-type ambiguity.",
        "",
    ]
    return "\n".join(lines)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown_summary(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-review-triage")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--sweep-report", type=Path, required=True)
    parser.add_argument("--human-review-csv", type=Path)
    parser.add_argument("--no-replacement-csv", type=Path)
    parser.add_argument("--sweep-summary-md", type=Path)
    parser.add_argument("--output-json", type=Path, default=Path("source-review-triage-plan.json"))
    parser.add_argument("--output-csv", type=Path, default=Path("source-review-triage-plan.csv"))
    parser.add_argument("--output-md", type=Path, default=Path("source-review-triage-summary.md"))
    args = parser.parse_args(argv)

    report = build_source_review_triage_plan(
        load_json(args.sweep_report),
        human_review_csv=read_optional_text(args.human_review_csv),
        no_replacement_csv=read_optional_text(args.no_replacement_csv),
        sweep_summary_md=read_optional_text(args.sweep_summary_md),
    )
    write_json(report, args.output_json)
    write_csv(report, args.output_csv)
    write_markdown(report, args.output_md)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
