from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.openva.advisory_wording import prohibited_terms_in_text
from tools.openva.automerge_lanes import EligibilityResult, load_policy

LANE = "automerge:strict-growth"
INFORMATIONAL_REASONS = {
    "base_sha_mismatch_warning",
    "eligibility_report_missing_used_promotion_plan_timestamp",
}
SOURCE_PREFLIGHT_FAIL_STATUSES = {
    "not_found",
    "gone",
    "bot_protected",
    "forbidden_unknown",
    "gated_or_login_required",
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "rate_limited",
    "suspect_inferred_url",
    "unreachable",
    "client_error",
    "server_error",
    "soft_not_found",
    "soft_404_detected",
}
STRICT_GROWTH_ROOT_PLAN = "strict-growth-promotion-plan.json"
STRICT_GROWTH_ROOT_ELIGIBILITY_REPORT = "catalog-growth-eligibility-report.json"
STRICT_GROWTH_GENERATED_PREFIX = "maintenance/generated/strict-growth-"


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_body_path(value: str) -> str:
    return value.strip().replace("\\", "/")


def is_allowed_strict_growth_plan_path(path: str) -> bool:
    normalized = normalize_body_path(path)
    return normalized == STRICT_GROWTH_ROOT_PLAN or (
        normalized.startswith(STRICT_GROWTH_GENERATED_PREFIX) and normalized.endswith(".json")
    )


def is_allowed_strict_growth_eligibility_path(path: str) -> bool:
    normalized = normalize_body_path(path)
    return normalized == STRICT_GROWTH_ROOT_ELIGIBILITY_REPORT or (
        normalized.startswith(STRICT_GROWTH_GENERATED_PREFIX) and normalized.endswith(".json")
    )


def body_value(body: str, label: str) -> str | None:
    pattern = re.compile(rf"^\s*-\s*{re.escape(label)}:\s*`([^`]+)`\s*$", re.MULTILINE)
    match = pattern.search(body)
    if match:
        return match.group(1).strip()
    return None


def sha256_for(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def action_count_for(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    actions = data.get("actions", []) if isinstance(data, dict) else []
    if not isinstance(actions, list):
        raise ValueError(f"{path}: actions must be a list")
    return len(actions)


def env_escape(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("environment value must be single-line")
    return value


def extract_inputs_from_body(body: str, *, repo_root: Path = Path(".")) -> dict[str, str]:
    plan_path = body_value(body, "Promotion plan")
    plan_sha = body_value(body, "Promotion plan SHA-256")
    action_count = body_value(body, "Action count")
    eligibility_path = body_value(body, "Strict-growth eligibility report") or body_value(
        body, "Eligibility report"
    )
    head_sha = body_value(body, "Head SHA")
    base_sha = body_value(body, "Base SHA")

    if not plan_path:
        raise ValueError("promotion_plan_path_missing")
    if not plan_sha:
        raise ValueError("promotion_plan_sha256_missing")
    if not action_count:
        raise ValueError("promotion_plan_action_count_missing")
    if not eligibility_path:
        raise ValueError("eligibility_report_path_missing")
    if not head_sha:
        raise ValueError("head_sha_missing")

    plan_path = normalize_body_path(plan_path)
    eligibility_path = normalize_body_path(eligibility_path)
    if not is_allowed_strict_growth_plan_path(plan_path):
        raise ValueError(f"promotion_plan_path_not_allowed:{plan_path}")
    if not is_allowed_strict_growth_eligibility_path(eligibility_path):
        raise ValueError(f"eligibility_report_path_not_allowed:{eligibility_path}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", plan_sha):
        raise ValueError("promotion_plan_sha256_invalid")
    if not re.fullmatch(r"[0-9]+", action_count):
        raise ValueError("promotion_plan_action_count_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise ValueError("head_sha_invalid")
    if base_sha and not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise ValueError("base_sha_invalid")

    plan_file = repo_root / plan_path
    eligibility_file = repo_root / eligibility_path
    if not plan_file.is_file():
        raise ValueError(f"promotion_plan_file_missing:{plan_path}")
    if not eligibility_file.is_file():
        raise ValueError(f"eligibility_report_file_missing:{eligibility_path}")
    actual_sha = sha256_for(plan_file)
    if actual_sha != plan_sha:
        raise ValueError(f"promotion_plan_sha256_mismatch:{actual_sha}!={plan_sha}")
    actual_action_count = str(action_count_for(plan_file))
    if actual_action_count != action_count:
        raise ValueError(f"promotion_plan_action_count_mismatch:{actual_action_count}!={action_count}")

    result = {
        "PROMOTION_PLAN_PATH": plan_path,
        "PROMOTION_PLAN_SHA256": plan_sha,
        "PROMOTION_PLAN_ACTION_COUNT": action_count,
        "ELIGIBILITY_REPORT_PATH": eligibility_path,
        "STRICT_GROWTH_HEAD_SHA": head_sha,
    }
    if base_sha:
        result["STRICT_GROWTH_BASE_SHA"] = base_sha
    return result


def write_env(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={env_escape(value)}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def strict_growth_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return policy.get("strict_growth", {})


def action_value(action: dict[str, Any], dotted_path: str) -> Any:
    value: Any = action
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def action_id(action: dict[str, Any], policy: dict[str, Any]) -> str:
    fields = strict_growth_policy(policy).get(
        "action_id_fields",
        ["vendor.candidate_vendor_id", "source.source_type_candidate", "source.candidate_source_id"],
    )
    parts = []
    for field in fields:
        value = action_value(action, field)
        parts.append(str(value) if value not in {None, ""} else "missing")
    return ":".join(parts)


def append_reason(
    reasons: list[str],
    reason: str,
    action: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> None:
    if action is not None and policy is not None:
        reasons.append(f"{reason}:{action_id(action, policy)}")
    else:
        reasons.append(reason)


def evidence_value(
    key: str,
    promotion_plan: dict[str, Any],
    eligibility_report: dict[str, Any] | None,
) -> str | None:
    if eligibility_report is not None and eligibility_report.get(key):
        return str(eligibility_report[key])
    if promotion_plan.get(key):
        return str(promotion_plan[key])
    return None


def evidence_timestamp(
    promotion_plan: dict[str, Any],
    eligibility_report: dict[str, Any] | None,
    reasons: list[str],
) -> tuple[datetime | None, str | None]:
    promotion_generated_at = parse_timestamp(str(promotion_plan.get("generated_at") or ""))
    if eligibility_report is not None:
        eligibility_generated_at = parse_timestamp(str(eligibility_report.get("generated_at") or ""))
        if eligibility_generated_at is None:
            reasons.append("eligibility_report_timestamp_missing")
            return None, None
        return eligibility_generated_at, "eligibility_report.generated_at"
    if promotion_generated_at is None:
        reasons.append("evidence_timestamp_missing")
        return None, None
    reasons.append("eligibility_report_missing_used_promotion_plan_timestamp")
    return promotion_generated_at, "promotion_plan.generated_at"


def relationship_records(action: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("relationships", "entity_relationships", "source_attested_relationships"):
        value = action.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    for key in ("legal_entities", "entity_mentions", "entities"):
        value = action.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def check_relationship_record(
    record: dict[str, Any],
    action: dict[str, Any],
    policy: dict[str, Any],
    reasons: list[str],
) -> None:
    sg = strict_growth_policy(policy)
    attestation_mode = record.get("attestation_mode")
    inference_mode = record.get("inference_mode")
    allowed_attestation = set(sg.get("allowed_attestation_modes", []))
    allowed_inference = set(sg.get("allowed_inference_modes", []))
    blocked_inference = set(sg.get("blocked_inference_modes", []))
    prefixes = tuple(sg.get("relationship_type_prefixes", []))

    if attestation_mode in {None, ""}:
        append_reason(reasons, "attestation_mode_missing", action, policy)
    elif attestation_mode not in allowed_attestation:
        append_reason(reasons, f"attestation_mode_not_allowed:{attestation_mode}", action, policy)

    if inference_mode in {None, ""}:
        append_reason(reasons, "inference_mode_missing", action, policy)
    elif inference_mode in blocked_inference:
        append_reason(reasons, f"blocked_inference_mode:{inference_mode}", action, policy)
    elif inference_mode not in allowed_inference:
        append_reason(reasons, f"inference_mode_not_allowed:{inference_mode}", action, policy)

    relationship_type = record.get("relationship_type")
    if relationship_type and prefixes and not str(relationship_type).startswith(prefixes):
        append_reason(reasons, f"relationship_type_not_allowed:{relationship_type}", action, policy)

    if attestation_mode == "source_attested":
        for field in sg.get("source_attested_required_fields", []):
            if not record.get(field):
                append_reason(reasons, f"source_attested_required_field_missing:{field}", action, policy)
    if attestation_mode == "registry_attested":
        for field in sg.get("registry_attested_required_fields", []):
            if not record.get(field):
                append_reason(reasons, f"registry_attested_required_field_missing:{field}", action, policy)


def check_action(action: dict[str, Any], policy: dict[str, Any], reasons: list[str]) -> None:
    sg = strict_growth_policy(policy)
    field = sg.get("required_action_field", "strict_machine_candidate")
    value = action.get(field)
    if field not in action:
        append_reason(reasons, f"{field}_missing", action, policy)
    elif not isinstance(value, bool):
        append_reason(reasons, f"{field}_not_boolean", action, policy)
    elif value is not True:
        append_reason(reasons, f"{field}_false", action, policy)

    if action.get("requires_human_review") is True or action.get("review_state") in {
        "review_required",
        "human_review_required",
        "deferred",
        "rejected",
        "ambiguous",
    }:
        append_reason(reasons, "review_required_action", action, policy)

    source_type = action_value(action, "source.source_type_candidate")
    core_source_types = set(sg.get("core_source_types", []))
    if source_type not in core_source_types:
        append_reason(reasons, f"non_core_source_type:{source_type}", action, policy)

    advisory_values = [
        action_value(action, "source.title"),
        action_value(action, "source.description"),
        action_value(action, "source.evidence.page_title"),
    ]
    for value in advisory_values:
        for term in prohibited_terms_in_text(value):
            append_reason(reasons, f"strict_growth_advisory_wording_detected:{term}", action, policy)

    verification_status = action_value(action, "source.evidence.verification_status")
    if verification_status in SOURCE_PREFLIGHT_FAIL_STATUSES:
        append_reason(reasons, f"source_preflight_risk:{verification_status}", action, policy)
    if action_value(action, "source.evidence.soft_404_detected") is True:
        append_reason(reasons, "source_preflight_risk:soft_404_detected", action, policy)

    for record in relationship_records(action):
        check_relationship_record(record, action, policy, reasons)


def check_strict_growth_eligibility(
    *,
    promotion_plan: dict[str, Any],
    eligibility_report: dict[str, Any] | None,
    labels: list[str],
    current_head_sha: str,
    recorded_head_sha: str | None = None,
    current_base_sha: str = "",
    recorded_base_sha: str | None = None,
    now: datetime,
    policy: dict[str, Any] | None = None,
) -> EligibilityResult:
    policy = policy or load_policy()
    sg = strict_growth_policy(policy)
    report_only = policy.get("mode", "report_only") != "enforce"
    reasons: list[str] = []
    labels_set = {label.strip() for label in labels if label.strip()}

    if report_only:
        reasons.append("report_only_not_merge_authority")

    label = sg.get("label", LANE)
    if label not in labels_set:
        reasons.append(f"required_label_missing:{label}")
    for required_label in sg.get("required_labels", []):
        if required_label not in labels_set:
            reasons.append(f"required_label_missing:{required_label}")

    effective_recorded_head_sha = recorded_head_sha or evidence_value("head_sha", promotion_plan, eligibility_report)
    effective_recorded_base_sha = recorded_base_sha or evidence_value("base_sha", promotion_plan, eligibility_report)

    if not effective_recorded_head_sha:
        reasons.append("recorded_head_sha_missing")
    elif current_head_sha != effective_recorded_head_sha:
        reasons.append("head_sha_mismatch")

    if not effective_recorded_base_sha:
        reasons.append("recorded_base_sha_missing")
    elif current_base_sha and current_base_sha != effective_recorded_base_sha:
        reasons.append("base_sha_mismatch_warning")

    timestamp, _source = evidence_timestamp(promotion_plan, eligibility_report, reasons)
    if timestamp is None:
        reasons.append("evidence_timestamp_missing")
    else:
        freshness_hours = int(sg.get("freshness_hours", policy.get("freshness", {}).get("strict_growth_hours", 4)))
        if now.astimezone(UTC) - timestamp > timedelta(hours=freshness_hours):
            reasons.append("evidence_timestamp_expired")

    actions = promotion_plan.get("actions")
    if not isinstance(actions, list) or not actions:
        reasons.append("promotion_plan_actions_missing")
        actions = []

    vendor_ids: set[str] = set()
    source_counts: Counter[str] = Counter()
    for action in actions:
        if not isinstance(action, dict):
            reasons.append("promotion_action_not_object")
            continue
        vendor_id = action_value(action, "vendor.candidate_vendor_id")
        if not vendor_id:
            append_reason(reasons, "candidate_vendor_id_missing", action, policy)
        else:
            vendor_ids.add(str(vendor_id))
            source_counts[str(vendor_id)] += 1
        check_action(action, policy, reasons)

    max_vendors = int(sg.get("max_new_vendors_per_pr", 5))
    if len(vendor_ids) > max_vendors:
        reasons.append(f"new_vendor_limit_exceeded:{len(vendor_ids)}>{max_vendors}")

    max_sources = int(sg.get("max_sources_per_new_vendor", 2))
    for vendor_id, count in sorted(source_counts.items()):
        if count > max_sources:
            reasons.append(f"vendor_source_limit_exceeded:{vendor_id}:{count}>{max_sources}")

    hard_failure_reasons = tuple(reason for reason in reasons if reason not in INFORMATIONAL_REASONS)
    eligible = not report_only and not hard_failure_reasons
    return EligibilityResult(eligible, label, tuple(reasons), report_only)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    command = "check"
    if raw_argv and raw_argv[0] == "extract-inputs":
        parser = argparse.ArgumentParser(description="Extract strict-growth automerge inputs from a PR body.")
        parser.add_argument("command", nargs="?")
        parser.add_argument("--body-file", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--repo-root", type=Path, default=Path("."))
        args = parser.parse_args(raw_argv)
        try:
            values = extract_inputs_from_body(
                args.body_file.read_text(encoding="utf-8"),
                repo_root=args.repo_root,
            )
        except ValueError as exc:
            print(f"input_valid=false")
            print(f"reason={exc}", file=sys.stderr)
            return 1
        write_env(args.output, values)
        print("input_valid=true")
        for key in sorted(values):
            print(f"{key}={values[key]}")
        return 0

    if raw_argv and raw_argv[0] == "check-plan":
        command = "check-plan"
        raw_argv = raw_argv[1:]

    parser = argparse.ArgumentParser(description="Check strict catalog growth automerge eligibility.")
    parser.add_argument("--promotion-plan", type=Path, required=True)
    parser.add_argument("--eligibility-report", type=Path)
    parser.add_argument("--labels", default="")
    parser.add_argument("--current-head-sha", required=True)
    parser.add_argument("--recorded-head-sha", default="")
    parser.add_argument("--current-base-sha", required=True)
    parser.add_argument("--recorded-base-sha", default="")
    parser.add_argument("--policy", default="config/automerge-policy.yaml")
    parser.add_argument("--now")
    args = parser.parse_args(raw_argv)

    promotion_plan = json.loads(args.promotion_plan.read_text(encoding="utf-8"))
    eligibility_report = (
        json.loads(args.eligibility_report.read_text(encoding="utf-8"))
        if args.eligibility_report
        else None
    )
    now = parse_timestamp(args.now) if args.now else datetime.now(UTC)
    if now is None:
        raise ValueError("invalid --now timestamp")

    result = check_strict_growth_eligibility(
        promotion_plan=promotion_plan,
        eligibility_report=eligibility_report,
        labels=[label for label in args.labels.split(",") if label],
        current_head_sha=args.current_head_sha,
        recorded_head_sha=args.recorded_head_sha or None,
        current_base_sha=args.current_base_sha,
        recorded_base_sha=args.recorded_base_sha or None,
        now=now,
        policy=load_policy(args.policy),
    )

    if command == "check-plan":
        print(f"plan_valid={str(result.eligible).lower()}")
    else:
        print(f"eligible={str(result.eligible).lower()}")
    print(f"lane={result.lane}")
    print(f"report_only={str(result.report_only).lower()}")
    for reason in result.reasons:
        print(f"reason={reason}")
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
