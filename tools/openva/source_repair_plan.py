from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT = Path("source-repair-plan-validation.json")

EVIDENCE_REPORT_TYPE = "p0_source_repair_evidence"
PLAN_REPORT_TYPE = "p0_source_repair_plan"
VALIDATION_REPORT_TYPE = "p0_source_repair_plan_validation"

ALLOWED_ORIGINAL_STATUSES = {"not_found", "gone"}
ALLOWED_REPLACEMENT_STATUSES = {"ok", "redirected"}
ALLOWED_AUTHORITY_STATUSES = {"vendor_controlled", "approved_exception"}
ALLOWED_ACCESS_STATUSES = {"public", "public_web", "public_pdf"}
ALLOWED_SEMANTIC_STATUSES = {"strong"}
OPTIONAL_REPLACEMENT_FIELDS = (
    "replacement_final_url",
    "replacement_soft_404_detected",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def evidence_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_url") or ""),
    )


def plan_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("original_source_url") or ""),
    )


def validate_evidence(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    if evidence.get("report_type") != EVIDENCE_REPORT_TYPE:
        raise ValueError(f"expected evidence report_type={EVIDENCE_REPORT_TYPE}")
    repairs = evidence.get("repairs")
    if not isinstance(repairs, list):
        raise ValueError("expected evidence repairs list")
    seen: set[tuple[str, str, str]] = set()
    for row in repairs:
        if not isinstance(row, dict):
            raise ValueError("expected each evidence repair row to be an object")
        key = evidence_key(row)
        if not all(key):
            raise ValueError(f"evidence row missing vendor_id, source_id, or source_url: {key}")
        if key in seen:
            raise ValueError(f"duplicate evidence row for key: {' | '.join(key)}")
        seen.add(key)
        if not row.get("source_type"):
            raise ValueError(f"evidence row missing source_type: {' | '.join(key)}")
        original = row.get("original")
        if not isinstance(original, dict):
            raise ValueError(f"evidence row missing original evidence: {' | '.join(key)}")
        prior = original.get("prior")
        fresh = original.get("fresh")
        if not isinstance(prior, dict) or not isinstance(fresh, dict):
            raise ValueError(f"evidence row missing prior/fresh original evidence: {' | '.join(key)}")
        status_pair = (prior.get("verification_status"), fresh.get("verification_status"))
        if status_pair not in {("not_found", "not_found"), ("gone", "gone")}:
            raise ValueError(f"evidence row has non-confirmed status pair: {status_pair}")
    return repairs


def validate_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("report_type") != PLAN_REPORT_TYPE:
        raise ValueError(f"expected plan report_type={PLAN_REPORT_TYPE}")
    repairs = plan.get("repairs")
    if not isinstance(repairs, list):
        raise ValueError("expected plan repairs list")
    seen: set[tuple[str, str, str]] = set()
    for row in repairs:
        if not isinstance(row, dict):
            raise ValueError("expected each plan repair row to be an object")
        key = plan_key(row)
        if not all(key):
            raise ValueError(f"plan row missing vendor_id, source_id, or original_source_url: {key}")
        if key in seen:
            raise ValueError(f"duplicate plan row for key: {' | '.join(key)}")
        seen.add(key)
        required = (
            "source_type",
            "replacement_source_url",
            "replacement_verification_status",
            "replacement_http_status",
            "replacement_semantic_status",
            "replacement_authority_status",
            "replacement_access_status",
            "replacement_url_safety_status",
        )
        missing = [field for field in required if field not in row]
        if missing:
            raise ValueError(f"plan row missing required field(s): {', '.join(missing)}")
    return repairs


def normalize_url(url: str) -> str:
    return url.strip().rstrip("#").rstrip("?").rstrip("/")


def replacement_soft_404_detected(row: dict[str, Any]) -> bool:
    return (
        row.get("replacement_soft_404_detected") is True
        or row.get("soft_404_detected") is True
        or row.get("replacement_verification_status") in {"soft_not_found", "soft_404_detected"}
    )


def validate_repair_row(plan_row: dict[str, Any], evidence_row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    original = evidence_row["original"]
    prior_status = original["prior"].get("verification_status")
    fresh_status = original["fresh"].get("verification_status")
    if prior_status not in ALLOWED_ORIGINAL_STATUSES or fresh_status not in ALLOWED_ORIGINAL_STATUSES:
        reasons.append("original_status_not_confirmed_p0")
    if prior_status != fresh_status:
        reasons.append("original_status_pair_not_exact")
    if plan_row.get("source_type") != evidence_row.get("source_type"):
        reasons.append("source_type_changed")
    replacement_url = str(plan_row.get("replacement_source_url") or "")
    original_url = str(evidence_row.get("source_url") or "")
    if not replacement_url:
        reasons.append("replacement_url_missing")
    if normalize_url(replacement_url) == normalize_url(original_url):
        reasons.append("replacement_url_same_as_original")
    if plan_row.get("replacement_verification_status") not in ALLOWED_REPLACEMENT_STATUSES:
        reasons.append("replacement_verification_status_not_ok")
    if replacement_soft_404_detected(plan_row):
        reasons.append("soft_404_detected")
    http_status = plan_row.get("replacement_http_status")
    if not isinstance(http_status, int) or http_status < 200 or http_status >= 400:
        reasons.append("replacement_http_status_not_2xx_or_3xx")
    if plan_row.get("replacement_semantic_status") not in ALLOWED_SEMANTIC_STATUSES:
        reasons.append("replacement_semantic_status_not_strong")
    if plan_row.get("replacement_authority_status") not in ALLOWED_AUTHORITY_STATUSES:
        reasons.append("replacement_authority_status_not_allowed")
    if plan_row.get("replacement_access_status") not in ALLOWED_ACCESS_STATUSES:
        reasons.append("replacement_access_status_not_public")
    if plan_row.get("replacement_url_safety_status") != "passed":
        reasons.append("replacement_url_safety_not_passed")
    return not reasons, reasons


def validate_source_repair_plan(evidence: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    evidence_rows = validate_evidence(evidence)
    plan_rows = validate_plan(plan)
    evidence_by_key = {evidence_key(row): row for row in evidence_rows}
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for row in plan_rows:
        key = plan_key(row)
        evidence_row = evidence_by_key.get(key)
        if evidence_row is None:
            unmatched.append({**row, "reasons": ["no_matching_evidence_row"]})
            continue
        ok, reasons = validate_repair_row(row, evidence_row)
        output = {
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
            "replacement_url_safety_status": row.get("replacement_url_safety_status"),
            "reasons": reasons,
        }
        for field in OPTIONAL_REPLACEMENT_FIELDS:
            if field in row:
                output[field] = row.get(field)
        if ok:
            approved.append(output)
        else:
            rejected.append(output)

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": VALIDATION_REPORT_TYPE,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "inputs": {
            "evidence_report_type": evidence.get("report_type"),
            "evidence_generated_at": evidence.get("generated_at"),
            "plan_report_type": plan.get("report_type"),
            "plan_generated_at": plan.get("generated_at"),
        },
        "approved": approved,
        "rejected": rejected,
        "unmatched": unmatched,
        "summary": {
            "evidence_repair_count": len(evidence_rows),
            "plan_repair_count": len(plan_rows),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "unmatched_count": len(unmatched),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-plan")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, required=True)
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    args = parser.parse_args()
    if args.command == "validate":
        report = validate_source_repair_plan(load_json(args.evidence), load_json(args.plan))
        write_report(report, args.output)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
