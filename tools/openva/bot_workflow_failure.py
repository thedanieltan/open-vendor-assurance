from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load_json_if_present(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_preflight_failed(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    if int(report.get("failed_count", 0) or 0) > 0:
        return True
    failures = report.get("failures")
    return isinstance(failures, list) and bool(failures)


def queue_needs_routing(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    decision = report.get("decision")
    reasons = set(report.get("reasons", []) or [])
    return decision in {"deny", "pause", "defer"} and reasons != {"queue_policy_satisfied"}


def build_observation(
    *,
    workflow: str,
    lane_id: str,
    message: str,
    artifact: str | None = None,
    failure_code: str | None = None,
    queue_report: dict[str, Any] | None = None,
    source_preflight_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inferred_code = failure_code
    inferred_message = message
    inferred_artifact = artifact
    if source_preflight_failed(source_preflight_report):
        inferred_code = "source_preflight_failure"
        inferred_message = "source preflight failed for changed source records"
        inferred_artifact = inferred_artifact or "source-preflight-report.json"

    observation: dict[str, Any] = {
        "version": 1,
        "workflow": workflow,
        "lane_id": lane_id,
        "failure": {
            "message": inferred_message,
        },
        "context": {
            "event_name": os.environ.get("GITHUB_EVENT_NAME"),
            "job": os.environ.get("GITHUB_JOB"),
            "ref": os.environ.get("GITHUB_REF"),
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "sha": os.environ.get("GITHUB_SHA"),
            "workflow": workflow,
        },
    }
    if inferred_code:
        observation["failure"]["code"] = inferred_code
    if inferred_artifact:
        observation["failure"]["artifact"] = inferred_artifact
    if queue_needs_routing(queue_report):
        observation["queue_report"] = {
            "decision": queue_report.get("decision"),
            "reasons": queue_report.get("reasons", []),
            "violated_policies": queue_report.get("violated_policies", []),
            "next_safe_action": queue_report.get("next_safe_action"),
        }
    if source_preflight_report:
        observation["source_preflight_report"] = {
            "failed_count": source_preflight_report.get("failed_count"),
            "checked_count": source_preflight_report.get("checked_count"),
        }
    return observation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-workflow-failure")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--workflow", required=True)
    build_parser.add_argument("--lane", required=True)
    build_parser.add_argument("--message", required=True)
    build_parser.add_argument("--artifact")
    build_parser.add_argument("--failure-code")
    build_parser.add_argument("--queue-report", type=Path)
    build_parser.add_argument("--source-preflight-report", type=Path)
    build_parser.add_argument("--out", type=Path, required=True)
    build_parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help="Leave an existing targeted failure input unchanged.",
    )
    args = parser.parse_args(argv)

    if args.command == "build":
        output = args.out if args.out.is_absolute() else ROOT / args.out
        if args.preserve_existing and output.exists():
            print(json.dumps({"failure_input": str(output), "preserved": True}, sort_keys=True))
            return 0
        observation = build_observation(
            workflow=args.workflow,
            lane_id=args.lane,
            message=args.message,
            artifact=args.artifact,
            failure_code=args.failure_code,
            queue_report=load_json_if_present(args.queue_report),
            source_preflight_report=load_json_if_present(args.source_preflight_report),
        )
        write_json(output, observation)
        print(json.dumps({"failure_input": str(output), "preserved": False}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
