from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
DEFAULT_REPORT = Path("maintenance/bot-failure-routing-report.json")

REQUIRED_TAXONOMY_FIELDS = {
    "code",
    "summary",
    "retry_eligible",
    "retry_policy",
    "escalation_target",
    "open_or_update_hardening_issue",
    "defer_candidate",
    "stop_lane",
}

MESSAGE_RULES: list[tuple[str, str]] = [
    ("unexpected inputs provided", "workflow_input_compatibility_failure"),
    ("workflow input compatibility", "workflow_input_compatibility_failure"),
    ("schema validation failed", "schema_validation_failure"),
    ("schema validation failure", "schema_validation_failure"),
    ("generated files are stale", "generated_drift_failure"),
    ("generated drift", "generated_drift_failure"),
    ("deterministic generated outputs", "generated_drift_failure"),
    ("permission denied by bot authority", "permission_policy_denial"),
    ("permission policy denial", "permission_policy_denial"),
    ("exceeds declared lane authority", "permission_policy_denial"),
    ("source preflight", "source_preflight_failure"),
    ("redirect canonicalization", "redirect_canonicalization_failure"),
    ("final url", "redirect_canonicalization_failure"),
    ("duplicate url", "duplicate_url_failure"),
    ("duplicate source", "duplicate_url_failure"),
    ("terminology contract", "terminology_contract_failure"),
    ("deprecated terminology", "terminology_contract_failure"),
    ("automerge lane mismatch", "automerge_lane_mismatch"),
    ("no_automerge_label", "automerge_lane_mismatch"),
    ("external fetch", "external_fetch_instability"),
    ("rate-limited", "external_fetch_instability"),
    ("rate limited", "external_fetch_instability"),
    ("stale evidence", "stale_evidence_failure"),
    ("evidence is older", "stale_evidence_failure"),
]

QUEUE_REASON_RULES: dict[str, str] = {
    "stale_evidence": "stale_evidence_failure",
    "missing_evidence": "stale_evidence_failure",
    "duplicate_pr_policy": "duplicate_url_failure",
    "pause_switch_active": "permission_policy_denial",
    "unknown_lane": "permission_policy_denial",
    "lane_missing_queue_policy": "permission_policy_denial",
    "lane_not_write_capable": "permission_policy_denial",
    "lane_not_deny_by_default": "permission_policy_denial",
    "permission_policy_denial": "permission_policy_denial",
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def load_input(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected JSON object")
        return data
    return load_yaml(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    source = report.get("source") or {}
    lines = [
        "# OpenVA Bot Failure Routing",
        "",
        "## Classification",
        "",
        f"- Lane: `{report.get('lane_id')}`",
        f"- Matched failure code: `{report.get('matched_failure_code')}`",
        f"- Classification: `{report.get('classification')}`",
        f"- Match confidence: `{report.get('match_confidence')}`",
        f"- Match basis: `{report.get('match_basis')}`",
        "",
        "## Behavior",
        "",
        f"- Retry eligible: `{report.get('retry_eligible')}`",
        f"- Retry policy: {report.get('retry_policy')}",
        f"- Escalation target: `{report.get('escalation_target')}`",
        f"- Open or update hardening issue later: `{report.get('open_or_update_hardening_issue')}`",
        f"- Defer candidate: `{report.get('defer_candidate')}`",
        f"- Stop lane: `{report.get('stop_lane')}`",
        f"- Next safe action: {report.get('next_safe_action')}",
        "",
        "## Source",
        "",
        f"- Message: `{source.get('message')}`",
        f"- Artifact: `{source.get('artifact')}`",
        f"- Queue decision: `{source.get('queue_decision')}`",
        f"- Queue reasons: `{', '.join(source.get('queue_reasons') or [])}`",
        "",
    ]
    return "\n".join(lines)


def load_taxonomy(root: Path = ROOT) -> dict[str, Any]:
    taxonomy = load_yaml(root / BOT_FAILURE_TAXONOMY)
    for entry in taxonomy.get("failure_classes", []):
        missing = REQUIRED_TAXONOMY_FIELDS - set(entry)
        if missing:
            raise ValueError(f"{entry.get('code', '<unknown>')}: missing {sorted(missing)}")
    return taxonomy


def taxonomy_by_code(taxonomy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entry["code"]): entry for entry in taxonomy.get("failure_classes", [])}


def failure_block(observation: dict[str, Any]) -> dict[str, Any]:
    value = observation.get("failure")
    return value if isinstance(value, dict) else {}


def message_for(observation: dict[str, Any]) -> str:
    failure = failure_block(observation)
    parts = [
        failure.get("message"),
        observation.get("message"),
    ]
    return " ".join(str(part) for part in parts if part).strip()


def queue_report(observation: dict[str, Any]) -> dict[str, Any]:
    value = observation.get("queue_report")
    return value if isinstance(value, dict) else {}


def match_failure_code(observation: dict[str, Any], taxonomy: dict[str, Any]) -> tuple[str | None, str, str]:
    known_codes = taxonomy_by_code(taxonomy)
    failure = failure_block(observation)
    explicit_code = failure.get("code") or observation.get("failure_code")
    if explicit_code:
        code = str(explicit_code)
        if code in known_codes:
            return code, "explicit", "failure.code"
        return None, "none", f"unknown explicit failure.code: {code}"

    normalized_message = message_for(observation).lower()
    for phrase, code in MESSAGE_RULES:
        if phrase in normalized_message and code in known_codes:
            return code, "message", f"message contains {phrase!r}"

    queue = queue_report(observation)
    for reason in queue.get("reasons", []) or []:
        code = QUEUE_REASON_RULES.get(str(reason))
        if code in known_codes:
            return code, "queue_report", f"queue_report.reasons contains {reason!r}"
    if queue.get("decision") == "deny":
        code = "permission_policy_denial"
        if code in known_codes:
            return code, "queue_report", "queue_report.decision is 'deny'"

    return None, "none", "manual classification required"


def next_safe_action_for(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "Stop the lane and ask a maintainer to classify the failure before retrying."
    code = entry["code"]
    if code == "stale_evidence_failure":
        return "Refresh evidence before retrying the lane."
    if code == "permission_policy_denial":
        return "Stop the lane and update policy through a reviewed contract PR before retrying."
    if entry["stop_lane"]:
        return f"Stop the lane and escalate to {entry['escalation_target']} before retry."
    if entry["defer_candidate"]:
        return f"Defer the candidate and follow retry policy: {entry['retry_policy']}."
    if entry["retry_eligible"]:
        return f"Retry only after satisfying policy: {entry['retry_policy']}."
    return f"Escalate to {entry['escalation_target']} before taking further action."


def manual_review_report(observation: dict[str, Any], match_basis: str) -> dict[str, Any]:
    return {
        "version": 1,
        "report_type": "bot_failure_routing",
        "lane_id": observation.get("lane_id"),
        "matched_failure_code": None,
        "classification": "manual_review_required",
        "match_confidence": "none",
        "match_basis": match_basis,
        "retry_eligible": False,
        "retry_policy": "manual classification required before retry",
        "escalation_target": "maintainer",
        "open_or_update_hardening_issue": False,
        "defer_candidate": False,
        "stop_lane": True,
        "next_safe_action": next_safe_action_for(None),
        "explanation": "The failure did not match a known taxonomy code or conservative message rule.",
        "source": {
            "message": message_for(observation) or None,
            "artifact": failure_block(observation).get("artifact") or observation.get("artifact"),
            "queue_decision": queue_report(observation).get("decision"),
            "queue_reasons": queue_report(observation).get("reasons", []),
        },
    }


def route_failure(observation: dict[str, Any], *, taxonomy: dict[str, Any] | None = None) -> dict[str, Any]:
    taxonomy = taxonomy or load_taxonomy()
    by_code = taxonomy_by_code(taxonomy)
    code, confidence, basis = match_failure_code(observation, taxonomy)
    if code is None:
        return manual_review_report(observation, basis)

    entry = by_code[code]
    return {
        "version": 1,
        "report_type": "bot_failure_routing",
        "lane_id": observation.get("lane_id"),
        "matched_failure_code": code,
        "classification": "taxonomy_match",
        "match_confidence": confidence,
        "match_basis": basis,
        "retry_eligible": entry["retry_eligible"],
        "retry_policy": entry["retry_policy"],
        "escalation_target": entry["escalation_target"],
        "open_or_update_hardening_issue": entry["open_or_update_hardening_issue"],
        "defer_candidate": entry["defer_candidate"],
        "stop_lane": entry["stop_lane"],
        "next_safe_action": next_safe_action_for(entry),
        "explanation": entry["summary"],
        "source": {
            "message": message_for(observation) or None,
            "artifact": failure_block(observation).get("artifact") or observation.get("artifact"),
            "queue_decision": queue_report(observation).get("decision"),
            "queue_reasons": queue_report(observation).get("reasons", []),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-failure-router")
    subparsers = parser.add_subparsers(dest="command", required=True)
    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("--input", type=Path, required=True)
    classify_parser.add_argument("--out", type=Path, default=ROOT / DEFAULT_REPORT)
    classify_parser.add_argument("--out-md", type=Path, help="Optional markdown failure routing report.")
    args = parser.parse_args(argv)

    if args.command == "classify":
        report = route_failure(load_input(args.input))
        output = args.out if args.out.is_absolute() else ROOT / args.out
        write_json(output, report)
        if args.out_md:
            output_md = args.out_md if args.out_md.is_absolute() else ROOT / args.out_md
            write_text(output_md, render_markdown(report))
        print(json.dumps({"matched_failure_code": report["matched_failure_code"]}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
