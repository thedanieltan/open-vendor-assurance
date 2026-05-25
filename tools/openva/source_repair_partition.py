from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

VALIDATION_REPORT_TYPE = "p0_source_repair_plan_validation"
EVIDENCE_REPORT_TYPE = "p0_source_repair_evidence"
PARTITION_REPORT_TYPE = "p0_source_repair_partition"

SELF_CERTIFYING_FIELDS = {
    "eligible",
    "eligible_for_automerge",
    "tool_recommendation",
}

ALLOWED_STATUS_PAIRS = {
    ("not_found", "not_found"),
    ("gone", "gone"),
}
ALLOWED_REPLACEMENT_STATUSES = {"ok", "redirected"}
ALLOWED_AUTHORITY_STATUSES = {"vendor_controlled", "approved_vendor_source"}
ALLOWED_ACCESS_STATUSES = {"public"}

POSITIVE_REASON_ORDER = (
    "approved_validation_row",
    "confirmed_p0",
    "replacement_ok",
    "replacement_redirected",
    "http_status_2xx_or_3xx",
    "semantic_strong",
    "authority_allowed",
    "public_access",
    "url_safety_passed",
    "source_type_unchanged",
    "replacement_url_differs",
)

NEGATIVE_REASON_ORDER = (
    "validation_not_approved",
    "evidence_missing",
    "status_pair_not_confirmed_p0",
    "semantic_status_not_strong",
    "authority_not_allowed",
    "access_not_public",
    "url_safety_not_passed",
    "source_type_changed",
    "replacement_url_same_as_original",
    "self_certifying_field_present",
    "unknown_or_unsupported_status",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_policy(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalize_url(url: str) -> str:
    return url.strip().rstrip("#").rstrip("?").rstrip("/")


def validation_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("original_source_url") or ""),
    )


def evidence_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_url") or ""),
    )


def sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_type") or ""),
        str(row.get("original_source_url") or row.get("source_url") or ""),
    )


def ordered_reasons(reasons: set[str], preferred: tuple[str, ...]) -> list[str]:
    ordered = [reason for reason in preferred if reason in reasons]
    ordered.extend(sorted(reasons - set(ordered)))
    return ordered


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


def validate_validation_report(report: dict[str, Any]) -> None:
    if report.get("report_type") != VALIDATION_REPORT_TYPE:
        raise ValueError(f"expected validation report_type={VALIDATION_REPORT_TYPE}")
    for field in ("approved", "rejected", "unmatched"):
        value = report.get(field)
        if not isinstance(value, list):
            raise ValueError(f"expected validation {field} list")
        if not all(isinstance(row, dict) for row in value):
            raise ValueError(f"expected validation {field} rows to be objects")


def validate_evidence_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != EVIDENCE_REPORT_TYPE:
        raise ValueError(f"expected evidence report_type={EVIDENCE_REPORT_TYPE}")
    repairs = report.get("repairs")
    if not isinstance(repairs, list):
        raise ValueError("expected evidence repairs list")
    if not all(isinstance(row, dict) for row in repairs):
        raise ValueError("expected evidence repair rows to be objects")
    return repairs


def evidence_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        indexed.setdefault(evidence_key(row), row)
    return indexed


def is_2xx_or_3xx(status: Any) -> bool:
    return isinstance(status, int) and 200 <= status < 400


def status_pair(evidence_row: dict[str, Any]) -> tuple[Any, Any]:
    original = evidence_row.get("original")
    prior = original.get("prior") if isinstance(original, dict) else None
    fresh = original.get("fresh") if isinstance(original, dict) else None
    if not isinstance(prior, dict) or not isinstance(fresh, dict):
        return None, None
    return prior.get("verification_status"), fresh.get("verification_status")


def evaluate_row(
    row: dict[str, Any],
    evidence_by_key: dict[tuple[str, str, str], dict[str, Any]],
    *,
    approved: bool,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    positive: set[str] = set()
    negative: set[str] = set()

    if approved:
        positive.add("approved_validation_row")
    else:
        negative.add("validation_not_approved")

    evidence_row = evidence_by_key.get(validation_key(row))
    if evidence_row is None:
        negative.add("evidence_missing")
    else:
        if status_pair(evidence_row) in ALLOWED_STATUS_PAIRS:
            positive.add("confirmed_p0")
        else:
            negative.add("status_pair_not_confirmed_p0")

        if row.get("source_type") == evidence_row.get("source_type"):
            positive.add("source_type_unchanged")
        else:
            negative.add("source_type_changed")

    replacement_status = row.get("replacement_verification_status")
    if replacement_status == "ok":
        positive.add("replacement_ok")
    elif replacement_status == "redirected":
        positive.add("replacement_redirected")
    else:
        negative.add("unknown_or_unsupported_status")

    if is_2xx_or_3xx(row.get("replacement_http_status")):
        positive.add("http_status_2xx_or_3xx")
    else:
        negative.add("unknown_or_unsupported_status")

    if row.get("replacement_semantic_status") == "strong":
        positive.add("semantic_strong")
    else:
        negative.add("semantic_status_not_strong")

    if row.get("replacement_authority_status") in ALLOWED_AUTHORITY_STATUSES:
        positive.add("authority_allowed")
    else:
        negative.add("authority_not_allowed")

    if row.get("replacement_access_status") in ALLOWED_ACCESS_STATUSES:
        positive.add("public_access")
    else:
        negative.add("access_not_public")

    if row.get("replacement_url_safety_status") == "passed":
        positive.add("url_safety_passed")
    else:
        negative.add("url_safety_not_passed")

    original_url = str(row.get("original_source_url") or "")
    replacement_url = str(row.get("replacement_source_url") or "")
    if replacement_url and normalize_url(replacement_url) != normalize_url(original_url):
        positive.add("replacement_url_differs")
    else:
        negative.add("replacement_url_same_as_original")

    if find_self_certifying_fields(row) or (evidence_row is not None and find_self_certifying_fields(evidence_row)):
        negative.add("self_certifying_field_present")

    if negative:
        return False, ordered_reasons(negative, NEGATIVE_REASON_ORDER), evidence_row
    return True, ordered_reasons(positive, POSITIVE_REASON_ORDER), evidence_row


def report_item(row: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "vendor_id": row.get("vendor_id"),
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "original_source_url": row.get("original_source_url"),
        "replacement_source_url": row.get("replacement_source_url"),
        "reasons": reasons,
    }


def posture() -> dict[str, bool]:
    return {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "non_advisory": True,
    }


def build_validation_partition(
    source_validation: dict[str, Any],
    *,
    approved: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    unmatched: list[dict[str, Any]],
) -> dict[str, Any]:
    approved = sorted(approved, key=sort_key)
    rejected = sorted(rejected, key=sort_key)
    unmatched = sorted(unmatched, key=sort_key)
    total = len(approved) + len(rejected) + len(unmatched)
    return {
        "schema_version": source_validation.get("schema_version", "0.1.0"),
        "generated_at": utc_now(),
        "report_type": VALIDATION_REPORT_TYPE,
        "posture": posture(),
        "inputs": {
            **(source_validation.get("inputs") if isinstance(source_validation.get("inputs"), dict) else {}),
            "partitioned_from_validation_generated_at": source_validation.get("generated_at"),
            "partitioned_from_validation_report_type": source_validation.get("report_type"),
        },
        "approved": approved,
        "rejected": rejected,
        "unmatched": unmatched,
        "summary": {
            "evidence_repair_count": source_validation.get("summary", {}).get("evidence_repair_count")
            if isinstance(source_validation.get("summary"), dict)
            else None,
            "plan_repair_count": total,
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "unmatched_count": len(unmatched),
        },
    }


def build_markdown_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# P0 Source Repair Partition Summary",
        "",
        "## Counts",
        "",
        f"- Total rows: `{summary['total_rows']}`",
        f"- Automerge eligible: `{summary['automerge_eligible_count']}`",
        f"- Manual review required: `{summary['manual_review_required_count']}`",
        f"- Excluded: `{summary['excluded_count']}`",
        "",
        "## Guardrails",
        "",
        "- Partitioned before source YAML changes are applied.",
        "- Automerge rows satisfy strict Layer 2B row eligibility checks.",
        "- Manual-review rows retain deterministic reason codes.",
        "- No catalog source records are mutated by this report.",
        "",
    ]
    if report["manual_review_required"]:
        lines.extend(["## Manual Review Reasons", ""])
        for item in report["manual_review_required"]:
            vendor = item.get("vendor_id")
            source = item.get("source_id")
            reasons = ", ".join(f"`{reason}`" for reason in item.get("reasons", []))
            lines.append(f"- `{vendor}/{source}`: {reasons}")
        lines.append("")
    return "\n".join(lines)


def partition_source_repair_validation(
    *,
    evidence: dict[str, Any],
    validation: dict[str, Any],
    source_validation_report: str,
    source_evidence_report: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    validate_validation_report(validation)
    evidence_rows = validate_evidence_report(evidence)
    evidence_by_key = evidence_index(evidence_rows)

    automerge_approved: list[dict[str, Any]] = []
    manual_approved: list[dict[str, Any]] = []
    manual_rejected: list[dict[str, Any]] = []
    manual_unmatched: list[dict[str, Any]] = []
    automerge_items: list[dict[str, Any]] = []
    manual_items: list[dict[str, Any]] = []

    for row in validation["approved"]:
        eligible, reasons, _ = evaluate_row(row, evidence_by_key, approved=True)
        if eligible:
            automerge_approved.append(row)
            automerge_items.append(report_item(row, reasons))
        else:
            manual_approved.append(row)
            manual_items.append(report_item(row, reasons))

    for field, target in (("rejected", manual_rejected), ("unmatched", manual_unmatched)):
        for row in validation[field]:
            _, reasons, _ = evaluate_row(row, evidence_by_key, approved=False)
            target.append(row)
            manual_items.append(report_item(row, reasons))

    automerge_items = sorted(automerge_items, key=sort_key)
    manual_items = sorted(manual_items, key=sort_key)
    excluded: list[dict[str, Any]] = []
    total = len(validation["approved"]) + len(validation["rejected"]) + len(validation["unmatched"])

    report = {
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "report_type": PARTITION_REPORT_TYPE,
        "source_validation_report": source_validation_report,
        "source_evidence_report": source_evidence_report,
        "summary": {
            "total_rows": total,
            "automerge_eligible_count": len(automerge_items),
            "manual_review_required_count": len(manual_items),
            "excluded_count": len(excluded),
        },
        "automerge_eligible": automerge_items,
        "manual_review_required": manual_items,
        "excluded": excluded,
    }
    automerge_validation = build_validation_partition(
        validation,
        approved=automerge_approved,
        rejected=[],
        unmatched=[],
    )
    manual_validation = build_validation_partition(
        validation,
        approved=manual_approved,
        rejected=manual_rejected,
        unmatched=manual_unmatched,
    )
    return automerge_validation, manual_validation, report, build_markdown_summary(report)


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-partition")
    subparsers = parser.add_subparsers(dest="command", required=True)
    partition = subparsers.add_parser("partition")
    partition.add_argument("--evidence", type=Path, required=True)
    partition.add_argument("--validation", type=Path, required=True)
    partition.add_argument("--automerge-output", type=Path, required=True)
    partition.add_argument("--manual-output", type=Path, required=True)
    partition.add_argument("--report-output", type=Path, required=True)
    partition.add_argument("--summary-output", type=Path, required=True)
    partition.add_argument("--policy", type=Path, default=Path("config/automerge-policy.yaml"))

    args = parser.parse_args()
    if args.command == "partition":
        load_policy(args.policy)
        automerge_validation, manual_validation, report, markdown = partition_source_repair_validation(
            evidence=load_json(args.evidence),
            validation=load_json(args.validation),
            source_validation_report=str(args.validation),
            source_evidence_report=str(args.evidence),
        )
        write_json(args.automerge_output, automerge_validation)
        write_json(args.manual_output, manual_validation)
        write_json(args.report_output, report)
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(markdown, encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
