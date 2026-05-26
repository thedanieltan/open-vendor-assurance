from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva.source_repair_collision_check import normalize_url

REPORT_TYPE = "source_repair_sweep"
SCHEMA_VERSION = "0.1.0"

STRICT_BUCKET = "strict_repair_ready"
HUMAN_BUCKET = "human_review_required"
NO_REPLACEMENT_BUCKET = "no_replacement_found"

HARD_P0_STATUSES = {"not_found", "gone"}
OK_STATUSES = {"ok", "redirected"}
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
    "soft_not_found",
    "suspect_inferred_url",
}
KNOWN_PROBLEM_STATUSES = HARD_P0_STATUSES | ACCESS_AMBIGUOUS_STATUSES | QUALITY_STATUSES | {
    "client_error",
    "server_error",
}
ALLOWED_REPLACEMENT_STATUSES = {"ok", "redirected"}
ALLOWED_AUTHORITY_STATUSES = {"vendor_controlled", "approved_exception", "approved_vendor_source"}
ALLOWED_ACCESS_STATUSES = {"public", "public_web", "public_pdf"}
SELF_CERTIFYING_FIELDS = {"eligible", "eligible_for_automerge", "tool_recommendation"}

CSV_FIELDS = [
    "vendor_id",
    "source_id",
    "source_type",
    "original_source_url",
    "original_status",
    "original_http_status",
    "original_final_url",
    "replacement_source_url",
    "replacement_final_url",
    "replacement_http_status",
    "replacement_semantic_status",
    "replacement_authority_status",
    "replacement_access_status",
    "soft_404_detected",
    "redirect_canonical_drift",
    "bucket",
    "reason_codes",
    "recommended_next_action",
    "requires_human_review",
]

RECOMMENDED_NEXT_ACTION = {
    STRICT_BUCKET: "Eligible for small reviewed P0 repair batch.",
    HUMAN_BUCKET: "Review source manually before repair.",
    NO_REPLACEMENT_BUCKET: "Keep source unavailable / not available until vendor publishes a source.",
}

REASON_ORDER = (
    "unknown_verification_status",
    "confirmed_p0",
    "original_hard_p0_status",
    "original_status_not_hard_p0",
    "replacement_missing",
    "replacement_status_not_ok_or_redirected",
    "replacement_final_url_missing",
    "redirect_canonical_drift",
    "soft_404_detected",
    "semantic_status_not_strong",
    "authority_not_vendor_controlled_or_exception",
    "access_not_public",
    "access_ambiguous",
    "source_type_changed",
    "source_type_ambiguous",
    "suspect_inferred_url",
    "possible_mismatch",
    "homepage_or_generic_redirect",
    "soft_not_found",
    "weak_semantic_match",
    "vendor_authority_ambiguous",
    "self_certifying_field_present",
    "replacement_candidate_not_strict",
    "no_verified_public_vendor_replacement",
)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def maybe_load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return load_json(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_source_verification_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != "source_verification_report":
        raise ValueError("expected source-verification report_type=source_verification_report")
    sources = report.get("sources")
    if not isinstance(sources, list):
        raise ValueError("expected source-verification sources list")
    rows: list[dict[str, Any]] = []
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("expected each source-verification row to be an object")
        for field in ("vendor_id", "source_id", "source_url"):
            if not row.get(field):
                raise ValueError(f"source-verification row missing {field}")
        rows.append(row)
    return rows


def source_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_url") or row.get("original_source_url") or ""),
    )


def vendor_type_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_type") or row.get("source_type_candidate") or ""),
    )


def sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("bucket") or ""),
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("original_source_url") or ""),
    )


def ordered_reasons(reasons: set[str]) -> list[str]:
    ordered = [reason for reason in REASON_ORDER if reason in reasons]
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


def semantic_status_from(row: dict[str, Any]) -> str:
    value = row.get("replacement_semantic_status") or row.get("semantic_status")
    if value:
        return str(value)
    semantic = row.get("semantic_match")
    if isinstance(semantic, dict) and semantic.get("status"):
        return str(semantic["status"])
    evidence = row.get("evidence")
    if isinstance(evidence, dict):
        if evidence.get("semantic_status"):
            return str(evidence["semantic_status"])
        matched_terms = evidence.get("matched_terms")
        if isinstance(matched_terms, list) and len(matched_terms) >= 2:
            return "strong"
        if isinstance(matched_terms, list) and len(matched_terms) == 1:
            return "weak"
    return ""


def final_url_from(row: dict[str, Any]) -> str:
    for field in ("replacement_final_url", "final_url", "replacement_resolved_final_url"):
        value = row.get(field)
        if value:
            return str(value)
    evidence = row.get("evidence")
    if isinstance(evidence, dict) and evidence.get("final_url"):
        return str(evidence["final_url"])
    return ""


def replacement_url_from(row: dict[str, Any]) -> str:
    for field in ("replacement_source_url", "candidate_url", "source_url", "url"):
        value = row.get(field)
        if value:
            return str(value)
    return ""


def replacement_status_from(row: dict[str, Any]) -> str:
    for field in ("replacement_verification_status", "verification_status", "status"):
        value = row.get(field)
        if value:
            return str(value)
    evidence = row.get("evidence")
    if isinstance(evidence, dict):
        http_status = evidence.get("http_status")
        if isinstance(http_status, int) and 200 <= http_status < 300:
            return "ok"
    return ""


def http_status_from(row: dict[str, Any]) -> Any:
    for field in ("replacement_http_status", "http_status"):
        if field in row:
            return row.get(field)
    evidence = row.get("evidence")
    if isinstance(evidence, dict):
        return evidence.get("http_status")
    return None


def authority_status_from(row: dict[str, Any]) -> str:
    return str(
        row.get("replacement_authority_status")
        or row.get("authority_status")
        or row.get("source_authority_status")
        or ""
    )


def access_status_from(row: dict[str, Any]) -> str:
    return str(row.get("replacement_access_status") or row.get("access_status") or "")


def source_type_from_candidate(candidate: dict[str, Any]) -> str:
    return str(candidate.get("source_type") or candidate.get("source_type_candidate") or "")


def is_soft_404(row: dict[str, Any], candidate: dict[str, Any] | None = None) -> bool:
    rows = [row]
    if candidate is not None:
        rows.append(candidate)
    for item in rows:
        if item.get("soft_404_detected") is True or item.get("replacement_soft_404_detected") is True:
            return True
        status = item.get("verification_status") or item.get("replacement_verification_status")
        if status in {"soft_not_found", "soft_404_detected"}:
            return True
        reasons = item.get("reasons") or item.get("reason_codes")
        if isinstance(reasons, list) and "soft_404_detected" in {str(reason) for reason in reasons}:
            return True
    return False


def canonical_chosen(candidate: dict[str, Any]) -> bool:
    if candidate.get("canonical_replacement_chosen") is True:
        return True
    canonical_url = candidate.get("canonical_replacement_url")
    return bool(canonical_url and normalize_url(str(canonical_url)) == normalize_url(replacement_url_from(candidate)))


def has_redirect_canonical_drift(source: dict[str, Any], candidate: dict[str, Any] | None) -> bool:
    if candidate is not None and replacement_status_from(candidate) == "redirected":
        replacement_url = replacement_url_from(candidate)
        final_url = final_url_from(candidate)
        return bool(final_url and normalize_url(replacement_url) != normalize_url(final_url) and not canonical_chosen(candidate))
    status = str(source.get("verification_status") or "")
    source_url = str(source.get("source_url") or "")
    final_url = str(source.get("final_url") or "")
    return status == "redirected" and bool(final_url and normalize_url(source_url) != normalize_url(final_url))


def candidate_is_inferred(candidate: dict[str, Any] | None) -> bool:
    if candidate is None:
        return False
    if candidate.get("suspect_inferred_url") is True:
        return True
    if candidate.get("requires_review") is True and candidate.get("discovery_method"):
        return True
    return str(candidate.get("discovery_method") or "") == "official_domain_crawl"


def replacement_from_source_row(source: dict[str, Any]) -> dict[str, Any] | None:
    if not any(source.get(field) for field in ("replacement_source_url", "candidate_url", "url")):
        return None
    return {
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("replacement_source_type") or source.get("source_type"),
        "replacement_source_url": replacement_url_from(source),
        "replacement_final_url": final_url_from(source) or replacement_url_from(source),
        "replacement_http_status": http_status_from(source),
        "replacement_verification_status": replacement_status_from(source),
        "replacement_semantic_status": semantic_status_from(source),
        "replacement_authority_status": authority_status_from(source),
        "replacement_access_status": access_status_from(source),
        "replacement_soft_404_detected": source.get("replacement_soft_404_detected", source.get("soft_404_detected")),
        "canonical_replacement_chosen": source.get("canonical_replacement_chosen"),
    }


def replacement_from_discovery_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    return {
        **candidate,
        "source_type": candidate.get("source_type_candidate"),
        "replacement_source_url": candidate.get("candidate_url"),
        "replacement_final_url": evidence.get("final_url"),
        "replacement_http_status": evidence.get("http_status"),
        "replacement_verification_status": "ok"
        if isinstance(evidence.get("http_status"), int) and 200 <= evidence.get("http_status") < 300
        else "",
        "replacement_semantic_status": semantic_status_from(candidate),
        "replacement_authority_status": candidate.get("replacement_authority_status") or "vendor_controlled",
        "replacement_access_status": candidate.get("replacement_access_status") or "public",
        "suspect_inferred_url": True,
    }


def iter_candidate_rows(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not report:
        return []
    rows: list[dict[str, Any]] = []
    for field in ("strict_repair_ready", "repairs", "approved", "rejected", "unmatched", "confirmed_p0"):
        value = report.get(field)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    for vendor in report.get("vendors", []) or []:
        if not isinstance(vendor, dict):
            continue
        for candidate in vendor.get("candidates", []) or []:
            if isinstance(candidate, dict):
                rows.append(replacement_from_discovery_candidate(candidate))
    return rows


def build_candidate_indexes(
    sources: list[dict[str, Any]],
    reports: list[dict[str, Any] | None],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]], set[tuple[str, str, str]]]:
    by_source: dict[tuple[str, str, str], dict[str, Any]] = {}
    by_type: dict[tuple[str, str], dict[str, Any]] = {}
    confirmed_p0: set[tuple[str, str, str]] = set()

    for source in sources:
        replacement = replacement_from_source_row(source)
        if replacement is not None:
            by_source[source_key(source)] = replacement

    for report in reports:
        if not report:
            continue
        for row in report.get("confirmed_p0", []) or []:
            if isinstance(row, dict):
                confirmed_p0.add(source_key(row))
        for row in iter_candidate_rows(report):
            if not replacement_url_from(row):
                continue
            key = source_key(row)
            if all(key):
                by_source.setdefault(key, row)
            type_key = vendor_type_key(row)
            if all(type_key):
                by_type.setdefault(type_key, row)

    return by_source, by_type, confirmed_p0


def select_candidate(
    source: dict[str, Any],
    by_source: dict[tuple[str, str, str], dict[str, Any]],
    by_type: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    return by_source.get(source_key(source)) or by_type.get(vendor_type_key(source))


def strict_fail_reasons(
    source: dict[str, Any],
    candidate: dict[str, Any] | None,
    confirmed_p0: set[tuple[str, str, str]],
) -> set[str]:
    reasons: set[str] = set()
    original_status = str(source.get("verification_status") or "")
    if original_status in HARD_P0_STATUSES:
        reasons.add("confirmed_p0" if source_key(source) in confirmed_p0 else "original_hard_p0_status")
    else:
        reasons.add("original_status_not_hard_p0")

    if candidate is None or not replacement_url_from(candidate):
        reasons.add("replacement_missing")
        return reasons

    replacement_status = replacement_status_from(candidate)
    if replacement_status not in ALLOWED_REPLACEMENT_STATUSES:
        reasons.add("replacement_status_not_ok_or_redirected")
    if not final_url_from(candidate):
        reasons.add("replacement_final_url_missing")
    if has_redirect_canonical_drift(source, candidate):
        reasons.add("redirect_canonical_drift")
    if is_soft_404(source, candidate):
        reasons.add("soft_404_detected")

    semantic_status = semantic_status_from(candidate)
    if semantic_status != "strong":
        reasons.add("weak_semantic_match" if semantic_status == "weak" else "semantic_status_not_strong")

    authority_status = authority_status_from(candidate)
    if authority_status not in ALLOWED_AUTHORITY_STATUSES:
        reasons.add("authority_not_vendor_controlled_or_exception")
    if not authority_status:
        reasons.add("vendor_authority_ambiguous")

    access_status = access_status_from(candidate)
    if access_status not in ALLOWED_ACCESS_STATUSES:
        reasons.add("access_not_public")
    if replacement_status in ACCESS_AMBIGUOUS_STATUSES or access_status in ACCESS_AMBIGUOUS_STATUSES:
        reasons.add("access_ambiguous")

    candidate_source_type = source_type_from_candidate(candidate)
    if candidate_source_type and candidate_source_type != str(source.get("source_type") or ""):
        reasons.add("source_type_changed")
    if not candidate_source_type:
        reasons.add("source_type_ambiguous")

    if candidate_is_inferred(candidate):
        reasons.add("suspect_inferred_url")
    if find_self_certifying_fields(source) or find_self_certifying_fields(candidate):
        reasons.add("self_certifying_field_present")
    return reasons


def bucket_for(source: dict[str, Any], candidate: dict[str, Any] | None, reasons: set[str]) -> str:
    status = str(source.get("verification_status") or "")
    if status not in KNOWN_PROBLEM_STATUSES and status not in OK_STATUSES:
        return HUMAN_BUCKET
    if status in ACCESS_AMBIGUOUS_STATUSES or status in QUALITY_STATUSES:
        return HUMAN_BUCKET
    if candidate is not None and "replacement_missing" not in reasons:
        return STRICT_BUCKET if not (reasons - {"confirmed_p0", "original_hard_p0_status"}) else HUMAN_BUCKET
    if status in HARD_P0_STATUSES:
        return NO_REPLACEMENT_BUCKET
    return HUMAN_BUCKET


def row_for_source(
    source: dict[str, Any],
    candidate: dict[str, Any] | None,
    confirmed_p0: set[tuple[str, str, str]],
) -> dict[str, Any]:
    status = str(source.get("verification_status") or "")
    reasons = strict_fail_reasons(source, candidate, confirmed_p0)
    if status in ACCESS_AMBIGUOUS_STATUSES:
        reasons.add("access_ambiguous")
    if status in QUALITY_STATUSES:
        reasons.add(status)
    if status not in KNOWN_PROBLEM_STATUSES and status not in OK_STATUSES:
        reasons.add("unknown_verification_status")
    if candidate is not None and reasons - {"confirmed_p0", "original_hard_p0_status"}:
        reasons.add("replacement_candidate_not_strict")
    if candidate is None and status in HARD_P0_STATUSES:
        reasons.add("no_verified_public_vendor_replacement")

    bucket = bucket_for(source, candidate, reasons)
    requires_human_review = bucket != STRICT_BUCKET
    replacement_status = replacement_status_from(candidate or {})
    access_ambiguous = status in ACCESS_AMBIGUOUS_STATUSES or replacement_status in ACCESS_AMBIGUOUS_STATUSES
    row: dict[str, Any] = {
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "original_source_url": source.get("source_url"),
        "original_status": status,
        "original_http_status": source.get("http_status"),
        "original_final_url": source.get("final_url"),
        "replacement_source_url": replacement_url_from(candidate or {}) or None,
        "replacement_final_url": final_url_from(candidate or {}) or None,
        "replacement_http_status": http_status_from(candidate or {}),
        "replacement_semantic_status": semantic_status_from(candidate or {}) or None,
        "replacement_authority_status": authority_status_from(candidate or {}) or None,
        "replacement_access_status": access_status_from(candidate or {}) or None,
        "soft_404_detected": is_soft_404(source, candidate),
        "redirect_canonical_drift": has_redirect_canonical_drift(source, candidate),
        "bucket": bucket,
        "reason_codes": ordered_reasons(reasons),
        "recommended_next_action": RECOMMENDED_NEXT_ACTION[bucket],
        "requires_human_review": requires_human_review,
        "source_exists_inference": "likely_endpoint_exists" if access_ambiguous else None,
        "content_verified": bucket == STRICT_BUCKET,
        "semantic_verified": bucket == STRICT_BUCKET,
    }
    return row


def source_has_problem(source: dict[str, Any]) -> bool:
    status = str(source.get("verification_status") or "")
    return (
        status not in OK_STATUSES
        or status not in KNOWN_PROBLEM_STATUSES | OK_STATUSES
        or has_redirect_canonical_drift(source, None)
        or replacement_from_source_row(source) is not None
    )


def bounded_counter(rows: list[dict[str, Any]], field: str, *, limit: int | None = None) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "unknown") for row in rows)
    items = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    if limit is not None:
        items = items[:limit]
    return dict(items)


def build_summary(sources: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts = Counter(reason for row in rows for reason in row.get("reason_codes", []))
    bucket_counts = Counter(row["bucket"] for row in rows)
    verification_statuses = Counter(str(source.get("verification_status") or "") for source in sources)
    return {
        "total_sources_seen": len(sources),
        "strict_repair_ready_count": bucket_counts.get(STRICT_BUCKET, 0),
        "human_review_required_count": bucket_counts.get(HUMAN_BUCKET, 0),
        "no_replacement_found_count": bucket_counts.get(NO_REPLACEMENT_BUCKET, 0),
        "counts_by_reason_code": dict(sorted(reason_counts.items())),
        "counts_by_source_type": bounded_counter(rows, "source_type"),
        "counts_by_vendor_id": bounded_counter(rows, "vendor_id", limit=25),
        "p0_remaining_count": verification_statuses.get("not_found", 0) + verification_statuses.get("gone", 0),
        "soft_not_found_count": verification_statuses.get("soft_not_found", 0),
        "redirect_canonical_drift_count": sum(1 for row in rows if row["redirect_canonical_drift"]),
        "access_ambiguous_count": sum(
            1 for source in sources if str(source.get("verification_status") or "") in ACCESS_AMBIGUOUS_STATUSES
        ),
        "quality_issue_count": sum(
            1 for source in sources if str(source.get("verification_status") or "") in QUALITY_STATUSES
        ),
    }


def posture() -> dict[str, bool]:
    return {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "non_advisory": True,
        "report_only": True,
    }


def build_source_repair_sweep(
    source_verification_report: dict[str, Any],
    *,
    source_discovery_report: dict[str, Any] | None = None,
    source_quality_refinement_queue: dict[str, Any] | None = None,
    confirmed_p0_repair_candidates: dict[str, Any] | None = None,
    latest_source_health: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    sources = validate_source_verification_report(source_verification_report)
    by_source, by_type, confirmed_p0 = build_candidate_indexes(
        sources,
        [
            source_discovery_report,
            source_quality_refinement_queue,
            confirmed_p0_repair_candidates,
            latest_source_health,
        ],
    )
    rows = [
        row_for_source(source, select_candidate(source, by_source, by_type), confirmed_p0)
        for source in sources
        if source_has_problem(source)
    ]
    rows.sort(key=sort_key)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or utc_now(),
        "report_type": REPORT_TYPE,
        "posture": posture(),
        "inputs": {
            "source_verification_report_type": source_verification_report.get("report_type"),
            "source_verification_generated_at": source_verification_report.get("generated_at"),
            "source_discovery_report_type": (source_discovery_report or {}).get("report_type"),
            "source_quality_refinement_queue_type": (source_quality_refinement_queue or {}).get("report_type"),
            "confirmed_p0_repair_candidates_type": (confirmed_p0_repair_candidates or {}).get("report_type"),
            "latest_source_health_type": (latest_source_health or {}).get("report_type"),
        },
        "summary": build_summary(sources, rows),
        "records": rows,
        STRICT_BUCKET: [row for row in rows if row["bucket"] == STRICT_BUCKET],
        HUMAN_BUCKET: [row for row in rows if row["bucket"] == HUMAN_BUCKET],
        NO_REPLACEMENT_BUCKET: [row for row in rows if row["bucket"] == NO_REPLACEMENT_BUCKET],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            output = dict(row)
            output["reason_codes"] = ";".join(row.get("reason_codes", []))
            writer.writerow(output)


def markdown_counter(counter: dict[str, int]) -> list[str]:
    if not counter:
        return ["- None"]
    return [f"- `{key}`: `{value}`" for key, value in counter.items()]


def build_markdown_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# OpenVA Source Repair Sweep Summary",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This report partitions remaining source problems into strict repair-ready rows, human-review rows, and no-replacement rows.",
        "",
        "It is operational metadata only. It does not mutate catalog sources, generate repair PRs, enable automerge, or perform live network fetches.",
        "",
        "## Summary",
        "",
        f"- Total sources seen: `{summary['total_sources_seen']}`",
        f"- Strict repair ready: `{summary['strict_repair_ready_count']}`",
        f"- Human review required: `{summary['human_review_required_count']}`",
        f"- No replacement found: `{summary['no_replacement_found_count']}`",
        f"- P0 remaining: `{summary['p0_remaining_count']}`",
        f"- Soft not found: `{summary['soft_not_found_count']}`",
        f"- Redirect canonical drift: `{summary['redirect_canonical_drift_count']}`",
        f"- Access ambiguous: `{summary['access_ambiguous_count']}`",
        f"- Quality issues: `{summary['quality_issue_count']}`",
        "",
        "## Reason Codes",
        "",
        *markdown_counter(summary["counts_by_reason_code"]),
        "",
        "## Source Types",
        "",
        *markdown_counter(summary["counts_by_source_type"]),
        "",
        "## Top Vendors",
        "",
        *markdown_counter(summary["counts_by_vendor_id"]),
        "",
        "## Guardrails",
        "",
        "- Report-only partitioning step.",
        "- No source URL replacement.",
        "- No catalog source mutation.",
        "- No repair PR generation.",
        "- No automerge changes.",
        "- No invented vendor URLs.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    report: dict[str, Any],
    *,
    json_output: Path,
    strict_csv_output: Path,
    human_review_csv_output: Path,
    no_replacement_csv_output: Path,
    markdown_output: Path,
) -> None:
    write_json(json_output, report)
    write_csv(strict_csv_output, report[STRICT_BUCKET])
    write_csv(human_review_csv_output, report[HUMAN_BUCKET])
    write_csv(no_replacement_csv_output, report[NO_REPLACEMENT_BUCKET])
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(build_markdown_summary(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-sweep")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--source-verification-report", type=Path, required=True)
    parser.add_argument("--source-discovery-report", type=Path)
    parser.add_argument("--source-quality-refinement-queue", type=Path)
    parser.add_argument("--confirmed-p0-repair-candidates", type=Path)
    parser.add_argument("--latest-source-health", type=Path)
    parser.add_argument("--json-output", type=Path, default=Path("source-repair-sweep-report.json"))
    parser.add_argument(
        "--strict-csv-output",
        type=Path,
        default=Path("source-repair-sweep-strict-candidates.csv"),
    )
    parser.add_argument(
        "--human-review-csv-output",
        type=Path,
        default=Path("source-repair-sweep-human-review.csv"),
    )
    parser.add_argument(
        "--no-replacement-csv-output",
        type=Path,
        default=Path("source-repair-sweep-no-replacement.csv"),
    )
    parser.add_argument("--markdown-output", type=Path, default=Path("source-repair-sweep-summary.md"))
    args = parser.parse_args(argv)

    report = build_source_repair_sweep(
        load_json(args.source_verification_report),
        source_discovery_report=maybe_load_json(args.source_discovery_report),
        source_quality_refinement_queue=maybe_load_json(args.source_quality_refinement_queue),
        confirmed_p0_repair_candidates=maybe_load_json(args.confirmed_p0_repair_candidates),
        latest_source_health=maybe_load_json(args.latest_source_health),
    )
    write_outputs(
        report,
        json_output=args.json_output,
        strict_csv_output=args.strict_csv_output,
        human_review_csv_output=args.human_review_csv_output,
        no_replacement_csv_output=args.no_replacement_csv_output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
