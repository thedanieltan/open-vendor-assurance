from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT_CHATOPS = Path("docs/operations/contracts/bot-chatops.yaml")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
DEFAULT_REPORT = Path("maintenance/bot-chatops-decision.json")


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_contracts(root: Path = ROOT) -> dict[str, Any]:
    return {
        "chatops": load_yaml(root / BOT_CHATOPS),
        "authority": load_yaml(root / BOT_AUTHORITY),
        "queue": load_yaml(root / BOT_QUEUE_POLICY),
        "failure_taxonomy": load_yaml(root / BOT_FAILURE_TAXONOMY),
    }


def command_by_full_command(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(command["full_command"]): command for command in contract.get("commands", [])}


def authority_lane_ids(authority: dict[str, Any]) -> set[str]:
    return {str(lane["id"]) for lane in authority.get("lanes", [])}


def queue_lane_ids(queue: dict[str, Any]) -> set[str]:
    return {str(lane["lane_id"]) for lane in queue.get("lanes", [])}


def failure_codes(failure_taxonomy: dict[str, Any]) -> set[str]:
    return {str(entry["code"]) for entry in failure_taxonomy.get("failure_classes", [])}


def openva_command_lines(comment: str, prefix: str) -> list[str]:
    lines: list[str] = []
    for raw_line in comment.splitlines():
        stripped = raw_line.strip()
        if stripped == prefix or stripped.startswith(f"{prefix} "):
            lines.append(stripped)
    return lines


def normalize_command(line: str) -> str:
    return " ".join(line.split())


def parse_comment(comment: str, contract: dict[str, Any]) -> dict[str, Any]:
    prefix = str(contract["prefix"])
    command_lines = openva_command_lines(comment, prefix)
    if not command_lines:
        return {
            "raw_comment": comment,
            "parsed_command": None,
            "normalized_command": None,
            "multiple_commands": False,
            "parse_status": "ignored",
            "reasons": ["no_openva_command"],
        }
    normalized = [normalize_command(line) for line in command_lines]
    if len(normalized) > 1:
        return {
            "raw_comment": comment,
            "parsed_command": None,
            "normalized_command": None,
            "multiple_commands": True,
            "parse_status": "denied",
            "reasons": ["multiple_openva_commands"],
        }
    full_command = normalized[0]
    parts = full_command.split()
    parsed_command = parts[1] if len(parts) == 2 else None
    if parsed_command is None:
        return {
            "raw_comment": comment,
            "parsed_command": None,
            "normalized_command": full_command,
            "multiple_commands": False,
            "parse_status": "denied",
            "reasons": ["invalid_openva_command_syntax"],
        }
    return {
        "raw_comment": comment,
        "parsed_command": parsed_command,
        "normalized_command": full_command,
        "multiple_commands": False,
        "parse_status": "parsed",
        "reasons": [],
    }


def next_safe_action(decision: str, reasons: list[str], command_entry: dict[str, Any] | None) -> str:
    if decision == "ignored":
        return "No OpenVA command was found; take no bot action."
    if "multiple_openva_commands" in reasons:
        return "Ask the maintainer to submit one OpenVA command per comment."
    if "unknown_openva_command" in reasons:
        return "Deny the command and add it to bot-chatops.yaml only through a reviewed contract PR."
    if "actor_not_authorized" in reasons:
        return "Deny the command until a maintainer issues it."
    if "lane_not_declared" in reasons:
        return "Deny the command until the lane is declared in bot-authority.yaml."
    if "queue_lane_not_declared" in reasons:
        return "Deny the command until the queue lane is declared in bot-queue-policy.yaml."
    if decision == "accepted_report_only" and command_entry:
        return "Record the chatops decision report; do not execute the command until a future authority PR enables it."
    return "Deny the command and require maintainer review."


def build_decision(
    comment: str,
    actor_role: str,
    *,
    contracts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contracts = contracts or load_contracts()
    chatops = contracts["chatops"]
    parsed = parse_comment(comment, chatops)
    command_entry = None
    reasons = list(parsed["reasons"])
    decision = "ignored" if parsed["parse_status"] == "ignored" else "denied"

    if parsed["parse_status"] == "parsed":
        command_entry = command_by_full_command(chatops).get(parsed["normalized_command"])
        if command_entry is None:
            reasons.append("unknown_openva_command")
        else:
            if actor_role not in command_entry.get("allowed_actors", []):
                reasons.append("actor_not_authorized")
            if command_entry.get("lane_id") not in authority_lane_ids(contracts["authority"]):
                reasons.append("lane_not_declared")
            if command_entry.get("requires_queue_check"):
                queue_lane_id = command_entry.get("queue_lane_id") or command_entry.get("lane_id")
                if queue_lane_id not in queue_lane_ids(contracts["queue"]):
                    reasons.append("queue_lane_not_declared")
            if command_entry.get("requires_failure_router") and not failure_codes(contracts["failure_taxonomy"]):
                reasons.append("failure_taxonomy_missing")
            if command_entry.get("requires_failure_router"):
                unknown_failure_codes = [
                    code
                    for code in command_entry.get("failure_router_codes", []) or []
                    if code not in failure_codes(contracts["failure_taxonomy"])
                ]
                if unknown_failure_codes:
                    reasons.append("failure_router_code_not_declared")
            if command_entry.get("executable") is not False:
                reasons.append("command_unexpectedly_executable")
            if command_entry.get("report_only") is not True:
                reasons.append("command_not_report_only")
            if not reasons:
                decision = "accepted_report_only"
                reasons.append("command_accepted_report_only")

    authorized = bool(command_entry and actor_role in command_entry.get("allowed_actors", []) and decision == "accepted_report_only")
    lane_id = command_entry.get("lane_id") if command_entry else None
    side_effect_class = command_entry.get("side_effect_class") if command_entry else None
    executable = bool(command_entry.get("executable")) if command_entry else False
    report_only = bool(command_entry.get("report_only")) if command_entry else True
    requires_queue_check = bool(command_entry.get("requires_queue_check")) if command_entry else False
    requires_failure_router = bool(command_entry.get("requires_failure_router")) if command_entry else False
    audit_artifacts = command_entry.get("audit_artifacts", []) if command_entry else []

    return {
        "version": 1,
        "report_type": "bot_chatops_decision",
        "raw_comment": comment,
        "parsed_command": parsed["parsed_command"],
        "normalized_command": parsed["normalized_command"],
        "actor_role": actor_role,
        "authorized": authorized,
        "lane_id": lane_id,
        "queue_lane_id": command_entry.get("queue_lane_id") if command_entry else None,
        "side_effect_class": side_effect_class,
        "executable": executable,
        "report_only": report_only,
        "requires_queue_check": requires_queue_check,
        "requires_failure_router": requires_failure_router,
        "decision": decision,
        "reasons": reasons,
        "next_safe_action": next_safe_action(decision, reasons, command_entry),
        "audit_artifacts": audit_artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-chatops")
    subparsers = parser.add_subparsers(dest="command", required=True)
    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("--comment-file", type=Path, required=True)
    parse_parser.add_argument("--actor-role", required=True)
    parse_parser.add_argument("--out", type=Path, default=ROOT / DEFAULT_REPORT)
    args = parser.parse_args(argv)

    if args.command == "parse":
        comment = args.comment_file.read_text(encoding="utf-8")
        report = build_decision(comment, args.actor_role)
        out = args.out if args.out.is_absolute() else ROOT / args.out
        write_json(out, report)
        print(json.dumps({"decision": report["decision"], "reasons": report["reasons"]}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
