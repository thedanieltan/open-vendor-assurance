from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "p0_source_repair_plan"
PLAN_SOURCE = "source_repair_sweep"
STRICT_BUCKET = "strict_repair_ready"
MAX_RECORDS_HARD_CAP = 10
DEFAULT_MAX_RECORDS = 10

SELF_CERTIFYING_FIELDS = {"eligible", "eligible_for_automerge", "tool_recommendation"}
ALLOWED_REPLACEMENT_STATUSES = {"ok", "redirected"}
ALLOWED_SEMANTIC_STATUSES = {"strong"}
ALLOWED_AUTHORITY_STATUSES = {"vendor_controlled", "approved_exception", "approved_vendor_source"}
ALLOWED_ACCESS_STATUSES = {"public", "public_web", "public_pdf"}
UNSAFE_REASON_CODES = {
    "access_ambiguous",
    "redirect_canonical_drift",
    "replacement_final_url_missing",
    "semantic_status_not_strong",
    "soft_404_detected",
    "source_type_ambiguous",
    "suspect_inferred_url",
    "unknown_verification_status",
    "weak_semantic_match",
}

REQUIRED_REPAIR_FIELDS = (
    "vendor_id",
    "source_id",
    "source_type",
    "original_source_url",
    "replacement_source_url",
    "replacement_verification_status",
    "replacement_http_status",
    "replacement_semantic_status",
    "replacement_authority_status",
    "replacement_access_status",
    "replacement_final_url",
)

REPAIR_FIELDS = [
    "vendor_id",
    "source_id",
    "source_type",
    "original_source_url",
    "replacement_source_url",
    "replacement_verification_status",
    "replacement_http_status",
    "replacement_semantic_status",
    "replacement_authority_status",
    "replacement_access_status",
    "replacement_url_safety_status",
    "replacement_final_url",
    "soft_404_detected",
    "redirect_canonical_drift",
    "source_repair_sweep_reason_codes",
]

CSV_FIELDS = REPAIR_FIELDS


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        for field in ("strict_repair_ready", "human_review_required", "no_replacement_found"):
            value = report.get(field)
            if isinstance(value, list):
                rows.extend(value)
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("expected sweep rows to be objects")
    return list(rows)


def sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_type") or ""),
        str(row.get("source_id") or ""),
        str(row.get("original_source_url") or ""),
    )


def has_truthy_bool(row: dict[str, Any], field: str) -> bool:
    value = row.get(field)
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def exclusion_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    reason_codes = set(normalize_reason_codes(row.get("reason_codes")))
    if row.get("bucket") != STRICT_BUCKET:
        reasons.append("not_strict_repair_ready")
    for field in REQUIRED_REPAIR_FIELDS:
        if row.get(field) in {None, ""}:
            reasons.append(f"{field}_missing")
    if row.get("replacement_verification_status") not in ALLOWED_REPLACEMENT_STATUSES:
        reasons.append("replacement_verification_status_not_ok")
    if row.get("replacement_semantic_status") not in ALLOWED_SEMANTIC_STATUSES:
        reasons.append("replacement_semantic_status_not_strong")
    if row.get("replacement_authority_status") not in ALLOWED_AUTHORITY_STATUSES:
        reasons.append("replacement_authority_status_not_allowed")
    if row.get("replacement_access_status") not in ALLOWED_ACCESS_STATUSES:
        reasons.append("replacement_access_status_not_public")
    if row.get("replacement_url_safety_status") not in {None, "", "passed"}:
        reasons.append("replacement_url_safety_status_not_passed")
    if has_truthy_bool(row, "soft_404_detected"):
        reasons.append("soft_404_detected")
    if has_truthy_bool(row, "redirect_canonical_drift"):
        reasons.append("redirect_canonical_drift")
    for reason in sorted(reason_codes & UNSAFE_REASON_CODES):
        if reason == "replacement_final_url_missing":
            reasons.append("final_url_missing")
        else:
            reasons.append(reason)
    if find_self_certifying_fields(row):
        reasons.append("self_certifying_field_present")
    return list(dict.fromkeys(reasons))


def repair_row(row: dict[str, Any]) -> dict[str, Any]:
    reason_codes = normalize_reason_codes(row.get("reason_codes"))
    return {
        "vendor_id": row.get("vendor_id"),
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "original_source_url": row.get("original_source_url"),
        "replacement_source_url": row.get("replacement_source_url"),
        "replacement_verification_status": row.get("replacement_verification_status"),
        "replacement_http_status": row.get("replacement_http_status"),
        "replacement_semantic_status": row.get("replacement_semantic_status"),
        "replacement_authority_status": row.get("replacement_authority_status"),
        "replacement_access_status": row.get("replacement_access_status"),
        "replacement_url_safety_status": row.get("replacement_url_safety_status") or "passed",
        "replacement_final_url": row.get("replacement_final_url"),
        "soft_404_detected": bool(row.get("soft_404_detected")),
        "redirect_canonical_drift": bool(row.get("redirect_canonical_drift")),
        "source_repair_sweep_reason_codes": reason_codes,
    }


def excluded_row(row: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "vendor_id": row.get("vendor_id"),
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "original_source_url": row.get("original_source_url"),
        "replacement_source_url": row.get("replacement_source_url"),
        "bucket": row.get("bucket"),
        "reason_codes": normalize_reason_codes(row.get("reason_codes")),
        "exclusion_reasons": reasons,
    }


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


def build_summary(
    rows: list[dict[str, Any]],
    repairs: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    max_records: int,
) -> dict[str, Any]:
    exclusion_counts = Counter(
        reason for row in excluded for reason in row.get("exclusion_reasons", [])
    )
    return {
        "sweep_rows_seen": len(rows),
        "max_records": max_records,
        "repair_count": len(repairs),
        "excluded_count": len(excluded),
        "strict_rows_seen": sum(1 for row in rows if row.get("bucket") == STRICT_BUCKET),
        "non_strict_rows_seen": sum(1 for row in rows if row.get("bucket") != STRICT_BUCKET),
        "excluded_by_reason": dict(sorted(exclusion_counts.items())),
    }


def build_source_repair_batch_plan(
    sweep_report: dict[str, Any],
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if max_records > MAX_RECORDS_HARD_CAP:
        raise ValueError(f"--max-records must be <= {MAX_RECORDS_HARD_CAP}")
    if max_records < 1:
        raise ValueError("--max-records must be >= 1")

    rows = sorted(validate_sweep_report(sweep_report), key=sort_key)
    repairs: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for row in rows:
        reasons = exclusion_reasons(row)
        if reasons:
            excluded.append(excluded_row(row, reasons))
            continue
        if len(repairs) >= max_records:
            excluded.append(excluded_row(row, ["over_max_records"]))
            continue
        repairs.append(repair_row(row))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or utc_now(),
        "report_type": REPORT_TYPE,
        "plan_source": PLAN_SOURCE,
        "batch_type": STRICT_BUCKET,
        "max_records": max_records,
        "posture": posture(),
        "inputs": {
            "source_repair_sweep_report_type": sweep_report.get("report_type"),
            "source_repair_sweep_generated_at": sweep_report.get("generated_at"),
        },
        "repairs": repairs,
        "excluded": excluded,
        "summary": build_summary(rows, repairs, excluded, max_records),
    }


def csv_row(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["source_repair_sweep_reason_codes"] = ";".join(
        normalize_reason_codes(output.get("source_repair_sweep_reason_codes"))
    )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(csv_row(row))


def build_markdown_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# OpenVA Strict Source Repair Batch Plan",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This plan contains only strict repair-ready rows selected from the source repair sweep.",
        "",
        "It is operational metadata only. It does not mutate catalog sources, open repair PRs, apply repairs, or enable automerge.",
        "",
        "## Summary",
        "",
        f"- Sweep rows seen: `{summary['sweep_rows_seen']}`",
        f"- Strict rows seen: `{summary['strict_rows_seen']}`",
        f"- Planned repairs: `{summary['repair_count']}`",
        f"- Excluded rows: `{summary['excluded_count']}`",
        f"- Max records: `{summary['max_records']}`",
        "",
        "## Excluded By Reason",
        "",
    ]
    if summary["excluded_by_reason"]:
        lines.extend(
            f"- `{reason}`: `{count}`"
            for reason, count in summary["excluded_by_reason"].items()
        )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Uses only `strict_repair_ready` sweep rows.",
            "- Caps every batch at 10 records.",
            "- Excludes unsafe diagnostics and self-certifying fields.",
            "- Does not invoke source repair actions.",
            "- Does not mutate catalog YAML.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], *, output_json: Path, output_csv: Path, output_md: Path) -> None:
    write_json(output_json, report)
    write_csv(output_csv, report["repairs"])
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(build_markdown_summary(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-batch")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--sweep-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=Path("source-repair-batch-plan.json"))
    parser.add_argument("--output-csv", type=Path, default=Path("source-repair-batch-plan.csv"))
    parser.add_argument("--output-md", type=Path, default=Path("source-repair-batch-summary.md"))
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    args = parser.parse_args(argv)

    report = build_source_repair_batch_plan(
        load_json(args.sweep_report),
        max_records=args.max_records,
    )
    write_outputs(
        report,
        output_json=args.output_json,
        output_csv=args.output_csv,
        output_md=args.output_md,
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
