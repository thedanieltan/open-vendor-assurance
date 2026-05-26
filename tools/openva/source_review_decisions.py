from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from tools.openva.source_verification import FetchResult, fetch_url, verify_source
from tools.openva.url_safety import validate_url_safety

SCHEMA_VERSION = "0.1.0"
SHEET_REPORT_TYPE = "source_review_decision_sheet"
VALIDATION_REPORT_TYPE = "source_review_decision_validation"
UNKNOWN_SOURCE_MAINTENANCE_RUN_ID = "unknown-source-maintenance-run"

ALLOWED_DECISIONS = {
    "replace_with_url",
    "mark_no_replacement_available",
    "defer_access_ambiguous",
    "defer_needs_vendor_confirmation",
    "reject_candidate_mismatch",
    "keep_existing_source",
}

SELF_CERTIFYING_FIELDS = {"eligible", "eligible_for_automerge", "tool_recommendation"}
FORMULA_PREFIXES = ("=", "+", "-", "@")
TRACKING_PARAMS = {
    "dclid",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "yclid",
}

BINDING_COLUMNS = [
    "source_maintenance_run_id",
    "triage_plan_sha256",
    "decision_sheet_generated_at",
]
CONTEXT_COLUMNS = BINDING_COLUMNS + [
    "review_item_id",
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
    "candidate_url",
    "candidate_final_url",
]
EDITABLE_COLUMNS = [
    "review_decision",
    "approved_replacement_url",
    "reviewer_note",
    "reviewed_by",
    "reviewed_at",
]
CSV_FIELDS = CONTEXT_COLUMNS + EDITABLE_COLUMNS

IMMUTABLE_COLUMNS = [
    "source_maintenance_run_id",
    "triage_plan_sha256",
    "decision_sheet_generated_at",
    "review_item_id",
    "vendor_id",
    "source_id",
    "source_type",
    "source_url",
]
REVIEWER_METADATA_FIELDS = ["reviewer_note", "reviewed_by", "reviewed_at"]

ALLOWED_REPLACEMENT_VERIFICATION_STATUSES = {"ok", "redirected"}
ALLOWED_AUTHORITY_STATUSES = {"vendor_controlled", "approved_exception"}
ALLOWED_ACCESS_STATUSES = {"public", "public_web", "public_pdf"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stable_json_sha256(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_maintenance_run_id_for(triage_plan: dict[str, Any]) -> str:
    for field in ("source_maintenance_run_id", "run_id", "github_run_id"):
        value = triage_plan.get(field)
        if value:
            return str(value)
    metadata = triage_plan.get("metadata")
    if isinstance(metadata, dict):
        for field in ("source_maintenance_run_id", "run_id", "github_run_id"):
            value = metadata.get(field)
            if value:
                return str(value)
    return UNKNOWN_SOURCE_MAINTENANCE_RUN_ID


def binding_context_for(triage_plan: dict[str, Any], *, generated_at: str) -> dict[str, str]:
    return {
        "source_maintenance_run_id": source_maintenance_run_id_for(triage_plan),
        "triage_plan_sha256": stable_json_sha256(triage_plan),
        "decision_sheet_generated_at": generated_at,
    }


def csv_safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        text = ";".join(str(item) for item in value)
    else:
        text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def normalize_reason_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            query,
            parsed.fragment,
        )
    ).rstrip("#?/")


def without_tracking_params(url: str) -> str:
    parsed = urlparse(url.strip())
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not (key.lower().startswith("utm_") or key.lower() in TRACKING_PARAMS)
        )
    )
    return canonical_url(urlunparse(parsed._replace(query=query)))


def same_or_tracking_only_url(left: str, right: str) -> tuple[bool, bool]:
    left_canonical = canonical_url(left)
    right_canonical = canonical_url(right)
    same = left_canonical == right_canonical
    tracking_only = (
        not same
        and without_tracking_params(left) == without_tracking_params(right)
    )
    return same, tracking_only


def review_item_id_for(item: dict[str, Any]) -> str:
    existing = item.get("review_item_id")
    if existing:
        return str(existing)
    material = "\x1f".join(
        str(item.get(field) or "")
        for field in ("vendor_id", "source_id", "source_type", "source_url")
    )
    return f"srdi-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def triage_items(triage_plan: dict[str, Any]) -> list[dict[str, Any]]:
    if triage_plan.get("report_type") != "source_review_triage_plan":
        raise ValueError("expected triage report_type=source_review_triage_plan")
    items = triage_plan.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("expected triage items list")
    return items


def candidate_url_from(item: dict[str, Any]) -> str:
    for field in ("candidate_url", "replacement_source_url", "approved_candidate_url"):
        if item.get(field):
            return str(item[field])
    return ""


def candidate_final_url_from(item: dict[str, Any]) -> str:
    for field in ("candidate_final_url", "replacement_final_url", "candidate_resolved_final_url"):
        if item.get(field):
            return str(item[field])
    return ""


def sheet_row_from_item(item: dict[str, Any], binding_context: dict[str, str]) -> dict[str, str]:
    row = {
        **binding_context,
        "review_item_id": review_item_id_for(item),
        "vendor_id": item.get("vendor_id"),
        "source_id": item.get("source_id"),
        "source_type": item.get("source_type"),
        "source_url": item.get("source_url"),
        "final_url": item.get("final_url"),
        "http_status": item.get("http_status"),
        "verification_status": item.get("verification_status"),
        "bucket": item.get("bucket"),
        "reason_codes": normalize_reason_codes(item.get("reason_codes")),
        "recommended_next_action": item.get("recommended_next_action"),
        "candidate_url": candidate_url_from(item),
        "candidate_final_url": candidate_final_url_from(item),
        "review_decision": "",
        "approved_replacement_url": "",
        "reviewer_note": "",
        "reviewed_by": "",
        "reviewed_at": "",
    }
    return {field: csv_safe(row.get(field)) for field in CSV_FIELDS}


def build_decision_sheet(triage_plan: dict[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or now_iso()
    items = triage_items(triage_plan)
    binding_context = binding_context_for(triage_plan, generated_at=generated_at)
    rows = [sheet_row_from_item(item, binding_context) for item in items]
    bucket_counts = Counter(str(item.get("bucket") or "unknown") for item in items)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "report_type": SHEET_REPORT_TYPE,
        "source_maintenance_run_id": binding_context["source_maintenance_run_id"],
        "triage_plan_sha256": binding_context["triage_plan_sha256"],
        "summary": {
            "review_rows": len(rows),
            "bucket_counts": dict(sorted(bucket_counts.items())),
            "review_decision_default_blank": True,
        },
        "posture": {
            "reviewer_input_trusted": False,
            "independent_validation_required": True,
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "report_only": True,
            "non_advisory": True,
        },
        "rows": rows,
    }


def write_sheet_csv(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow(row)


def counter_lines(counter: dict[str, int]) -> list[str]:
    if not counter:
        return ["- None"]
    return [f"- `{key}`: `{value}`" for key, value in counter.items()]


def build_sheet_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "# OpenVA Source Review Decision Sheet",
            "",
            f"Generated: {report['generated_at']}",
            f"Source maintenance run: `{report['source_maintenance_run_id']}`",
            f"Triage plan SHA-256: `{report['triage_plan_sha256']}`",
            "",
            "This decision sheet is a reviewer-friendly handoff for source triage rows.",
            "",
            "## Summary",
            "",
            f"- Review rows: `{summary['review_rows']}`",
            "- Default review_decision: `blank`",
            "",
            "## Bucket Counts",
            "",
            *counter_lines(summary["bucket_counts"]),
            "",
            "## Reviewer Guardrails",
            "",
            "- Editing this sheet does not mutate the catalog.",
            "- Reviewer decisions are not trusted until independently validated.",
            "- Approved replacements still require source verification.",
            "- No-replacement decisions do not invent URLs.",
            "- The sheet must validate against the triage plan with the matching SHA-256.",
            "- Repair PRs are generated only from validated reviewed artifacts in a later workflow.",
            "",
            "## Allowed Decisions",
            "",
            *[f"- `{decision}`" for decision in sorted(ALLOWED_DECISIONS)],
            "",
        ]
    )


def write_sheet_markdown(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_sheet_markdown(report), encoding="utf-8")


def invalid_row(row_number: int, review_item_id: str | None, reason_codes: list[str], message: str) -> dict[str, Any]:
    return {
        "row_number": row_number,
        "review_item_id": review_item_id or "",
        "reason_codes": reason_codes,
        "message": message,
    }


def expected_csv_value(item: dict[str, Any], field: str, binding_context: dict[str, str]) -> str:
    if field in binding_context:
        return csv_safe(binding_context[field])
    if field == "review_item_id":
        return csv_safe(review_item_id_for(item))
    if field == "reason_codes":
        return csv_safe(normalize_reason_codes(item.get(field)))
    if field == "candidate_url":
        return csv_safe(candidate_url_from(item))
    if field == "candidate_final_url":
        return csv_safe(candidate_final_url_from(item))
    return csv_safe(item.get(field))


def build_triage_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        review_item_id = review_item_id_for(item)
        if review_item_id in index:
            raise ValueError(f"duplicate triage review_item_id: {review_item_id}")
        index[review_item_id] = item
    return index


def blank(value: Any) -> bool:
    return str(value or "").strip() == ""


def has_required_metadata(row: dict[str, Any]) -> list[str]:
    return [field for field in REVIEWER_METADATA_FIELDS if blank(row.get(field))]


def host_is_same_or_subdomain(host: str, reference: str) -> bool:
    host = host.lower().rstrip(".")
    reference = reference.lower().rstrip(".")
    return host == reference or host.endswith(f".{reference}") or reference.endswith(f".{host}")


def authority_status(original_url: str, replacement_url: str) -> str:
    original_host = urlparse(original_url).hostname
    replacement_host = urlparse(replacement_url).hostname
    if original_host and replacement_host and host_is_same_or_subdomain(replacement_host, original_host):
        return "vendor_controlled"
    return "unknown"


def access_status(http_status: int | None, content_type: str | None) -> str:
    if http_status is None or not (200 <= http_status < 400):
        return "not_public"
    if content_type and "pdf" in content_type.lower():
        return "public_pdf"
    return "public_web"


def verify_replacement_url(
    item: dict[str, Any],
    replacement_url: str,
    fetcher: Callable[[str], FetchResult] = fetch_url,
) -> dict[str, Any]:
    safety_failures = validate_url_safety(replacement_url)
    if safety_failures:
        return {
            "ok": False,
            "reason_codes": ["replacement_url_safety_not_passed"],
            "message": "; ".join(safety_failures),
            "url_safety_status": "failed",
        }

    try:
        verification = verify_source(
            {
                "vendor_id": item.get("vendor_id"),
                "source_id": item.get("source_id"),
                "source_type": item.get("source_type"),
                "source_url": replacement_url,
            },
            Path("source-review-decision-sheet.csv"),
            fetcher=fetcher,
        )
    except Exception as exc:  # noqa: BLE001 - reviewer approval must fail closed on verification errors.
        return {
            "ok": False,
            "reason_codes": ["live_verification_error"],
            "message": f"{type(exc).__name__}: {exc}",
            "url_safety_status": "passed",
        }

    final_url = str(verification.get("final_url") or replacement_url)
    http_status = verification.get("http_status")
    semantic_status = str((verification.get("semantic_match") or {}).get("status") or "")
    replacement_authority = authority_status(str(item.get("source_url") or ""), final_url)
    replacement_access = access_status(http_status if isinstance(http_status, int) else None, verification.get("content_type"))
    redirect_canonical_drift = canonical_url(replacement_url) != canonical_url(final_url)
    soft_404 = verification.get("soft_404_detected") is True
    status = str(verification.get("verification_status") or "")

    reasons: list[str] = []
    if status not in ALLOWED_REPLACEMENT_VERIFICATION_STATUSES:
        reasons.append("replacement_verification_status_not_ok")
    if not isinstance(http_status, int) or http_status < 200 or http_status >= 400:
        reasons.append("replacement_http_status_not_2xx_or_3xx")
    if soft_404:
        reasons.append("soft_404_detected")
    if semantic_status != "strong":
        reasons.append("replacement_semantic_status_not_strong")
    if replacement_authority not in ALLOWED_AUTHORITY_STATUSES:
        reasons.append("replacement_authority_status_not_allowed")
    if replacement_access not in ALLOWED_ACCESS_STATUSES:
        reasons.append("replacement_access_status_not_public")
    if redirect_canonical_drift:
        reasons.append("redirect_canonical_drift")

    return {
        "ok": not reasons,
        "reason_codes": reasons,
        "message": "replacement passed independent verification" if not reasons else "replacement failed independent verification",
        "replacement_source_url": replacement_url,
        "replacement_final_url": final_url,
        "replacement_verification_status": status,
        "replacement_http_status": http_status,
        "replacement_semantic_status": semantic_status,
        "replacement_authority_status": replacement_authority,
        "replacement_access_status": replacement_access,
        "replacement_url_safety_status": "passed",
        "soft_404_detected": soft_404,
        "redirect_canonical_drift": redirect_canonical_drift,
    }


def approved_repair_record(
    item: dict[str, Any],
    row: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    return {
        "vendor_id": item.get("vendor_id"),
        "source_id": item.get("source_id"),
        "source_type": item.get("source_type"),
        "original_source_url": item.get("source_url"),
        "replacement_source_url": verification.get("replacement_source_url"),
        "replacement_final_url": verification.get("replacement_final_url"),
        "replacement_verification_status": verification.get("replacement_verification_status"),
        "replacement_http_status": verification.get("replacement_http_status"),
        "replacement_semantic_status": verification.get("replacement_semantic_status"),
        "replacement_authority_status": verification.get("replacement_authority_status"),
        "replacement_access_status": verification.get("replacement_access_status"),
        "replacement_url_safety_status": verification.get("replacement_url_safety_status"),
        "soft_404_detected": False,
        "redirect_canonical_drift": False,
        "source_maintenance_run_id": row.get("source_maintenance_run_id"),
        "triage_plan_sha256": row.get("triage_plan_sha256"),
        "decision_sheet_generated_at": row.get("decision_sheet_generated_at"),
        "reviewer_note": row.get("reviewer_note"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "source_review_decision_id": review_item_id_for(item),
    }


def no_replacement_record(item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_id": item.get("vendor_id"),
        "source_id": item.get("source_id"),
        "source_type": item.get("source_type"),
        "source_url": item.get("source_url"),
        "truth_state": "no_public_vendor_source_found",
        "source_maintenance_run_id": row.get("source_maintenance_run_id"),
        "triage_plan_sha256": row.get("triage_plan_sha256"),
        "decision_sheet_generated_at": row.get("decision_sheet_generated_at"),
        "reviewer_note": row.get("reviewer_note"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "source_review_decision_id": review_item_id_for(item),
        "requires_catalog_truth_state_followup": True,
    }


def deferred_record(item: dict[str, Any], row: dict[str, Any], truth_state: str) -> dict[str, Any]:
    return {
        "vendor_id": item.get("vendor_id"),
        "source_id": item.get("source_id"),
        "source_type": item.get("source_type"),
        "source_url": item.get("source_url"),
        "truth_state": truth_state,
        "source_maintenance_run_id": row.get("source_maintenance_run_id"),
        "triage_plan_sha256": row.get("triage_plan_sha256"),
        "decision_sheet_generated_at": row.get("decision_sheet_generated_at"),
        "reviewer_note": row.get("reviewer_note"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "source_review_decision_id": review_item_id_for(item),
        "requires_human_followup": True,
    }


def rejected_record(item: dict[str, Any], row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "vendor_id": item.get("vendor_id"),
        "source_id": item.get("source_id"),
        "source_type": item.get("source_type"),
        "source_url": item.get("source_url"),
        "rejection_reason": reason,
        "source_maintenance_run_id": row.get("source_maintenance_run_id"),
        "triage_plan_sha256": row.get("triage_plan_sha256"),
        "decision_sheet_generated_at": row.get("decision_sheet_generated_at"),
        "reviewer_note": row.get("reviewer_note"),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "source_review_decision_id": review_item_id_for(item),
    }


def validate_row(
    *,
    row: dict[str, Any],
    row_number: int,
    item: dict[str, Any],
    binding_context: dict[str, str],
    verifier: Callable[[dict[str, Any], str], dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    review_item_id = str(row.get("review_item_id") or "")
    reasons: list[str] = []

    for field in CSV_FIELDS:
        if field in EDITABLE_COLUMNS:
            continue
        if str(row.get(field) or "") != expected_csv_value(item, field, binding_context):
            reasons.append(f"{field}_changed")

    source_url = str(item.get("source_url") or "")
    row_source_url = str(row.get("source_url") or "")
    if validate_url_safety(source_url) or validate_url_safety(row_source_url):
        reasons.append("source_url_safety_not_passed")

    decision = str(row.get("review_decision") or "").strip()
    if decision not in ALLOWED_DECISIONS:
        reasons.append("invalid_review_decision")

    approved_url = str(row.get("approved_replacement_url") or "").strip()
    if approved_url:
        replacement_safety = validate_url_safety(approved_url)
        if replacement_safety:
            reasons.append("approved_replacement_url_safety_not_passed")

    if reasons:
        return "invalid", None, invalid_row(row_number, review_item_id, reasons, "row failed base validation")

    missing_metadata = has_required_metadata(row)
    if missing_metadata:
        return (
            "invalid",
            None,
            invalid_row(row_number, review_item_id, [f"{field}_missing" for field in missing_metadata], "reviewer metadata is required"),
        )

    if decision == "replace_with_url":
        if not approved_url:
            return "invalid", None, invalid_row(row_number, review_item_id, ["approved_replacement_url_missing"], "replacement URL is required")
        same, tracking_only = same_or_tracking_only_url(source_url, approved_url)
        if same:
            return "invalid", None, invalid_row(row_number, review_item_id, ["replacement_url_same_as_current"], "replacement URL matches current source URL")
        if tracking_only:
            return "invalid", None, invalid_row(row_number, review_item_id, ["replacement_url_tracking_param_only"], "replacement URL only changes tracking parameters")
        try:
            verification = verifier(item, approved_url)
        except Exception as exc:  # noqa: BLE001 - replacement approvals fail closed.
            verification = {
                "ok": False,
                "reason_codes": ["live_verification_error"],
                "message": f"{type(exc).__name__}: {exc}",
            }
        if not verification.get("ok"):
            return (
                "invalid",
                None,
                invalid_row(
                    row_number,
                    review_item_id,
                    list(verification.get("reason_codes") or ["replacement_verification_failed"]),
                    str(verification.get("message") or "replacement verification failed closed"),
                ),
            )
        return "approved_repairs", approved_repair_record(item, row, verification), None

    if approved_url:
        return (
            "invalid",
            None,
            invalid_row(row_number, review_item_id, ["approved_replacement_url_not_allowed"], f"{decision} must not include approved_replacement_url"),
        )

    if decision == "mark_no_replacement_available":
        return "no_replacement_decisions", no_replacement_record(item, row), None
    if decision == "defer_access_ambiguous":
        return "deferred_decisions", deferred_record(item, row, "access_ambiguous"), None
    if decision == "defer_needs_vendor_confirmation":
        return "deferred_decisions", deferred_record(item, row, "needs_vendor_confirmation"), None
    if decision == "reject_candidate_mismatch":
        return "rejected_decisions", rejected_record(item, row, "candidate_mismatch"), None
    if decision == "keep_existing_source":
        return "deferred_decisions", deferred_record(item, row, "keep_existing_source_pending_independent_verification"), None

    raise AssertionError(f"unhandled decision: {decision}")


def replace_row_reaches_verifier(row: dict[str, Any], item: dict[str, Any], binding_context: dict[str, str]) -> bool:
    if str(row.get("review_decision") or "").strip() != "replace_with_url":
        return False
    for field in CSV_FIELDS:
        if field in EDITABLE_COLUMNS:
            continue
        if str(row.get(field) or "") != expected_csv_value(item, field, binding_context):
            return False
    source_url = str(item.get("source_url") or "")
    row_source_url = str(row.get("source_url") or "")
    if validate_url_safety(source_url) or validate_url_safety(row_source_url):
        return False
    if has_required_metadata(row):
        return False
    approved_url = str(row.get("approved_replacement_url") or "").strip()
    if not approved_url or validate_url_safety(approved_url):
        return False
    same, tracking_only = same_or_tracking_only_url(source_url, approved_url)
    return not same and not tracking_only


def read_decision_sheet(path: Path) -> tuple[list[str], list[tuple[int, dict[str, Any]]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, restkey="__extra_values__")
        fieldnames = list(reader.fieldnames or [])
        rows = [(row_number, row) for row_number, row in enumerate(reader, start=2)]
    return fieldnames, rows


def empty_validation_report(
    *,
    triage_source: str,
    decision_sheet_source: str,
    source_maintenance_run_id: str,
    triage_plan_sha256: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": VALIDATION_REPORT_TYPE,
        "triage_source": triage_source,
        "decision_sheet_source": decision_sheet_source,
        "source_maintenance_run_id": source_maintenance_run_id,
        "triage_plan_sha256": triage_plan_sha256,
        "approved_repairs": [],
        "no_replacement_decisions": [],
        "deferred_decisions": [],
        "rejected_decisions": [],
        "invalid_rows": [],
        "summary": {},
        "posture": {
            "reviewer_input_trusted": False,
            "independent_validation_required": True,
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "report_only": True,
            "non_advisory": True,
        },
    }


def summarize_validation(report: dict[str, Any], decisions: Counter[str], total_rows: int) -> None:
    report["summary"] = {
        "total_rows": total_rows,
        "approved_repairs_count": len(report["approved_repairs"]),
        "no_replacement_decisions_count": len(report["no_replacement_decisions"]),
        "deferred_decisions_count": len(report["deferred_decisions"]),
        "rejected_decisions_count": len(report["rejected_decisions"]),
        "invalid_rows_count": len(report["invalid_rows"]),
        "replace_with_url_count": decisions.get("replace_with_url", 0),
        "mark_no_replacement_available_count": decisions.get("mark_no_replacement_available", 0),
        "defer_access_ambiguous_count": decisions.get("defer_access_ambiguous", 0),
        "defer_needs_vendor_confirmation_count": decisions.get("defer_needs_vendor_confirmation", 0),
        "reject_candidate_mismatch_count": decisions.get("reject_candidate_mismatch", 0),
        "keep_existing_source_count": decisions.get("keep_existing_source", 0),
    }


def validate_decision_sheet(
    triage_plan: dict[str, Any],
    *,
    decision_sheet_path: Path,
    triage_source: str,
    generated_at: str | None = None,
    verifier: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = triage_items(triage_plan)
    binding_context = binding_context_for(triage_plan, generated_at="")
    binding_context.pop("decision_sheet_generated_at")
    index = build_triage_index(items)
    report = empty_validation_report(
        triage_source=triage_source,
        decision_sheet_source=str(decision_sheet_path),
        source_maintenance_run_id=binding_context["source_maintenance_run_id"],
        triage_plan_sha256=binding_context["triage_plan_sha256"],
        generated_at=generated_at,
    )
    fieldnames, rows = read_decision_sheet(decision_sheet_path)
    verifier = verifier or (lambda item, url: verify_replacement_url(item, url))

    header_reasons: list[str] = []
    if fieldnames != CSV_FIELDS:
        missing = sorted(set(CSV_FIELDS) - set(fieldnames))
        unexpected = sorted(set(fieldnames) - set(CSV_FIELDS))
        if missing:
            header_reasons.append("missing_columns")
        if unexpected:
            header_reasons.append("unexpected_columns")
        if SELF_CERTIFYING_FIELDS & set(fieldnames):
            header_reasons.append("self_certifying_field_present")
        if len(fieldnames) != len(set(fieldnames)):
            header_reasons.append("duplicate_columns")
        report["invalid_rows"].append(
            invalid_row(1, "", header_reasons, f"decision sheet columns are invalid; missing={missing}; unexpected={unexpected}")
        )

    seen: set[str] = set()
    sheet_generated_at: str | None = None
    decisions: Counter[str] = Counter()
    network_fetch_performed = False

    for row_number, row in rows:
        review_item_id = str(row.get("review_item_id") or "")
        row_generated_at = str(row.get("decision_sheet_generated_at") or "")
        row_binding_context = {
            **binding_context,
            "decision_sheet_generated_at": row_generated_at,
        }
        if row.get("__extra_values__"):
            report["invalid_rows"].append(
                invalid_row(row_number, review_item_id, ["unexpected_extra_values"], "row contains values beyond declared columns")
            )
            continue
        if review_item_id in seen:
            report["invalid_rows"].append(
                invalid_row(row_number, review_item_id, ["duplicate_review_item_id"], "duplicate review_item_id appears in decision sheet")
            )
            continue
        seen.add(review_item_id)
        item = index.get(review_item_id)
        if item is None:
            report["invalid_rows"].append(
                invalid_row(row_number, review_item_id, ["review_item_id_not_found"], "review_item_id does not exist in original triage plan")
            )
            continue
        if blank(row_generated_at):
            report["invalid_rows"].append(
                invalid_row(row_number, review_item_id, ["decision_sheet_generated_at_missing"], "decision sheet generated timestamp is required")
            )
            continue
        if sheet_generated_at is None:
            sheet_generated_at = row_generated_at
        elif row_generated_at != sheet_generated_at:
            report["invalid_rows"].append(
                invalid_row(row_number, review_item_id, ["mixed_decision_sheet_generated_at"], "decision sheet rows must share one generated timestamp")
            )
            continue
        decision = str(row.get("review_decision") or "").strip()
        if decision in ALLOWED_DECISIONS:
            decisions[decision] += 1
        bucket, output, invalid = validate_row(
            row=row,
            row_number=row_number,
            item=item,
            binding_context=row_binding_context,
            verifier=verifier,
        )
        if replace_row_reaches_verifier(row, item, row_binding_context):
            network_fetch_performed = True
        if invalid:
            report["invalid_rows"].append(invalid)
        elif bucket and output:
            report[bucket].append(output)

    for key in ("approved_repairs", "no_replacement_decisions", "deferred_decisions", "rejected_decisions"):
        report[key].sort(key=lambda item: str(item.get("source_review_decision_id") or ""))
    report["invalid_rows"].sort(key=lambda item: (int(item.get("row_number") or 0), str(item.get("review_item_id") or "")))
    report["posture"]["network_fetch_performed"] = network_fetch_performed
    summarize_validation(report, decisions, len(rows))
    return report


def build_validation_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    invalid_count = summary["invalid_rows_count"]
    next_action = (
        "Fix invalid rows and re-run validation before exporting reviewed artifacts."
        if invalid_count
        else "Validation has zero invalid rows; reviewed artifacts may be exported for a separate reviewed-artifacts PR."
    )
    lines = [
        "# OpenVA Source Review Decision Validation",
        "",
        f"Generated: {report['generated_at']}",
        f"Source maintenance run: `{report['source_maintenance_run_id']}`",
        f"Triage plan SHA-256: `{report['triage_plan_sha256']}`",
        "",
        "Reviewer input is untrusted. This report is the independent validation result.",
        "",
        "## Summary",
        "",
        f"- Total rows: `{summary['total_rows']}`",
        f"- Approved repairs: `{summary['approved_repairs_count']}`",
        f"- No-replacement decisions: `{summary['no_replacement_decisions_count']}`",
        f"- Deferred decisions: `{summary['deferred_decisions_count']}`",
        f"- Rejected decisions: `{summary['rejected_decisions_count']}`",
        f"- Invalid rows: `{invalid_count}`",
        "",
        "## Decision Counts",
        "",
        f"- `replace_with_url`: `{summary['replace_with_url_count']}`",
        f"- `mark_no_replacement_available`: `{summary['mark_no_replacement_available_count']}`",
        f"- `defer_access_ambiguous`: `{summary['defer_access_ambiguous_count']}`",
        f"- `defer_needs_vendor_confirmation`: `{summary['defer_needs_vendor_confirmation_count']}`",
        f"- `reject_candidate_mismatch`: `{summary['reject_candidate_mismatch_count']}`",
        f"- `keep_existing_source`: `{summary['keep_existing_source_count']}`",
        "",
        "## Next Action",
        "",
        f"- {next_action}",
        "",
    ]
    if report["invalid_rows"]:
        lines.extend(["## Invalid Rows", ""])
        for row in report["invalid_rows"][:50]:
            lines.append(
                f"- Row `{row['row_number']}` `{row.get('review_item_id', '')}`: "
                f"{';'.join(row.get('reason_codes', []))} - {row.get('message', '')}"
            )
        lines.append("")
    lines.extend(
        [
            "## Guardrails",
            "",
            "- This report does not mutate catalog source YAML.",
            "- The decision sheet must be bound to the supplied triage plan SHA-256.",
            "- Approved replacements are only emitted after independent verification.",
            "- No-replacement and defer decisions are not source repairs.",
            "- Repair PR generation remains a separate later workflow.",
            "",
        ]
    )
    return "\n".join(lines)


def write_validation_markdown(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_validation_markdown(report), encoding="utf-8")


def export_reviewed_artifacts(validation: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    exports = [
        ("approved_repairs", "reviewed-repair-plan.json", "reviewed_source_repair_plan"),
        ("no_replacement_decisions", "reviewed-no-replacement-decisions.json", "reviewed_no_replacement_decisions"),
        ("deferred_decisions", "reviewed-deferred-decisions.json", "reviewed_deferred_decisions"),
    ]
    for field, filename, report_type in exports:
        rows = validation.get(field) or []
        if not rows:
            continue
        path = output_dir / filename
        write_json(
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": now_iso(),
                "report_type": report_type,
                "source_maintenance_run_id": validation.get("source_maintenance_run_id"),
                "triage_plan_sha256": validation.get("triage_plan_sha256"),
                field: rows,
                "summary": {"count": len(rows)},
                "posture": validation.get("posture", {}),
            },
            path,
        )
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-review-decisions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_sheet = subparsers.add_parser("build-sheet")
    build_sheet.add_argument("--triage-plan", type=Path, required=True)
    build_sheet.add_argument("--output-csv", type=Path, default=Path("source-review-decision-sheet.csv"))
    build_sheet.add_argument("--output-md", type=Path, default=Path("source-review-decision-sheet-summary.md"))

    validate_sheet = subparsers.add_parser("validate-sheet")
    validate_sheet.add_argument("--triage-plan", type=Path, required=True)
    validate_sheet.add_argument("--decision-sheet", type=Path, required=True)
    validate_sheet.add_argument("--output-json", type=Path, default=Path("source-review-decision-validation.json"))
    validate_sheet.add_argument("--output-md", type=Path, default=Path("source-review-decision-validation-summary.md"))

    export = subparsers.add_parser("export-reviewed-artifacts")
    export.add_argument("--validation", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, default=Path("maintenance/reviewed/generated"))

    args = parser.parse_args(argv)

    if args.command == "build-sheet":
        report = build_decision_sheet(load_json(args.triage_plan))
        write_sheet_csv(report, args.output_csv)
        write_sheet_markdown(report, args.output_md)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0

    if args.command == "validate-sheet":
        report = validate_decision_sheet(
            load_json(args.triage_plan),
            decision_sheet_path=args.decision_sheet,
            triage_source=str(args.triage_plan),
        )
        write_json(report, args.output_json)
        write_validation_markdown(report, args.output_md)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 1 if report["summary"]["invalid_rows_count"] else 0

    if args.command == "export-reviewed-artifacts":
        written = export_reviewed_artifacts(load_json(args.validation), args.output_dir)
        print(json.dumps({"written": [str(path) for path in written]}, indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
