from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from tools.openva import bot_chatops, bot_dashboard, bot_observability, bot_ops_smoke, workflow_retirement

ROOT = Path(__file__).resolve().parents[2]
BOT_CALIBRATION = Path("docs/operations/contracts/bot-calibration.yaml")


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


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return load_yaml(root / BOT_CALIBRATION)


def section(section_id: str, title: str, status: str, findings: list[str], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "status": status,
        "findings": findings,
        "evidence": evidence or {},
    }


def _subsystem(smoke: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in smoke.get("subsystems", []):
        if entry.get("name") == name:
            return entry
    return {"name": name, "status": "missing", "details": {}}


def _recommendations(
    smoke: dict[str, Any],
    scorecard: dict[str, Any],
    retirement_errors: list[str],
    hold_decision: dict[str, Any],
) -> list[str]:
    recommendations: set[str] = {"hold_current_authority"}
    if smoke.get("status") != "pass" or retirement_errors:
        recommendations.add("block_authority_expansion")
    if scorecard.get("completeness", {}).get("missing_input_count", 0):
        recommendations.add("tune_dashboard_signals")
    queue = _subsystem(smoke, "queue")
    if queue.get("status") != "pass":
        recommendations.add("tune_queue_policy")
    failure = _subsystem(smoke, "failure_router")
    if failure.get("status") != "pass":
        recommendations.add("tune_failure_taxonomy")
    if (
        smoke.get("status") == "pass"
        and not retirement_errors
        and hold_decision.get("decision") == "accepted_executable"
        and hold_decision.get("execution", {}).get("live_mutation") is False
    ):
        recommendations.add("allow_limited_label_activation")
    return sorted(recommendations)


def build_calibration(root: Path = ROOT, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract(root)
    smoke = bot_ops_smoke.run_smoke(root)
    dashboard_md = bot_dashboard.render_dashboard(root)
    observability_contract = bot_observability.load_contract(root)
    scorecard = bot_observability.build_scorecard(root, observability_contract)
    retirement_contracts = workflow_retirement.load_contracts(root)
    retirement_errors = workflow_retirement.validate_contracts(retirement_contracts)
    retirement_report = workflow_retirement.build_report(retirement_contracts)
    explain_decision = bot_chatops.build_decision("/openva explain-strict-growth", "maintainer")
    hold_decision = bot_chatops.build_decision("/openva hold", "maintainer")
    denied_decision = bot_chatops.build_decision("/openva retry-source-preflight", "viewer")

    smoke_by_name = {entry["name"]: entry for entry in smoke.get("subsystems", [])}
    missing_inputs = scorecard.get("missing_inputs", [])
    failed_subsystems = smoke.get("summary", {}).get("failed_subsystems", [])
    recommendations = _recommendations(smoke, scorecard, retirement_errors, hold_decision)

    sections = [
        section(
            "baseline_repo_posture",
            "Baseline repo posture",
            "pass" if smoke.get("status") == "pass" else "review_required",
            [
                f"Smoke harness status is `{smoke.get('status')}`.",
                "Calibration is local-only and report-only.",
            ],
            {
                "local_only": True,
                "report_only": True,
                "github_api_calls": False,
                "workflow_dispatch": False,
                "catalog_mutation": False,
            },
        ),
        section(
            "dashboard_usefulness_review",
            "Dashboard usefulness review",
            "watch" if missing_inputs else "pass",
            [
                "Dashboard renders successfully." if dashboard_md.startswith("# OpenVA Bot Dashboard") else "Dashboard heading was not detected.",
                "Missing optional local artifacts should be separated from actionable failures.",
            ],
            {"character_count": len(dashboard_md), "missing_input_count": len(missing_inputs)},
        ),
        section(
            "queue_decision_quality",
            "Queue decision quality",
            smoke_by_name.get("queue", {}).get("status", "missing"),
            [
                f"Clean sample decision: `{smoke_by_name.get('queue', {}).get('details', {}).get('clean_decision')}`.",
                f"Blocked sample decision: `{smoke_by_name.get('queue', {}).get('details', {}).get('blocked_decision')}`.",
            ],
            smoke_by_name.get("queue", {}).get("details", {}),
        ),
        section(
            "failure_router_classification_quality",
            "Failure-router classification quality",
            smoke_by_name.get("failure_router", {}).get("status", "missing"),
            [
                f"Smoke sample matched `{smoke_by_name.get('failure_router', {}).get('details', {}).get('matched_failure_code')}`.",
                "Unknown failures should remain conservative and require manual review.",
            ],
            smoke_by_name.get("failure_router", {}).get("details", {}),
        ),
        section(
            "chatops_safety_review",
            "Chat-ops safety review",
            "pass" if hold_decision.get("decision") == "accepted_executable" and denied_decision.get("decision") == "denied" else "review_required",
            [
                f"Explain command decision: `{explain_decision.get('decision')}`.",
                f"Hold command decision: `{hold_decision.get('decision')}`.",
                f"Unauthorized high-risk command decision: `{denied_decision.get('decision')}`.",
            ],
            {
                "explain": explain_decision,
                "hold": hold_decision,
                "denied": denied_decision,
            },
        ),
        section(
            "workflow_retirement_posture",
            "Workflow retirement posture",
            "pass" if not retirement_errors else "review_required",
            [
                f"Workflow retirement validation error count: `{len(retirement_errors)}`.",
                "Further retirement should remain evidence-gated.",
            ],
            {"errors": retirement_errors, "report_heading_present": retirement_report.startswith("# Workflow Retirement Report")},
        ),
        section(
            "observability_completeness",
            "Observability completeness",
            "watch" if missing_inputs else "pass",
            [
                f"Observed input completeness: `{scorecard['completeness']['present_input_count']}/{scorecard['completeness']['input_count']}`.",
                f"Missing input count: `{scorecard['completeness']['missing_input_count']}`.",
            ],
            scorecard.get("completeness", {}),
        ),
        section(
            "smoke_harness_coverage",
            "Smoke harness coverage",
            "pass" if not failed_subsystems else "review_required",
            [
                f"Subsystem count: `{smoke.get('summary', {}).get('subsystem_count')}`.",
                f"Failed subsystems: `{', '.join(failed_subsystems) if failed_subsystems else 'none'}`.",
            ],
            {"subsystems": sorted(smoke_by_name)},
        ),
        section(
            "missing_artifact_inventory",
            "Missing artifact inventory",
            "watch" if missing_inputs else "pass",
            [
                "Missing optional artifacts are calibration evidence, not automatic blockers.",
                f"Missing artifacts: `{len(missing_inputs)}`.",
            ],
            {"missing_inputs": missing_inputs},
        ),
        section(
            "noise_false_positive_inventory",
            "Noise / false-positive inventory",
            "watch" if missing_inputs else "pass",
            [
                "Optional local-report fallbacks should not be rendered as critical failures.",
                "Dashboard signal quality should be tuned before adding more live authority.",
            ],
            {"noise_sources": ["missing_optional_inputs"] if missing_inputs else []},
        ),
        section(
            "automation_authority_recommendation",
            "Automation authority recommendation",
            "review_required" if "block_authority_expansion" in recommendations else "watch",
            [f"Recommendations: `{', '.join(recommendations)}`."],
            {"recommendations": recommendations},
        ),
        section(
            "next_safe_action",
            "Next safe action",
            "watch",
            [next_safe_action(recommendations, missing_inputs)],
            {},
        ),
    ]

    required_ids = [entry["id"] for entry in contract.get("required_sections", [])]
    section_ids = [entry["id"] for entry in sections]
    missing_sections = [section_id for section_id in required_ids if section_id not in section_ids]
    if missing_sections:
        raise ValueError(f"calibration report missing sections: {missing_sections}")

    return {
        "version": 1,
        "report_type": "bot_ops_calibration",
        "local_only": True,
        "report_only": True,
        "github_api_calls": False,
        "workflow_dispatch": False,
        "catalog_mutation": False,
        "sections": sections,
        "recommendations": recommendations,
        "missing_inputs": missing_inputs,
        "failed_subsystems": failed_subsystems,
        "summary": {
            "section_count": len(sections),
            "missing_input_count": len(missing_inputs),
            "failed_subsystem_count": len(failed_subsystems),
            "retirement_error_count": len(retirement_errors),
        },
        "next_safe_action": next_safe_action(recommendations, missing_inputs),
    }


def next_safe_action(recommendations: list[str], missing_inputs: list[dict[str, Any]]) -> str:
    if "block_authority_expansion" in recommendations:
        return "Block authority expansion and resolve failed calibration evidence first."
    if missing_inputs:
        return "Tune dashboard signal quality so missing optional artifacts do not create false critical posture."
    if "allow_limited_label_activation" in recommendations:
        return "Proceed to a reviewed WP25 limited hold-label activation path; keep all higher-risk commands denied."
    return "Hold current bot authority and continue report-only evidence collection."


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Bot Ops Calibration Report",
        "",
        "This report is local-only and report-only. It does not call GitHub APIs, dispatch workflows, or mutate catalog data.",
        "",
        "## Summary",
        "",
        f"- Recommendations: `{', '.join(report['recommendations'])}`",
        f"- Missing inputs: `{report['summary']['missing_input_count']}`",
        f"- Failed subsystems: `{report['summary']['failed_subsystem_count']}`",
        f"- Retirement errors: `{report['summary']['retirement_error_count']}`",
        "",
    ]
    for entry in report["sections"]:
        lines.extend(
            [
                f"## {entry['title']}",
                "",
                f"- Status: `{entry['status']}`",
            ]
        )
        for finding in entry["findings"]:
            lines.append(f"- {finding}")
        lines.append("")
    lines.extend(["## Final Next Safe Action", "", f"- {report['next_safe_action']}", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-calibration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--out-json", type=Path, default=None)
    run_parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "run":
        contract = load_contract(ROOT)
        report = build_calibration(ROOT, contract)
        out_json = args.out_json or Path(str(contract["outputs"]["json"]))
        out_md = args.out_md or Path(str(contract["outputs"]["markdown"]))
        out_json = out_json if out_json.is_absolute() else ROOT / out_json
        out_md = out_md if out_md.is_absolute() else ROOT / out_md
        write_json(out_json, report)
        write_text(out_md, render_markdown(report))
        print(json.dumps({"report_type": report["report_type"], "recommendations": report["recommendations"]}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
