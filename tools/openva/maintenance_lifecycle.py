from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.openva.source_verification import ROOT, display_path

APPLIED_PLANS = ROOT / "maintenance" / "applied" / "applied-plans.json"
REVIEWED_DIR = ROOT / "maintenance" / "reviewed"
DEFAULT_MAX_ACTIONS_PER_PLAN = 50
ALLOWED_CLEANUP_ACTIONS = {
    "cleanup_source_for_review",
    "retire_or_replace_source_for_review",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def plan_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reviewed_plan_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "maintenance" / "reviewed").glob("*.json"))


def applied_plan_entries(root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / "maintenance" / "applied" / "applied-plans.json"
    if not path.exists():
        return []
    registry = load_json(path)
    plans = registry.get("plans", [])
    if not isinstance(plans, list):
        raise ValueError(f"{display_path(path)}: plans must be a list")
    return [plan for plan in plans if isinstance(plan, dict)]


def applied_plan_key_sets(root: Path = ROOT) -> tuple[set[str], set[str], set[str]]:
    paths: set[str] = set()
    names: set[str] = set()
    digests: set[str] = set()
    for entry in applied_plan_entries(root):
        if entry.get("status") != "applied":
            continue
        if entry.get("plan_path"):
            paths.add(str(entry["plan_path"]))
        if entry.get("plan_name"):
            names.add(str(entry["plan_name"]))
        if entry.get("plan_sha256"):
            digests.add(str(entry["plan_sha256"]))
    return paths, names, digests


def is_applied_plan(path: Path, root: Path = ROOT) -> bool:
    relative_path = display_path(path, root)
    paths, names, digests = applied_plan_key_sets(root)
    if relative_path in paths or path.name in names:
        return True
    if digests and path.exists() and plan_sha256(path) in digests:
        return True
    return False


def assert_reviewed_plan_path(path: Path, root: Path = ROOT) -> None:
    try:
        path.resolve().relative_to((root / "maintenance" / "reviewed").resolve())
    except ValueError as exc:
        raise ValueError("promotion_plan_path must be under maintenance/reviewed/ and end with .json") from exc
    if path.suffix != ".json":
        raise ValueError("promotion_plan_path must be under maintenance/reviewed/ and end with .json")
    if not path.exists():
        raise ValueError(f"promotion plan file not found: {display_path(path, root)}")


def validate_reviewed_cleanup_plan(
    path: Path,
    root: Path = ROOT,
    max_actions: int | None = DEFAULT_MAX_ACTIONS_PER_PLAN,
) -> dict[str, Any]:
    assert_reviewed_plan_path(path, root)
    plan = load_json(path)
    posture = plan.get("posture") or {}
    expected_posture = {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }
    for key, expected in expected_posture.items():
        if posture.get(key) is not expected:
            raise ValueError(f"{display_path(path, root)}: posture.{key} must be {expected!r}")

    actions = plan.get("actions", []) or []
    if not isinstance(actions, list):
        raise ValueError(f"{display_path(path, root)}: actions must be a list")
    if max_actions is not None and len(actions) > max_actions:
        raise ValueError(
            f"{display_path(path, root)}: reviewed plan has {len(actions)} actions, "
            f"which exceeds max_actions_per_plan={max_actions}. Split the reviewed plan into smaller batches."
        )
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"{display_path(path, root)}: action {index} must be an object")
        action_type = action.get("action")
        if action_type not in ALLOWED_CLEANUP_ACTIONS:
            raise ValueError(
                f"{display_path(path, root)}: action {index} uses unsupported reviewed cleanup action {action_type!r}"
            )
        if action.get("non_advisory") is not True:
            raise ValueError(f"{display_path(path, root)}: action {index} must set non_advisory true")
    return plan


def select_unapplied_reviewed_plan(
    root: Path = ROOT,
    max_actions: int | None = DEFAULT_MAX_ACTIONS_PER_PLAN,
) -> Path | None:
    paths, names, digests = applied_plan_key_sets(root)
    for path in reviewed_plan_paths(root):
        relative_path = display_path(path, root)
        if relative_path in paths or path.name in names:
            continue
        if digests and plan_sha256(path) in digests:
            continue
        validate_reviewed_cleanup_plan(path, root, max_actions=max_actions)
        return path
    return None


def branch_for_plan(path: Path) -> str:
    stem = path.stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return f"agent-catalog-maintenance-{slug}"


def write_env(path: Path, values: dict[str, str | bool | int]) -> None:
    lines = []
    for key, value in values.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def select_command(args: argparse.Namespace) -> int:
    output = args.output
    max_actions = None if args.max_actions_per_plan <= 0 else args.max_actions_per_plan
    requested = str(args.promotion_plan or "").strip()
    if requested:
        path = ROOT / requested
        if is_applied_plan(path):
            print(f"Reviewed plan already applied: {display_path(path)}")
            write_env(
                output,
                {
                    "HAS_REVIEWED_PLAN": False,
                    "REVIEWED_PLAN_ALREADY_APPLIED": True,
                    "SELECTED_PLAN_PATH": display_path(path),
                    "SELECTED_PLAN_SHA256": plan_sha256(path) if path.exists() else "",
                    "SELECTED_PLAN_ACTION_COUNT": 0,
                    "SELECTED_PR_BRANCH": branch_for_plan(path),
                },
            )
            return 0
        plan = validate_reviewed_cleanup_plan(path, max_actions=max_actions)
    else:
        path = select_unapplied_reviewed_plan(max_actions=max_actions)
        if path is None:
            print("No unapplied reviewed maintenance plans found.")
            write_env(
                output,
                {
                    "HAS_REVIEWED_PLAN": False,
                    "REVIEWED_PLAN_ALREADY_APPLIED": False,
                    "SELECTED_PLAN_PATH": "",
                    "SELECTED_PLAN_SHA256": "",
                    "SELECTED_PLAN_ACTION_COUNT": 0,
                    "SELECTED_PR_BRANCH": "",
                },
            )
            return 0
        plan = load_json(path)

    actions = plan.get("actions", []) or []
    print(f"Selected reviewed plan: {display_path(path)}")
    print(f"Selected reviewed plan action count: {len(actions)}")
    write_env(
        output,
        {
            "HAS_REVIEWED_PLAN": True,
            "REVIEWED_PLAN_ALREADY_APPLIED": False,
            "SELECTED_PLAN_PATH": display_path(path),
            "SELECTED_PLAN_SHA256": plan_sha256(path),
            "SELECTED_PLAN_ACTION_COUNT": len(actions),
            "SELECTED_PR_BRANCH": branch_for_plan(path),
        },
    )
    return 0


def validate_command(args: argparse.Namespace) -> int:
    max_actions = None if args.max_actions_per_plan <= 0 else args.max_actions_per_plan
    path = ROOT / args.promotion_plan
    plan = validate_reviewed_cleanup_plan(path, max_actions=max_actions)
    print(
        json.dumps(
            {
                "plan_path": display_path(path),
                "plan_sha256": plan_sha256(path),
                "action_count": len(plan.get("actions", []) or []),
                "max_actions_per_plan": max_actions,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-maintenance-lifecycle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--promotion-plan", type=str, default="")
    select_parser.add_argument("--max-actions-per-plan", type=int, default=DEFAULT_MAX_ACTIONS_PER_PLAN)
    select_parser.add_argument("--output", type=Path, required=True)
    select_parser.set_defaults(func=select_command)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--promotion-plan", type=str, required=True)
    validate_parser.add_argument("--max-actions-per-plan", type=int, default=DEFAULT_MAX_ACTIONS_PER_PLAN)
    validate_parser.set_defaults(func=validate_command)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
