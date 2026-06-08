from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva import bot_chatops, bot_dashboard, bot_dashboard_issue, bot_failure_router, bot_observability, bot_queue
from tools.openva import workflow_retirement

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = Path("maintenance/bot-ops-smoke-report.json")
DEFAULT_MD = Path("maintenance/bot-ops-smoke-report.md")
NOW = datetime(2026, 6, 8, 0, 0, tzinfo=UTC)

REQUIRED_CONTRACTS = [
    Path("docs/operations/contracts/bot-authority.yaml"),
    Path("docs/operations/contracts/bot-queue-policy.yaml"),
    Path("docs/operations/contracts/bot-failure-taxonomy.yaml"),
    Path("docs/operations/contracts/bot-dashboard.yaml"),
    Path("docs/operations/contracts/bot-chatops.yaml"),
    Path("docs/operations/contracts/bot-dashboard-issue.yaml"),
    Path("docs/operations/contracts/workflow-retirement.yaml"),
    Path("docs/operations/contracts/bot-observability.yaml"),
    Path("docs/operations/contracts/workflow-inventory.yaml"),
]


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def clean_queue_state() -> dict[str, Any]:
    return {
        "version": 1,
        "lane_id": "catalog_growth_promotion",
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "evidence": {"generated_at": "2026-06-07T23:00:00Z"},
        "pause": {"active": False},
        "requested_action": {
            "duplicate_key": "wp17-smoke-clean",
            "vendor_domain": "example.com",
            "source_host": "example.com",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
        },
    }


def blocked_queue_state() -> dict[str, Any]:
    state = clean_queue_state()
    state["open_prs"] = [
        {
            "number": 1701,
            "title": "Catalog growth promotion",
            "lane_id": "catalog_growth_promotion",
            "created_at": "2026-06-07T00:00:00Z",
            "duplicate_key": "wp17-smoke-clean",
        }
    ]
    return state


def subsystem(name: str, status: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "status": status, "details": details}


def validate_contracts(root: Path = ROOT) -> dict[str, Any]:
    parsed: list[str] = []
    for rel_path in REQUIRED_CONTRACTS:
        path = root / rel_path
        if not path.exists():
            raise FileNotFoundError(f"required contract missing: {rel_path}")
        load_yaml(path)
        parsed.append(rel_path.as_posix())
    return {"parsed_contracts": parsed, "contract_count": len(parsed)}


def run_smoke(root: Path = ROOT) -> dict[str, Any]:
    subsystems: list[dict[str, Any]] = []

    contract_result = validate_contracts(root)
    subsystems.append(subsystem("contracts", "pass", contract_result))

    dashboard_md = bot_dashboard.render_dashboard(root)
    subsystems.append(
        subsystem(
            "dashboard",
            "pass",
            {
                "rendered": True,
                "heading_present": dashboard_md.startswith("# OpenVA Bot Dashboard"),
                "character_count": len(dashboard_md),
            },
        )
    )

    clean_queue = bot_queue.evaluate("catalog_growth_promotion", clean_queue_state(), now=NOW)
    blocked_queue = bot_queue.evaluate("catalog_growth_promotion", blocked_queue_state(), now=NOW)
    queue_status = "pass" if clean_queue["decision"] == "allow" and blocked_queue["decision"] in {"defer", "deny"} else "fail"
    subsystems.append(
        subsystem(
            "queue",
            queue_status,
            {
                "clean_decision": clean_queue["decision"],
                "clean_reasons": clean_queue["reasons"],
                "blocked_decision": blocked_queue["decision"],
                "blocked_reasons": blocked_queue["reasons"],
            },
        )
    )

    failure = bot_failure_router.route_failure(
        {
            "version": 1,
            "lane_id": "catalog_growth_promotion",
            "failure": {
                "code": "stale_evidence_failure",
                "message": "Evidence is older than strict-growth stale evidence limit.",
                "artifact": "promotion-plan.json",
            },
        }
    )
    subsystems.append(
        subsystem(
            "failure_router",
            "pass" if failure["matched_failure_code"] == "stale_evidence_failure" else "fail",
            {
                "matched_failure_code": failure["matched_failure_code"],
                "classification": failure["classification"],
                "next_safe_action": failure["next_safe_action"],
            },
        )
    )

    allowed_chatops = bot_chatops.build_decision("/openva explain-strict-growth", "maintainer")
    denied_chatops = bot_chatops.build_decision("/openva frobnicate", "maintainer")
    chatops_status = (
        "pass"
        if allowed_chatops["decision"] == "accepted_executable"
        and allowed_chatops["executable"] is True
        and denied_chatops["decision"] == "denied"
        else "fail"
    )
    subsystems.append(
        subsystem(
            "chatops",
            chatops_status,
            {
                "allowed_decision": allowed_chatops["decision"],
                "allowed_report_only": allowed_chatops["report_only"],
                "allowed_executable": allowed_chatops["executable"],
                "denied_decision": denied_chatops["decision"],
                "denied_reasons": denied_chatops["reasons"],
            },
        )
    )

    dashboard_issue = bot_dashboard_issue.sync_dashboard_issue(
        repo="thedanieltan/open-vendor-assurance",
        dashboard_path=Path("maintenance/bot-dashboard.md"),
        dry_run=True,
        report_only=True,
    )
    issue_status = "pass" if dashboard_issue["dry_run"] is True and dashboard_issue["report_only"] is True else "fail"
    subsystems.append(
        subsystem(
            "dashboard_issue_sync",
            issue_status,
            {
                "decision": dashboard_issue["decision"],
                "dry_run": dashboard_issue["dry_run"],
                "report_only": dashboard_issue["report_only"],
                "duplicate_issue_status": dashboard_issue["duplicate_issue_status"],
            },
        )
    )

    retirement_contracts = workflow_retirement.load_contracts(root)
    retirement_errors = workflow_retirement.validate_contracts(retirement_contracts)
    retirement_report = workflow_retirement.build_report(retirement_contracts)
    subsystems.append(
        subsystem(
            "workflow_retirement",
            "pass" if not retirement_errors else "fail",
            {
                "error_count": len(retirement_errors),
                "report_heading_present": retirement_report.startswith("# Workflow Retirement Report"),
            },
        )
    )

    observability_contract = bot_observability.load_contract(root)
    scorecard = bot_observability.build_scorecard(root, observability_contract)
    subsystems.append(
        subsystem(
            "observability",
            "pass" if scorecard["report_type"] == "bot_observability_scorecard" else "fail",
            {
                "report_type": scorecard["report_type"],
                "missing_input_count": scorecard["completeness"]["missing_input_count"],
                "next_safe_action": scorecard["next_safe_action"],
            },
        )
    )

    failed = [entry["name"] for entry in subsystems if entry["status"] != "pass"]
    next_action = (
        "Resolve failed smoke subsystems before enabling new bot capabilities."
        if failed
        else "Smoke harness passed locally; keep bot actions report-only until a reviewed authority PR enables stronger behavior."
    )

    return {
        "version": 1,
        "report_type": "bot_ops_smoke",
        "status": "pass" if not failed else "fail",
        "subsystems": subsystems,
        "summary": {
            "subsystem_count": len(subsystems),
            "failed_subsystems": failed,
            "local_only": True,
            "report_only": True,
            "github_api_calls": False,
            "workflow_dispatch": False,
            "catalog_mutation": False,
        },
        "next_safe_action": next_action,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Bot Ops Smoke Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Local only: `{report['summary']['local_only']}`",
        f"- Report only: `{report['summary']['report_only']}`",
        f"- GitHub API calls: `{report['summary']['github_api_calls']}`",
        f"- Workflow dispatch: `{report['summary']['workflow_dispatch']}`",
        f"- Catalog mutation: `{report['summary']['catalog_mutation']}`",
        "",
        "## Subsystems",
        "",
        "| Subsystem | Status | Key result |",
        "|---|---|---|",
    ]
    for entry in report["subsystems"]:
        details = entry["details"]
        key_result = (
            details.get("clean_decision")
            or details.get("matched_failure_code")
            or details.get("allowed_decision")
            or details.get("decision")
            or details.get("report_type")
            or details.get("contract_count")
            or details.get("character_count")
            or details.get("error_count")
        )
        lines.append(f"| `{entry['name']}` | `{entry['status']}` | `{key_result}` |")
    lines.extend(
        [
            "",
            "## Queue Samples",
            "",
        ]
    )
    queue = next(entry for entry in report["subsystems"] if entry["name"] == "queue")["details"]
    lines.extend(
        [
            f"- Clean sample decision: `{queue['clean_decision']}`",
            f"- Blocked sample decision: `{queue['blocked_decision']}`",
            "",
            "## Chat-Ops Samples",
            "",
        ]
    )
    chatops = next(entry for entry in report["subsystems"] if entry["name"] == "chatops")["details"]
    lines.extend(
        [
            f"- Allowed command decision: `{chatops['allowed_decision']}`",
            f"- Allowed command report-only: `{chatops['allowed_report_only']}`",
            f"- Allowed command executable: `{chatops['allowed_executable']}`",
            f"- Denied command decision: `{chatops['denied_decision']}`",
            "",
            "## Next Safe Action",
            "",
            f"- {report['next_safe_action']}",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-ops-smoke")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--out-json", type=Path, default=ROOT / DEFAULT_JSON)
    run_parser.add_argument("--out-md", type=Path, default=ROOT / DEFAULT_MD)
    args = parser.parse_args(argv)

    if args.command == "run":
        report = run_smoke(ROOT)
        out_json = args.out_json if args.out_json.is_absolute() else ROOT / args.out_json
        out_md = args.out_md if args.out_md.is_absolute() else ROOT / args.out_md
        write_json(out_json, report)
        write_text(out_md, render_markdown(report))
        print(json.dumps({"status": report["status"], "subsystem_count": report["summary"]["subsystem_count"]}, sort_keys=True))
        return 0 if report["status"] == "pass" else 1
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
