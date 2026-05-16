from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import build_indexes
from tools.openva.source_verification import ROOT, display_path

ACTIONABLE_CLEANUP_ACTIONS = {
    "cleanup_source_for_review",
    "retire_or_replace_source_for_review",
}


@dataclass(frozen=True)
class FileAction:
    action: str
    path: Path
    reason: str

    def as_dict(self, root: Path) -> dict[str, str]:
        return {
            "action": self.action,
            "path": display_path(self.path, root),
            "reason": self.reason,
        }


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def source_path_for_action(action: dict[str, Any], root: Path) -> Path:
    action_path = action.get("path")
    if action_path:
        return root / str(action_path)
    vendor_id = str(action["vendor_id"])
    source_id = str(action["source_id"])
    return root / "data" / "vendors" / vendor_id / "sources" / f"{source_id}.yaml"


def artifact_paths_for_source(root: Path, vendor_id: str, source_id: str) -> list[Path]:
    paths: list[Path] = []
    for path in sorted((root / "data" / "vendors" / vendor_id / "artifacts").glob("*.yaml")):
        artifact = load_yaml(path)
        if artifact.get("source_id") == source_id:
            paths.append(path)
    return paths


def change_paths_for_source_or_artifacts(root: Path, vendor_id: str, source_id: str, artifact_ids: set[str]) -> list[Path]:
    paths: list[Path] = []
    for path in sorted((root / "data" / "vendors" / vendor_id / "changes").glob("*.yaml")):
        change = load_yaml(path)
        if change.get("source_id") == source_id or change.get("artifact_id") in artifact_ids:
            paths.append(path)
    return paths


def unavailable_source_path(root: Path, vendor_id: str, source_type: str) -> Path:
    suffix = source_type.replace("_", "-")
    return root / "data" / "vendors" / vendor_id / "unavailable_sources" / f"{vendor_id}-{suffix}.yaml"


def unavailable_source_record(action: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    vendor_id = str(source["vendor_id"])
    source_type = str(source["source_type"])
    source_url = str(source.get("source_url") or action.get("source_url") or "")
    verification = action.get("verification") or {}
    verification_status = str(verification.get("verification_status") or "")
    reason = "public_source_temporarily_unavailable" if verification_status in {"not_found", "gone"} else "distinct_public_url_not_identified"

    return {
        "schema_version": "0.1.0",
        "unavailable_source_id": f"{vendor_id}-{source_type.replace('_', '-')}",
        "vendor_id": vendor_id,
        "source_type": source_type,
        "status": "not_identified",
        "reason": reason,
        "reviewed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reviewed_by": "agent",
        "next_review_after": (date.today() + timedelta(days=90)).isoformat(),
        "candidate_urls_checked": [source_url] if source_url else [],
        "notes": (
            "Canonical source removed through reviewed maintenance action because the promotion plan marked it as "
            f"{action.get('action')}. This is not a legal, procurement, compliance, risk, or vendor approval conclusion."
        ),
        "not_advice": True,
    }


def plan_cleanup_action(action: dict[str, Any], root: Path) -> tuple[list[FileAction], dict[str, Any] | None]:
    source_path = source_path_for_action(action, root)
    if not source_path.exists():
        return ([FileAction("missing", source_path, "Source path from promotion plan was not found.")], None)

    source = load_yaml(source_path)
    vendor_id = str(source["vendor_id"])
    source_id = str(source["source_id"])
    source_type = str(source["source_type"])
    artifact_paths = artifact_paths_for_source(root, vendor_id, source_id)
    artifact_ids = {load_yaml(path)["artifact_id"] for path in artifact_paths}
    change_paths = change_paths_for_source_or_artifacts(root, vendor_id, source_id, artifact_ids)
    unavailable_path = unavailable_source_path(root, vendor_id, source_type)

    file_actions = [
        FileAction("delete", path, f"Remove generated canonical source dependency for {source_id}.")
        for path in [source_path, *artifact_paths, *change_paths]
    ]
    file_actions.append(
        FileAction("write", unavailable_path, f"Record reviewed absence for {vendor_id}/{source_type} after source cleanup.")
    )
    return file_actions, unavailable_source_record(action, source)


def build_maintenance_plan(promotion_plan: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    actions = promotion_plan.get("actions", []) or []
    selected = [action for action in actions if action.get("action") in ACTIONABLE_CLEANUP_ACTIONS]
    file_actions: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []

    for action in selected:
        planned, unavailable = plan_cleanup_action(action, root)
        file_actions.extend(item.as_dict(root) for item in planned)
        if unavailable is None:
            skipped.append({"action": action, "reason": "source path missing"})

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "maintenance_action_plan",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "promotion_actions_seen": len(actions),
            "cleanup_actions_selected": len(selected),
            "file_actions_planned": len(file_actions),
            "skipped_actions": len(skipped),
        },
        "file_actions": file_actions,
        "skipped": skipped,
    }


def apply_maintenance_plan(promotion_plan: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    actions = promotion_plan.get("actions", []) or []
    selected = [action for action in actions if action.get("action") in ACTIONABLE_CLEANUP_ACTIONS]
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []

    for action in selected:
        planned, unavailable = plan_cleanup_action(action, root)
        if unavailable is None:
            skipped.append({"action": action, "reason": "source path missing"})
            applied.extend(item.as_dict(root) for item in planned)
            continue

        for file_action in planned:
            if file_action.action == "delete" and file_action.path.exists():
                file_action.path.unlink()
            elif file_action.action == "write":
                write_yaml(file_action.path, unavailable)
            applied.append(file_action.as_dict(root))

    build_indexes()

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "maintenance_action_apply_report",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": True,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "promotion_actions_seen": len(actions),
            "cleanup_actions_selected": len(selected),
            "file_actions_applied": len(applied),
            "skipped_actions": len(skipped),
        },
        "file_actions": applied,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-maintenance-actions")
    parser.add_argument("command", choices={"plan", "apply"})
    parser.add_argument("--promotion-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "maintenance-action-report.json")
    args = parser.parse_args()

    promotion_plan = load_json(args.promotion_plan)
    if args.command == "plan":
        report = build_maintenance_plan(promotion_plan)
    else:
        report = apply_maintenance_plan(promotion_plan)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
