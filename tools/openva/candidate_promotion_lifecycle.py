from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION, resolve_max_promotion_actions_per_pr
from tools.openva.source_verification import ROOT, display_path

APPLIED_PLANS = ROOT / "maintenance" / "applied" / "applied-plans.json"
DEFAULT_MAX_PROMOTION_ACTIONS_PER_PR = 50
DEFAULT_MAX_ACTIONS_PER_PLAN = DEFAULT_MAX_PROMOTION_ACTIONS_PER_PR


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def plan_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reviewed_plan_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "maintenance" / "reviewed").glob("*.json"))


def applied_entries(root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / "maintenance" / "applied" / "applied-plans.json"
    if not path.exists():
        return []
    data = load_json(path)
    return [item for item in data.get("plans", []) or [] if isinstance(item, dict)]


def applied_keys(root: Path = ROOT) -> tuple[set[str], set[str], set[str]]:
    paths: set[str] = set()
    names: set[str] = set()
    digests: set[str] = set()
    for entry in applied_entries(root):
        if entry.get("status") != "applied":
            continue
        if entry.get("plan_path"):
            paths.add(str(entry["plan_path"]))
        if entry.get("plan_name"):
            names.add(str(entry["plan_name"]))
        if entry.get("plan_sha256"):
            digests.add(str(entry["plan_sha256"]))
    return paths, names, digests


def is_applied(path: Path, root: Path = ROOT) -> bool:
    relative = display_path(path, root)
    paths, names, digests = applied_keys(root)
    return relative in paths or path.name in names or (path.exists() and plan_sha256(path) in digests)


def assert_reviewed_path(path: Path, root: Path = ROOT) -> None:
    try:
        path.resolve().relative_to((root / "maintenance" / "reviewed").resolve())
    except ValueError as exc:
        raise ValueError("promotion_plan_path must be under maintenance/reviewed/ and end with .json") from exc
    if path.suffix != ".json":
        raise ValueError("promotion_plan_path must be under maintenance/reviewed/ and end with .json")
    if not path.exists():
        raise ValueError(f"promotion plan file not found: {display_path(path, root)}")


def validate_candidate_promotion_plan(
    path: Path,
    root: Path = ROOT,
    max_actions: int | None = DEFAULT_MAX_PROMOTION_ACTIONS_PER_PR,
) -> dict[str, Any]:
    assert_reviewed_path(path, root)
    plan = load_json(path)
    posture = plan.get("posture", {}) or {}
    expected = {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }
    for key, value in expected.items():
        if posture.get(key) is not value:
            raise ValueError(f"{display_path(path, root)}: posture.{key} must be {value!r}")
    actions = plan.get("actions", []) or []
    if not isinstance(actions, list):
        raise ValueError(f"{display_path(path, root)}: actions must be a list")
    if max_actions is not None and len(actions) > max_actions:
        raise ValueError(f"{display_path(path, root)}: reviewed plan exceeds max_promotion_actions_per_pr={max_actions}")
    if not actions:
        raise ValueError(f"{display_path(path, root)}: candidate promotion plan must contain actions")
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"{display_path(path, root)}: action {index} must be an object")
        if action.get("action") != REVIEWED_CANDIDATE_PROMOTION_ACTION:
            raise ValueError(f"{display_path(path, root)}: action {index} is not a candidate promotion action")
        if action.get("requires_human_review") is not True:
            raise ValueError(f"{display_path(path, root)}: action {index} must require human review")
        if action.get("writes_canonical_sources") is not False:
            raise ValueError(f"{display_path(path, root)}: action {index} must be non-mutating in the plan")
        if action.get("non_advisory") is not True:
            raise ValueError(f"{display_path(path, root)}: action {index} must be non-advisory")
    return plan


def select_unapplied(root: Path = ROOT, max_actions: int | None = DEFAULT_MAX_PROMOTION_ACTIONS_PER_PR) -> Path | None:
    paths, names, digests = applied_keys(root)
    for path in reviewed_plan_paths(root):
        relative = display_path(path, root)
        if relative in paths or path.name in names:
            continue
        if digests and plan_sha256(path) in digests:
            continue
        try:
            validate_candidate_promotion_plan(path, root, max_actions=max_actions)
        except ValueError:
            continue
        return path
    return None


def branch_for_plan(path: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return f"agent-candidate-promotion-{slug}"


def write_env(path: Path, values: dict[str, str | bool | int]) -> None:
    lines = []
    for key, value in values.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def select_command(args: argparse.Namespace) -> int:
    resolved_max_actions = resolve_max_promotion_actions_per_pr(
        max_promotion_actions_per_pr=args.max_promotion_actions_per_pr,
        max_actions_per_plan=args.max_actions_per_plan,
    )
    if resolved_max_actions is None:
        resolved_max_actions = DEFAULT_MAX_PROMOTION_ACTIONS_PER_PR
    max_actions = None if resolved_max_actions <= 0 else resolved_max_actions
    requested = str(args.promotion_plan or "").strip()
    if requested:
        path = ROOT / requested
        if is_applied(path):
            print(f"Reviewed candidate promotion plan already applied: {display_path(path)}")
            write_env(args.output, {"HAS_REVIEWED_PLAN": False, "REVIEWED_PLAN_ALREADY_APPLIED": True, "SELECTED_PLAN_PATH": display_path(path), "SELECTED_PLAN_SHA256": plan_sha256(path) if path.exists() else "", "SELECTED_PLAN_ACTION_COUNT": 0, "SELECTED_PR_BRANCH": branch_for_plan(path)})
            return 0
        plan = validate_candidate_promotion_plan(path, max_actions=max_actions)
    else:
        path = select_unapplied(max_actions=max_actions)
        if path is None:
            print("No unapplied reviewed candidate promotion plans found.")
            write_env(args.output, {"HAS_REVIEWED_PLAN": False, "REVIEWED_PLAN_ALREADY_APPLIED": False, "SELECTED_PLAN_PATH": "", "SELECTED_PLAN_SHA256": "", "SELECTED_PLAN_ACTION_COUNT": 0, "SELECTED_PR_BRANCH": ""})
            return 0
        plan = load_json(path)
    actions = plan.get("actions", []) or []
    write_env(args.output, {"HAS_REVIEWED_PLAN": True, "REVIEWED_PLAN_ALREADY_APPLIED": False, "SELECTED_PLAN_PATH": display_path(path), "SELECTED_PLAN_SHA256": plan_sha256(path), "SELECTED_PLAN_ACTION_COUNT": len(actions), "SELECTED_PR_BRANCH": branch_for_plan(path)})
    print(f"Selected reviewed candidate promotion plan: {display_path(path)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-candidate-promotion-lifecycle")
    subparsers = parser.add_subparsers(dest="command", required=True)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--promotion-plan", type=str, default="")
    select_parser.add_argument("--max-promotion-actions-per-pr", type=int)
    select_parser.add_argument("--max-actions-per-plan", type=int, help="Deprecated alias for --max-promotion-actions-per-pr")
    select_parser.add_argument("--output", type=Path, required=True)
    select_parser.set_defaults(func=select_command)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
