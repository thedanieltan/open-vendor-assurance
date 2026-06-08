from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.openva.bot_chatops import build_decision, command_by_full_command, load_contracts
from tools.openva.bot_failure_router import route_failure
from tools.openva.bot_queue import evaluate as evaluate_queue
from tools.openva.bot_queue import load_state as load_queue_state

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = Path("maintenance/bot-chatops-execution-report.json")

EXECUTABLE_COMMANDS = {"/openva explain-strict-growth", "/openva hold", "/openva unhold"}
HOLD_LABEL = "openva-hold"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def strict_growth_explanation() -> str:
    return "\n".join([
        "# OpenVA Strict-Growth Explanation", "",
        "Strict-growth is OpenVA's narrow automerge lane for reviewed catalog growth PRs.", "",
        "A strict-growth PR must:", "",
        "- use reviewed evidence or freshly generated strict-growth evidence",
        "- apply only selected promotion actions",
        "- pass source preflight for changed canonical source records",
        "- preserve catalog schema validity and deterministic generated outputs",
        "- match the declared catalog-growth and automerge labels",
        "- avoid broader source repair, workflow, or arbitrary catalog mutation", "",
        "Next safe action: inspect the PR evidence, labels, changed paths, source preflight report, and generated-output checks before relying on strict-growth automation.", "",
    ])


def command_entry_for(decision: dict[str, Any], contracts: dict[str, Any]) -> dict[str, Any] | None:
    normalized = decision.get("normalized_command")
    if not normalized:
        return None
    return command_by_full_command(contracts["chatops"]).get(str(normalized))


def queue_decision_for(command_entry: dict[str, Any], queue_state_path: Path | None) -> dict[str, Any] | None:
    if not command_entry.get("requires_queue_check"):
        return None
    if queue_state_path is None:
        return {
            "version": 1,
            "report_type": "bot_queue_decision",
            "lane_id": command_entry.get("queue_lane_id") or command_entry.get("lane_id"),
            "decision": "deny",
            "reasons": ["queue_state_required"],
            "violated_policies": ["chatops.execution.queue_state"],
            "next_safe_action": "Provide local queue state before executing queue-gated chatops commands.",
        }
    return evaluate_queue(str(command_entry.get("queue_lane_id") or command_entry.get("lane_id")), load_queue_state(queue_state_path))


def failure_routing_for(*, lane_id: str | None, message: str, queue_report: dict[str, Any] | None, failure_code: str | None = None) -> dict[str, Any]:
    observation: dict[str, Any] = {"version": 1, "lane_id": lane_id, "failure": {"message": message}}
    if failure_code:
        observation["failure"]["code"] = failure_code
    if queue_report:
        observation["queue_report"] = queue_report
    return route_failure(observation)


def execution_payload(command: str, context_kind: str) -> dict[str, Any]:
    if command == "/openva explain-strict-growth":
        return {
            "side_effect_class": "informational_report",
            "mutates_remote_state": False,
            "mutates_catalog": False,
            "dispatches_workflows": False,
            "label_mutation": None,
            "markdown": strict_growth_explanation(),
        }
    action = "apply" if command == "/openva hold" else "remove"
    return {
        "side_effect_class": "hold_label_mutation",
        "mutates_remote_state": False,
        "mutates_catalog": False,
        "dispatches_workflows": False,
        "label_mutation": {
            "allowed_label": HOLD_LABEL,
            "requested_action": action,
            "target_scope": "current_comment_thread",
            "context_kind": context_kind,
            "applied": False,
            "reason": "local CLI execution is audit-only; live mutation is performed only by bot-chatops.yml on issue_comment events",
        },
        "markdown": "\n".join([
            f"# OpenVA {'Hold' if action == 'apply' else 'Unhold'} Decision", "",
            f"- Label: `{HOLD_LABEL}`",
            f"- Requested action: `{action}`",
            "- Target scope: `current_comment_thread`",
            "- Applied by local CLI: `False`",
            "- Live mutation path: `bot-chatops.yml` issue_comment workflow.", "",
        ]),
    }


def next_safe_action_for(report: dict[str, Any]) -> str:
    if report["decision"] == "executed":
        return "Use the audit report output; local CLI execution does not mutate catalog data, PRs, branches, or workflows."
    if report["decision"] == "report_only_not_executable":
        return "Keep this command report-only until a future authority PR enables execution."
    if report["decision"] == "denied" and report.get("failure_routing_report"):
        return report["failure_routing_report"]["next_safe_action"]
    if report["decision"] == "ignored":
        return "No OpenVA command was found; take no bot action."
    return "Deny the command and require maintainer review before retrying."


def execute_command(comment: str, actor_role: str, *, queue_state_path: Path | None = None, context_kind: str = "comment_thread", contracts: dict[str, Any] | None = None) -> dict[str, Any]:
    contracts = contracts or load_contracts()
    parse_decision = build_decision(comment, actor_role, contracts=contracts)
    command_entry = command_entry_for(parse_decision, contracts)
    normalized_command = parse_decision.get("normalized_command")
    queue_report: dict[str, Any] | None = None
    failure_report: dict[str, Any] | None = None
    execution_result: dict[str, Any] | None = None
    reasons: list[str] = []
    decision = "denied"

    if parse_decision["decision"] == "ignored":
        decision = "ignored"
        reasons = ["no_openva_command"]
    elif parse_decision["decision"] == "denied":
        reasons = list(parse_decision["reasons"])
        failure_report = failure_routing_for(lane_id=parse_decision.get("lane_id"), message="chatops command denied before execution", failure_code="permission_policy_denial", queue_report=None)
    elif normalized_command not in EXECUTABLE_COMMANDS or not command_entry or not command_entry.get("executable"):
        decision = "report_only_not_executable"
        reasons = ["command_remains_report_only"]
    else:
        queue_report = queue_decision_for(command_entry, queue_state_path)
        if queue_report and queue_report.get("decision") != "allow":
            reasons = ["queue_decision_not_allow", *list(queue_report.get("reasons", []))]
            failure_report = failure_routing_for(lane_id=command_entry.get("lane_id"), message="chatops execution blocked by queue decision", queue_report=queue_report)
        else:
            decision = "executed"
            reasons = ["safe_command_executed"]
            execution_result = execution_payload(str(normalized_command), context_kind)

    report = {
        "version": 1,
        "report_type": "bot_chatops_execution",
        "raw_command_input": comment,
        "parsed_command_decision": parse_decision,
        "authorization_decision": {"actor_role": actor_role, "authorized": parse_decision.get("authorized") is True, "required_actor": "maintainer"},
        "queue_decision": queue_report,
        "failure_routing_report": failure_report,
        "execution_report": execution_result,
        "decision": decision,
        "executed": decision == "executed",
        "reasons": reasons,
        "audit_artifacts": ["raw command input", "parsed command decision", "authorization decision", *( ["queue decision"] if queue_report is not None else [] ), "execution report"],
    }
    report["next_safe_action"] = next_safe_action_for(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    execution = report.get("execution_report") or {}
    lines = [
        "# OpenVA Chat-Ops Execution Report", "", "## Decision", "",
        f"- Decision: `{report['decision']}`",
        f"- Executed: `{report['executed']}`",
        f"- Reasons: `{', '.join(report['reasons'])}`",
        f"- Next safe action: {report['next_safe_action']}", "", "## Command", "",
        f"- Normalized command: `{report['parsed_command_decision'].get('normalized_command')}`",
        f"- Actor role: `{report['authorization_decision']['actor_role']}`",
        f"- Authorized: `{report['authorization_decision']['authorized']}`", "",
    ]
    if report.get("queue_decision") is not None:
        queue = report["queue_decision"]
        lines.extend(["## Queue", "", f"- Lane: `{queue.get('lane_id')}`", f"- Decision: `{queue.get('decision')}`", f"- Reasons: `{', '.join(queue.get('reasons', []))}`", ""])
    if execution:
        lines.extend(["## Execution", "", f"- Side effect class: `{execution.get('side_effect_class')}`", f"- Mutates remote state: `{execution.get('mutates_remote_state')}`", f"- Mutates catalog: `{execution.get('mutates_catalog')}`", f"- Dispatches workflows: `{execution.get('dispatches_workflows')}`", ""])
        if execution.get("label_mutation"):
            label = execution["label_mutation"]
            lines.extend(["## Label Mutation", "", f"- Allowed label: `{label['allowed_label']}`", f"- Requested action: `{label['requested_action']}`", f"- Applied by local CLI: `{label['applied']}`", ""])
        if execution.get("markdown"):
            lines.extend(["## Generated Markdown", "", execution["markdown"]])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-chatops-execute")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("execute")
    run.add_argument("--comment-file", type=Path, required=True)
    run.add_argument("--actor-role", required=True)
    run.add_argument("--queue-state", type=Path, default=None)
    run.add_argument("--context-kind", default="comment_thread")
    run.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    run.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "execute":
        report = execute_command(args.comment_file.read_text(encoding="utf-8").strip(), args.actor_role, queue_state_path=args.queue_state, context_kind=args.context_kind)
        write_json(args.out, report)
        if args.out_md:
            write_text(args.out_md, render_markdown(report))
        print(json.dumps({"decision": report["decision"], "executed": report["executed"]}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
