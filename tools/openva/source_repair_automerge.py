from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable

import yaml

P0_SOURCE_REPAIR_LABEL = "automerge:p0-source-repair"
SOURCE_REFINEMENT_LABEL = "source-refinement"
DEFAULT_MAX_SOURCE_REPAIRS = 10

VALIDATION_REPORT_TYPE = "p0_source_repair_plan_validation"
EVIDENCE_REPORT_TYPE = "p0_source_repair_evidence"
FORBIDDEN_SELF_CERTIFYING_FIELDS = {
    "eligible",
    "eligible_for_automerge",
    "tool_recommendation",
}
ALLOWED_REPLACEMENT_STATUSES = {"ok", "redirected"}
ALLOWED_AUTHORITY_STATUSES = {"vendor_controlled", "approved_exception"}
ALLOWED_ACCESS_STATUSES = {"public", "public_web", "public_pdf"}
ALLOWED_SOURCE_TOP_LEVEL_CHANGES = {
    "source_url",
    "catalog_tier",
    "review_state",
    "provenance",
}


@dataclass(frozen=True)
class SourceRepairAutomergeResult:
    eligible: bool
    reasons: tuple[str, ...]
    source_repairs: int = 0


def _load_json_text(text: str, label: str) -> dict[str, Any]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{label}: expected JSON object")
    return data


def _load_yaml_text(text: str, label: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{label}: expected YAML mapping")
    return data


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def validate_reviewed_report_path(path: str, kind: str) -> str:
    clean = path.strip()
    parsed = PurePosixPath(clean)
    if (
        not clean
        or parsed.is_absolute()
        or ".." in parsed.parts
        or len(parsed.parts) < 3
        or parsed.parts[0] != "maintenance"
        or parsed.parts[1] != "reviewed"
        or parsed.suffix != ".json"
    ):
        raise ValueError(f"{kind} must be a committed JSON file under maintenance/reviewed/")
    return clean


def find_forbidden_fields(value: Any, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            if key in FORBIDDEN_SELF_CERTIFYING_FIELDS:
                found.append(child_path)
            found.extend(find_forbidden_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_forbidden_fields(child, f"{prefix}[{index}]"))
    return found


def is_source_path(path: str) -> bool:
    parts = path.split("/")
    return (
        len(parts) == 5
        and parts[0] == "data"
        and parts[1] == "vendors"
        and bool(parts[2])
        and parts[3] == "sources"
        and parts[4].endswith(".yaml")
    )


def is_generated_catalog_path(path: str) -> bool:
    return path == "openva-pack.json" or path.startswith("indexes/") or path.startswith("dist/")


def source_path(vendor_id: str, source_id: str) -> str:
    return f"data/vendors/{vendor_id}/sources/{source_id}.yaml"


def evidence_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("source_url") or ""),
    )


def approved_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("vendor_id") or ""),
        str(row.get("source_id") or ""),
        str(row.get("original_source_url") or ""),
    )


def normalize_url(url: str) -> str:
    return url.strip().rstrip("#").rstrip("?").rstrip("/")


def load_base_report(
    base_ref: str,
    path: str,
    report_type: str,
    loader: Callable[[str, str], str],
) -> dict[str, Any]:
    report = _load_json_text(loader(base_ref, path), path)
    if report.get("report_type") != report_type:
        raise ValueError(f"{path}: expected report_type={report_type}")
    forbidden = find_forbidden_fields(report)
    if forbidden:
        raise ValueError(f"{path}: self-certifying field(s) are not allowed: {', '.join(forbidden)}")
    return report


def changed_top_level_keys(base: dict[str, Any], head: dict[str, Any]) -> set[str]:
    keys = set(base) | set(head)
    return {key for key in keys if base.get(key) != head.get(key)}


def validate_source_delta(
    path: str,
    base_source: dict[str, Any],
    head_source: dict[str, Any],
    approved: dict[tuple[str, str, str], dict[str, Any]],
    evidence: dict[tuple[str, str, str], dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    vendor_id = str(base_source.get("vendor_id") or "")
    source_id = str(base_source.get("source_id") or "")
    original_url = str(base_source.get("source_url") or "")
    key = (vendor_id, source_id, original_url)
    row = approved.get(key)
    evidence_row = evidence.get(key)

    expected_path = source_path(vendor_id, source_id)
    if path != expected_path:
        reasons.append(f"source_path_mismatch:{path}!={expected_path}")
    if row is None:
        reasons.append(f"approved_repair_missing:{vendor_id}:{source_id}")
        return reasons
    if evidence_row is None:
        reasons.append(f"evidence_row_missing:{vendor_id}:{source_id}")
        return reasons

    changed = changed_top_level_keys(base_source, head_source)
    unexpected = sorted(changed - ALLOWED_SOURCE_TOP_LEVEL_CHANGES)
    reasons.extend(f"unexpected_source_field_change:{field}" for field in unexpected)

    original = evidence_row.get("original")
    prior = original.get("prior") if isinstance(original, dict) else None
    fresh = original.get("fresh") if isinstance(original, dict) else None
    if not isinstance(prior, dict) or not isinstance(fresh, dict):
        reasons.append("evidence_original_pair_missing")
    else:
        prior_status = prior.get("verification_status")
        fresh_status = fresh.get("verification_status")
        if (prior_status, fresh_status) not in {("not_found", "not_found"), ("gone", "gone")}:
            reasons.append(f"evidence_status_pair_not_confirmed_p0:{prior_status}:{fresh_status}")

    if row.get("reasons") not in ([], None):
        reasons.append("approved_row_contains_rejection_reasons")
    if row.get("source_type") != base_source.get("source_type") or head_source.get("source_type") != base_source.get("source_type"):
        reasons.append("source_type_changed")
    if evidence_row.get("source_type") != base_source.get("source_type"):
        reasons.append("evidence_source_type_mismatch")
    if row.get("replacement_verification_status") not in ALLOWED_REPLACEMENT_STATUSES:
        reasons.append("replacement_verification_status_not_ok")
    http_status = row.get("replacement_http_status")
    if not isinstance(http_status, int) or http_status < 200 or http_status >= 400:
        reasons.append("replacement_http_status_not_2xx_or_3xx")
    if row.get("replacement_semantic_status") != "strong":
        reasons.append("replacement_semantic_status_not_strong")
    if row.get("replacement_authority_status") not in ALLOWED_AUTHORITY_STATUSES:
        reasons.append("replacement_authority_status_not_allowed")
    if row.get("replacement_access_status") not in ALLOWED_ACCESS_STATUSES:
        reasons.append("replacement_access_status_not_public")
    if row.get("replacement_url_safety_status") != "passed":
        reasons.append("replacement_url_safety_not_passed")

    replacement_url = str(row.get("replacement_source_url") or "")
    if normalize_url(replacement_url) == normalize_url(original_url):
        reasons.append("replacement_url_same_as_original")
    if head_source.get("source_url") != replacement_url:
        reasons.append("head_source_url_not_approved_replacement")
    if head_source.get("review_state") != "human_reviewed":
        reasons.append("head_review_state_not_human_reviewed")
    if head_source.get("catalog_tier") != "human_reviewed":
        reasons.append("head_catalog_tier_not_human_reviewed")
    provenance = head_source.get("provenance")
    if isinstance(provenance, dict):
        if provenance.get("observer") != "human":
            reasons.append("head_provenance_observer_not_human")
        if provenance.get("confidence") != "high":
            reasons.append("head_provenance_confidence_not_high")
    else:
        reasons.append("head_provenance_missing")
    return reasons


def check_source_repair_automerge(
    changed_paths: list[str],
    validation_report: dict[str, Any],
    evidence_report: dict[str, Any],
    base_ref: str,
    head_ref: str,
    loader: Callable[[str, str], str] = git_show,
    max_source_repairs: int = DEFAULT_MAX_SOURCE_REPAIRS,
) -> SourceRepairAutomergeResult:
    reasons: list[str] = []
    paths = [path.strip() for path in changed_paths if path.strip()]
    if not paths:
        return SourceRepairAutomergeResult(False, ("no_changed_paths",), 0)

    bad_paths = [path for path in paths if not (is_source_path(path) or is_generated_catalog_path(path))]
    reasons.extend(f"disallowed_path:{path}" for path in bad_paths)
    source_paths = [path for path in paths if is_source_path(path)]
    if not source_paths:
        reasons.append("no_source_repairs")
    if len(source_paths) > max_source_repairs:
        reasons.append(f"source_repair_record_limit_exceeded:{len(source_paths)}>{max_source_repairs}")

    if validation_report.get("report_type") != VALIDATION_REPORT_TYPE:
        reasons.append("validation_report_type_invalid")
    if evidence_report.get("report_type") != EVIDENCE_REPORT_TYPE:
        reasons.append("evidence_report_type_invalid")
    validation_forbidden = find_forbidden_fields(validation_report)
    evidence_forbidden = find_forbidden_fields(evidence_report)
    reasons.extend(f"validation_self_certifying_field:{field}" for field in validation_forbidden)
    reasons.extend(f"evidence_self_certifying_field:{field}" for field in evidence_forbidden)

    approved_rows = validation_report.get("approved")
    evidence_rows = evidence_report.get("repairs")
    if not isinstance(approved_rows, list):
        reasons.append("validation_approved_rows_missing")
        approved_rows = []
    if not isinstance(evidence_rows, list):
        reasons.append("evidence_repairs_missing")
        evidence_rows = []

    approved = {approved_key(row): row for row in approved_rows if isinstance(row, dict)}
    evidence = {evidence_key(row): row for row in evidence_rows if isinstance(row, dict)}
    changed_source_keys: set[tuple[str, str, str]] = set()

    for path in source_paths:
        try:
            base_source = _load_yaml_text(loader(base_ref, path), f"{base_ref}:{path}")
            head_source = _load_yaml_text(loader(head_ref, path), f"{head_ref}:{path}")
        except Exception as exc:  # noqa: BLE001 - eligibility must fail closed.
            reasons.append(f"source_load_failed:{path}:{type(exc).__name__}")
            continue
        key = (
            str(base_source.get("vendor_id") or ""),
            str(base_source.get("source_id") or ""),
            str(base_source.get("source_url") or ""),
        )
        changed_source_keys.add(key)
        reasons.extend(validate_source_delta(path, base_source, head_source, approved, evidence))

    unused_approved = sorted(set(approved) - changed_source_keys)
    reasons.extend(f"approved_repair_not_changed:{vendor_id}:{source_id}" for vendor_id, source_id, _ in unused_approved)

    return SourceRepairAutomergeResult(not reasons, tuple(reasons), len(source_paths))


def extract_reviewed_inputs(body: str) -> dict[str, str]:
    patterns = {
        "VALIDATION_REPORT_PATH": r"Validation report:\s*`([^`]+)`",
        "EVIDENCE_REPORT_PATH": r"Evidence report:\s*`([^`]+)`",
    }
    values: dict[str, str] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, body)
        if match:
            values[key] = validate_reviewed_report_path(match.group(1), key.lower())
    missing = sorted(set(patterns) - set(values))
    if missing:
        raise ValueError(f"missing reviewed input(s): {', '.join(missing)}")
    return values


def max_source_repairs_from_policy(path: str) -> int:
    policy_path = PurePosixPath(path)
    if str(policy_path):
        try:
            policy = yaml.safe_load(open(path, encoding="utf-8")) or {}
        except FileNotFoundError:
            return DEFAULT_MAX_SOURCE_REPAIRS
        return int(policy.get("source_repair", {}).get("max_source_records_per_pr", DEFAULT_MAX_SOURCE_REPAIRS))
    return DEFAULT_MAX_SOURCE_REPAIRS


def write_env(values: dict[str, str], output: str) -> None:
    with open(output, "w", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-automerge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract-inputs")
    extract.add_argument("--body-file", required=True)
    extract.add_argument("--output", required=True)

    check = subparsers.add_parser("check")
    check.add_argument("--paths-file", required=True)
    check.add_argument("--base-ref", required=True)
    check.add_argument("--head-ref", required=True)
    check.add_argument("--validation-report", required=True)
    check.add_argument("--evidence-report", required=True)
    check.add_argument("--policy", default="config/automerge-policy.yaml")

    args = parser.parse_args(argv)
    if args.command == "extract-inputs":
        body = open(args.body_file, encoding="utf-8").read()
        write_env(extract_reviewed_inputs(body), args.output)
        return 0

    validation_path = validate_reviewed_report_path(args.validation_report, "validation_report")
    evidence_path = validate_reviewed_report_path(args.evidence_report, "evidence_report")
    validation_report = load_base_report(args.base_ref, validation_path, VALIDATION_REPORT_TYPE, git_show)
    evidence_report = load_base_report(args.base_ref, evidence_path, EVIDENCE_REPORT_TYPE, git_show)
    paths = open(args.paths_file, encoding="utf-8").read().splitlines()
    result = check_source_repair_automerge(
        paths,
        validation_report,
        evidence_report,
        args.base_ref,
        args.head_ref,
        max_source_repairs=max_source_repairs_from_policy(args.policy),
    )
    print(f"eligible={str(result.eligible).lower()}")
    print(f"source_repairs={result.source_repairs}")
    for reason in result.reasons:
        print(f"reason={reason}")
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
