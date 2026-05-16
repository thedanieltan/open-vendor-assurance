from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION
from tools.openva.source_verification import ROOT, display_path

DEFAULT_MAX_ACTIONS = 50


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def candidate_actions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    actions = plan.get("actions", []) or []
    if not isinstance(actions, list):
        raise ValueError("promotion plan actions must be a list")
    return [action for action in actions if action.get("action") == REVIEWED_CANDIDATE_PROMOTION_ACTION]


def split_actions(actions: list[dict[str, Any]], max_actions: int) -> list[list[dict[str, Any]]]:
    if max_actions <= 0:
        raise ValueError("max_actions must be positive")
    return [actions[index : index + max_actions] for index in range(0, len(actions), max_actions)]


def batch_plan(actions: list[dict[str, Any]], source_plan_path: str, index: int) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "candidate_promotion_plan_proposal",
        "source_plan_path": source_plan_path,
        "batch_index": index,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "action_count": len(actions),
            "action_types": {REVIEWED_CANDIDATE_PROMOTION_ACTION: len(actions)},
        },
        "actions": actions,
    }


def build_batches(plan: dict[str, Any], source_plan_path: str, max_actions: int = DEFAULT_MAX_ACTIONS) -> list[dict[str, Any]]:
    return [
        batch_plan(actions, source_plan_path, index + 1)
        for index, actions in enumerate(split_actions(candidate_actions(plan), max_actions))
    ]


def write_batches(batches: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for batch in batches:
        path = output_dir / f"candidate-promotion-plan-{batch['batch_index']:03d}.json"
        path.write_text(json.dumps(batch, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def summary(paths: list[Path], batches: list[dict[str, Any]], root: Path = ROOT) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "promotion_plan_batch_summary",
        "summary": {
            "batch_count": len(batches),
            "candidate_promotion_actions": sum(batch["summary"]["action_count"] for batch in batches),
            "batch_paths": [display_path(path, root) for path in paths],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-promotion-plan-batcher")
    parser.add_argument("command", choices={"batch"})
    parser.add_argument("--promotion-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "maintenance" / "generated")
    parser.add_argument("--summary-output", type=Path, default=ROOT / "promotion-plan-batch-summary.json")
    parser.add_argument("--max-actions", type=int, default=DEFAULT_MAX_ACTIONS)
    args = parser.parse_args()

    batches = build_batches(load_json(args.promotion_plan), display_path(args.promotion_plan), args.max_actions)
    paths = write_batches(batches, args.output_dir)
    report = summary(paths, batches)
    args.summary_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
