from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT_OBSERVABILITY = Path("docs/operations/contracts/bot-observability.yaml")

METRIC_NAMES = [
    "bot_prs_opened",
    "bot_prs_merged",
    "bot_prs_failed_before_creation",
    "bot_prs_closed",
    "human_interventions_per_pr",
    "average_time_to_merge",
    "failure_reasons_by_class",
    "candidate_conversion_rate",
    "source_preflight_failure_rate",
    "redirect_canonicalization_rate",
    "deferred_backlog_age",
    "review_backlog_age",
    "queue_denials_by_lane",
    "queue_deferrals_by_lane",
    "stale_evidence_denials",
    "chatops_command_decisions_by_status",
]


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return load_yaml(root / BOT_OBSERVABILITY)


def repo_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def as_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("reports"), list):
            return [item for item in data["reports"] if isinstance(item, dict)]
        if isinstance(data.get("items"), list) and data.get("report_type"):
            return [item for item in data["items"] if isinstance(item, dict)]
        return [data]
    return []


def load_input_records(root: Path, contract: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    inputs: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for input_def in contract.get("input_reports", []):
        input_id = str(input_def["id"])
        report_type = str(input_def["report_type"])
        for rel_path in input_def.get("paths", []):
            path = repo_path(root, rel_path)
            exists = path.exists()
            input_record = {
                "id": input_id,
                "report_type": report_type,
                "path": str(rel_path),
                "required": bool(input_def.get("required", False)),
                "exists": exists,
                "record_count": 0,
                "error": None,
            }
            if not exists:
                missing.append(
                    {
                        "id": input_id,
                        "report_type": report_type,
                        "path": str(rel_path),
                        "required": bool(input_def.get("required", False)),
                    }
                )
            elif path.suffix == ".json":
                try:
                    records = as_records(load_json(path))
                    input_record["record_count"] = len(records)
                    records_by_type.setdefault(report_type, []).extend(records)
                except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    input_record["error"] = str(exc)
                    missing.append(
                        {
                            "id": input_id,
                            "report_type": report_type,
                            "path": str(rel_path),
                            "required": bool(input_def.get("required", False)),
                            "error": str(exc),
                        }
                    )
            else:
                input_record["record_count"] = 1
                records_by_type.setdefault(report_type, []).append(
                    {"report_type": report_type, "path": str(rel_path), "content_length": path.stat().st_size}
                )
            inputs.append(input_record)
    return records_by_type, inputs, missing


def metric(value: Any, confidence: str, completeness: float, sources: list[str]) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence,
        "completeness": round(completeness, 3),
        "sources": sorted(set(sources)),
    }


def metric_from_count(value: int, sources: list[str]) -> dict[str, Any]:
    return metric(value, "observed" if sources else "missing", 1.0 if sources else 0.0, sources)


def rate(numerator: int, denominator: int, sources: list[str]) -> dict[str, Any]:
    if denominator == 0:
        return metric(None, "missing", 0.0, sources)
    return metric(round(numerator / denominator, 6), "observed", 1.0, sources)


def queue_reports(records_by_type: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return records_by_type.get("bot_queue_decision", [])


def failure_reports(records_by_type: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return records_by_type.get("bot_failure_routing", [])


def chatops_reports(records_by_type: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return records_by_type.get("bot_chatops_decision", [])


def build_scorecard(root: Path = ROOT, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract(root)
    records_by_type, inputs, missing_inputs = load_input_records(root, contract)
    queue = queue_reports(records_by_type)
    failures = failure_reports(records_by_type)
    chatops = chatops_reports(records_by_type)

    queue_sources = ["bot_queue_reports"] if queue else []
    failure_sources = ["bot_failure_routing_reports"] if failures else []
    chatops_sources = ["bot_chatops_decision_reports"] if chatops else []

    queue_denials = Counter(str(report.get("lane_id") or "unknown") for report in queue if report.get("decision") == "deny")
    queue_deferrals = Counter(str(report.get("lane_id") or "unknown") for report in queue if report.get("decision") == "defer")
    stale_evidence_denials = 0
    for report in queue:
        reasons = {str(reason) for reason in report.get("reasons", []) or []}
        stale = report.get("stale_evidence") if isinstance(report.get("stale_evidence"), dict) else {}
        if report.get("decision") in {"deny", "defer"} and (
            reasons & {"stale_evidence", "missing_evidence"} or stale.get("stale") is True or stale.get("missing") is True
        ):
            stale_evidence_denials += 1

    failure_codes = Counter(
        str(report.get("matched_failure_code") or "manual_review_required")
        for report in failures
        if report.get("classification") in {"taxonomy_match", "manual_review_required"} or report.get("matched_failure_code")
    )
    failed_before_creation = sum(1 for report in queue if report.get("decision") == "deny") + sum(
        1 for report in failures if report.get("stop_lane") is True
    )
    total_classified_failures = sum(failure_codes.values())

    chatops_decisions = Counter(str(report.get("decision") or "unknown") for report in chatops)

    metrics = {
        "bot_prs_opened": metric(None, "not_available_without_github_api", 0.0, []),
        "bot_prs_merged": metric(None, "not_available_without_github_api", 0.0, []),
        "bot_prs_failed_before_creation": metric_from_count(failed_before_creation, queue_sources + failure_sources),
        "bot_prs_closed": metric(None, "not_available_without_github_api", 0.0, []),
        "human_interventions_per_pr": metric(None, "not_available_without_github_api", 0.0, []),
        "average_time_to_merge": metric(None, "not_available_without_github_api", 0.0, []),
        "failure_reasons_by_class": metric(dict(sorted(failure_codes.items())), "observed" if failures else "missing", 1.0 if failures else 0.0, failure_sources),
        "candidate_conversion_rate": metric(None, "missing_candidate_history", 0.0, []),
        "source_preflight_failure_rate": rate(failure_codes.get("source_preflight_failure", 0), total_classified_failures, failure_sources),
        "redirect_canonicalization_rate": rate(failure_codes.get("redirect_canonicalization_failure", 0), total_classified_failures, failure_sources),
        "deferred_backlog_age": metric(None, "missing_backlog_age_data", 0.0, []),
        "review_backlog_age": metric(None, "missing_backlog_age_data", 0.0, []),
        "queue_denials_by_lane": metric(dict(sorted(queue_denials.items())), "observed" if queue else "missing", 1.0 if queue else 0.0, queue_sources),
        "queue_deferrals_by_lane": metric(dict(sorted(queue_deferrals.items())), "observed" if queue else "missing", 1.0 if queue else 0.0, queue_sources),
        "stale_evidence_denials": metric_from_count(stale_evidence_denials, queue_sources),
        "chatops_command_decisions_by_status": metric(dict(sorted(chatops_decisions.items())), "observed" if chatops else "missing", 1.0 if chatops else 0.0, chatops_sources),
    }

    present_inputs = [item for item in inputs if item["exists"] and not item["error"]]
    completeness = {
        "input_count": len(inputs),
        "present_input_count": len(present_inputs),
        "missing_input_count": len(missing_inputs),
        "ratio": round(len(present_inputs) / len(inputs), 3) if inputs else 1.0,
    }

    return {
        "version": 1,
        "report_type": "bot_observability_scorecard",
        "metrics": {name: metrics[name] for name in METRIC_NAMES},
        "groups": {
            "failure_reasons_by_class": dict(sorted(failure_codes.items())),
            "queue_denials_by_lane": dict(sorted(queue_denials.items())),
            "queue_deferrals_by_lane": dict(sorted(queue_deferrals.items())),
            "chatops_command_decisions_by_status": dict(sorted(chatops_decisions.items())),
        },
        "inputs": inputs,
        "missing_inputs": missing_inputs,
        "completeness": completeness,
        "next_safe_action": next_safe_action(completeness, metrics),
    }


def next_safe_action(completeness: dict[str, Any], metrics: dict[str, dict[str, Any]]) -> str:
    if completeness["missing_input_count"]:
        return "Regenerate missing local bot reports before using the scorecard for throttling changes."
    if metrics["queue_denials_by_lane"]["value"]:
        return "Review queue denials by lane before enabling additional write-capable bot actions."
    if metrics["stale_evidence_denials"]["value"]:
        return "Refresh stale evidence before controlled promotion, source repair, or merge decisions."
    return "Use the scorecard as report-only bot-ops evidence; do not change automation without a reviewed contract PR."


def markdown_table_row(values: list[Any]) -> str:
    return "| " + " | ".join("" if value is None else str(value).replace("|", "\\|") for value in values) + " |"


def render_markdown(scorecard: dict[str, Any], contract: dict[str, Any] | None = None) -> str:
    metrics = scorecard["metrics"]
    lines = [
        "# OpenVA Bot Observability Scorecard",
        "",
        "Generated from local bot reports only. This scorecard is report-only and does not call GitHub APIs.",
        "",
        "## Summary",
        "",
        f"- Report type: `{scorecard['report_type']}`",
        f"- Input completeness: `{scorecard['completeness']['present_input_count']}/{scorecard['completeness']['input_count']}`",
        f"- Missing inputs: `{scorecard['completeness']['missing_input_count']}`",
        "",
        "## Metric Completeness",
        "",
        "| Metric | Confidence | Completeness | Sources |",
        "|---|---|---:|---|",
    ]
    for name in METRIC_NAMES:
        entry = metrics[name]
        sources = ", ".join(entry["sources"]) if entry["sources"] else ""
        lines.append(markdown_table_row([f"`{name}`", entry["confidence"], entry["completeness"], sources]))

    lines.extend(
        [
            "",
            "## PR Lifecycle Metrics",
            "",
            f"- Bot PRs opened: `{metrics['bot_prs_opened']['value']}`",
            f"- Bot PRs merged: `{metrics['bot_prs_merged']['value']}`",
            f"- Bot PRs failed before creation: `{metrics['bot_prs_failed_before_creation']['value']}`",
            f"- Bot PRs closed: `{metrics['bot_prs_closed']['value']}`",
            f"- Human interventions per PR: `{metrics['human_interventions_per_pr']['value']}`",
            f"- Average time to merge: `{metrics['average_time_to_merge']['value']}` hours",
            "",
            "## Queue Metrics",
            "",
            f"- Queue denials by lane: `{json.dumps(metrics['queue_denials_by_lane']['value'], sort_keys=True)}`",
            f"- Queue deferrals by lane: `{json.dumps(metrics['queue_deferrals_by_lane']['value'], sort_keys=True)}`",
            f"- Stale evidence denials: `{metrics['stale_evidence_denials']['value']}`",
            "",
            "## Failure Metrics",
            "",
            f"- Failure reasons by class: `{json.dumps(metrics['failure_reasons_by_class']['value'], sort_keys=True)}`",
            f"- Source preflight failure rate: `{metrics['source_preflight_failure_rate']['value']}`",
            f"- Redirect canonicalization rate: `{metrics['redirect_canonicalization_rate']['value']}`",
            "",
            "## Chat-Ops Metrics",
            "",
            f"- Chat-ops command decisions by status: `{json.dumps(metrics['chatops_command_decisions_by_status']['value'], sort_keys=True)}`",
            "",
            "## Missing Inputs",
            "",
        ]
    )
    if scorecard["missing_inputs"]:
        lines.extend(["| Input | Report type | Path | Required |", "|---|---|---|---|"])
        for item in scorecard["missing_inputs"]:
            lines.append(markdown_table_row([item["id"], item["report_type"], f"`{item['path']}`", item["required"]]))
    else:
        lines.append("- No configured inputs are missing.")
    lines.extend(["", "## Next Safe Action", "", f"- {scorecard['next_safe_action']}", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-observability")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--out-json", type=Path, default=None)
    build_parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "build":
        contract = load_contract()
        scorecard = build_scorecard(ROOT, contract)
        out_json = args.out_json or Path(str(contract["outputs"]["json"]))
        out_md = args.out_md or Path(str(contract["outputs"]["markdown"]))
        out_json = out_json if out_json.is_absolute() else ROOT / out_json
        out_md = out_md if out_md.is_absolute() else ROOT / out_md
        write_json(out_json, scorecard)
        write_text(out_md, render_markdown(scorecard, contract))
        print(json.dumps({"report_type": scorecard["report_type"], "missing_inputs": scorecard["completeness"]["missing_input_count"]}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
