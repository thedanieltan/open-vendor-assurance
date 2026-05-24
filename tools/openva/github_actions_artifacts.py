from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1.0"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_id(run: dict[str, Any]) -> str:
    value = run.get("databaseId") or run.get("id") or run.get("run_id")
    return "" if value is None else str(value)


def is_successful_completed_run(run: dict[str, Any]) -> bool:
    return str(run.get("status") or "") == "completed" and str(run.get("conclusion") or "") == "success"


def sort_key(run: dict[str, Any]) -> tuple[str, int]:
    created_at = str(run.get("createdAt") or run.get("created_at") or "")
    try:
        numeric_id = int(run_id(run))
    except ValueError:
        numeric_id = 0
    return (created_at, numeric_id)


def compact_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run_id(run),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("createdAt") or run.get("created_at"),
        "updated_at": run.get("updatedAt") or run.get("updated_at"),
        "workflow_name": run.get("workflowName") or run.get("workflow_name"),
        "event": run.get("event"),
        "head_branch": run.get("headBranch") or run.get("head_branch"),
    }


def select_latest_two_successful_runs(
    runs: list[dict[str, Any]],
    *,
    workflow: str = "source-maintenance-report.yml",
    generated_at: str | None = None,
) -> dict[str, Any]:
    successful = [run for run in runs if is_successful_completed_run(run) and run_id(run)]
    successful.sort(key=sort_key, reverse=True)
    selected = successful[:2]
    status = "selected" if len(selected) == 2 else "insufficient_history"
    fresh = compact_run(selected[0]) if len(selected) >= 1 else None
    prior = compact_run(selected[1]) if len(selected) >= 2 else None
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": "source_maintenance_run_selection",
        "status": status,
        "workflow": workflow,
        "reason": None if status == "selected" else "fewer_than_two_successful_completed_source_maintenance_runs",
        "prior_run_id": prior["run_id"] if prior else None,
        "fresh_run_id": fresh["run_id"] if fresh else None,
        "selected_runs": {
            "prior": prior,
            "fresh": fresh,
        },
        "summary": {
            "input_run_count": len(runs),
            "successful_completed_run_count": len(successful),
            "selected_run_count": len(selected),
        },
    }


def write_github_output(selection: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    has_history = "true" if selection["status"] == "selected" else "false"
    lines = [
        f"has_history={has_history}",
        f"prior_run_id={selection.get('prior_run_id') or ''}",
        f"fresh_run_id={selection.get('fresh_run_id') or ''}",
    ]
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def write_github_env(selection: dict[str, Any], env_path: Path | None) -> None:
    if env_path is None:
        return
    has_history = "true" if selection["status"] == "selected" else "false"
    lines = [
        f"SOURCE_REFINEMENT_HAS_HISTORY={has_history}",
        f"PRIOR_RUN_ID={selection.get('prior_run_id') or ''}",
        f"FRESH_RUN_ID={selection.get('fresh_run_id') or ''}",
    ]
    with env_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def skipped_confirmed_p0_scan(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "report_type": "confirmed_p0_source_refinement_scan",
        "status": "skipped",
        "reason": selection.get("reason") or "insufficient_source_maintenance_history",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "non_advisory": True,
        },
        "prior_report_run_id": selection.get("prior_run_id"),
        "fresh_report_run_id": selection.get("fresh_run_id"),
        "prior_report_generated_at": None,
        "fresh_report_generated_at": None,
        "confirmed_p0": [],
        "inconclusive": [],
        "excluded": [],
        "unknown_statuses": [],
        "summary": {
            "prior_source_count": 0,
            "fresh_source_count": 0,
            "confirmed_p0_count": 0,
            "inconclusive_count": 0,
            "excluded_count": 0,
            "unknown_status_count": 0,
            "prior_statuses": {},
            "fresh_statuses": {},
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-github-actions-artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select-latest-source-maintenance-runs")
    select.add_argument("--runs-json", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("--github-output", type=Path)
    select.add_argument("--github-env", type=Path)

    skipped = subparsers.add_parser("write-skipped-source-refinement-scan")
    skipped.add_argument("--selection-report", type=Path, required=True)
    skipped.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "select-latest-source-maintenance-runs":
        runs = load_json(args.runs_json)
        if not isinstance(runs, list):
            raise ValueError(f"{args.runs_json}: expected JSON array")
        if not all(isinstance(run, dict) for run in runs):
            raise ValueError(f"{args.runs_json}: expected each run to be an object")
        selection = select_latest_two_successful_runs(runs)
        write_json(selection, args.output)
        write_github_output(selection, args.github_output)
        write_github_env(selection, args.github_env)
        print(json.dumps(selection["summary"], indent=2, sort_keys=True))
        return 0
    if args.command == "write-skipped-source-refinement-scan":
        selection = load_json(args.selection_report)
        if not isinstance(selection, dict):
            raise ValueError(f"{args.selection_report}: expected JSON object")
        scan = skipped_confirmed_p0_scan(selection)
        write_json(scan, args.output)
        print(json.dumps(scan["summary"], indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
