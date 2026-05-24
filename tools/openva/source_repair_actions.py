from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import build_indexes
from tools.openva.source_verification import ROOT, display_path

VALIDATION_REPORT_TYPE = "p0_source_repair_plan_validation"


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


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_path(root: Path, vendor_id: str, source_id: str) -> Path:
    return root / "data" / "vendors" / vendor_id / "sources" / f"{source_id}.yaml"


def validate_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != VALIDATION_REPORT_TYPE:
        raise ValueError(f"expected report_type={VALIDATION_REPORT_TYPE}")
    approved = report.get("approved")
    if not isinstance(approved, list):
        raise ValueError("expected approved list")
    for row in approved:
        if not isinstance(row, dict):
            raise ValueError("expected each approved row to be an object")
        if row.get("reasons") not in ([], None):
            raise ValueError("approved row must not contain rejection reasons")
        required = (
            "vendor_id",
            "source_id",
            "source_type",
            "original_source_url",
            "replacement_source_url",
            "replacement_verification_status",
            "replacement_http_status",
            "replacement_semantic_status",
            "replacement_authority_status",
            "replacement_access_status",
            "replacement_url_safety_status",
        )
        missing = [field for field in required if field not in row]
        if missing:
            raise ValueError(f"approved row missing required field(s): {', '.join(missing)}")
    return approved


def plan_row(row: dict[str, Any], root: Path) -> tuple[list[FileAction], list[str]]:
    reasons: list[str] = []
    vendor_id = str(row["vendor_id"])
    source_id = str(row["source_id"])
    path = source_path(root, vendor_id, source_id)
    if not path.exists():
        return [FileAction("missing", path, "Approved repair source file was not found.")], ["source_file_missing"]
    source = load_yaml(path)
    if source.get("vendor_id") != vendor_id:
        reasons.append("source_file_vendor_id_mismatch")
    if source.get("source_id") != source_id:
        reasons.append("source_file_source_id_mismatch")
    if source.get("source_type") != row.get("source_type"):
        reasons.append("source_file_source_type_mismatch")
    if source.get("source_url") != row.get("original_source_url"):
        reasons.append("source_file_url_mismatch")
    if reasons:
        return [FileAction("blocked", path, ",".join(reasons))], reasons
    return [FileAction("update", path, "Replace confirmed-P0 source URL with human-reviewed replacement.")], []


def build_repair_action_plan(validation_report: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    approved = validate_report(validation_report)
    file_actions: list[dict[str, str]] = []
    blocked: list[dict[str, Any]] = []
    for row in approved:
        planned, reasons = plan_row(row, root)
        file_actions.extend(item.as_dict(root) for item in planned)
        if reasons:
            blocked.append({"repair": row, "reasons": reasons})
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "p0_source_repair_action_plan",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "summary": {
            "approved_repairs_seen": len(approved),
            "file_actions_planned": len(file_actions),
            "blocked_repairs": len(blocked),
        },
        "file_actions": file_actions,
        "blocked": blocked,
    }


def apply_repair_actions(validation_report: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    approved = validate_report(validation_report)
    applied: list[dict[str, str]] = []
    blocked: list[dict[str, Any]] = []
    for row in approved:
        planned, reasons = plan_row(row, root)
        if reasons:
            applied.extend(item.as_dict(root) for item in planned)
            blocked.append({"repair": row, "reasons": reasons})
            continue
        action = planned[0]
        source = load_yaml(action.path)
        source["source_url"] = row["replacement_source_url"]
        source["review_state"] = "human_reviewed"
        source["catalog_tier"] = "human_reviewed"
        provenance = source.get("provenance")
        if isinstance(provenance, dict):
            provenance["observer"] = "human"
            provenance["confidence"] = "high"
        write_yaml(action.path, source)
        applied.append(action.as_dict(root))
    if blocked:
        raise ValueError(f"blocked repair action(s): {len(blocked)}")
    build_indexes()
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "p0_source_repair_action_apply_report",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": True,
            "opens_pull_requests": False,
            "mutates_catalog": True,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "summary": {
            "approved_repairs_seen": len(approved),
            "file_actions_applied": len(applied),
            "blocked_repairs": len(blocked),
        },
        "file_actions": applied,
        "blocked": blocked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-actions")
    parser.add_argument("command", choices={"plan", "apply"})
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "source-repair-action-report.json")
    args = parser.parse_args()

    report = load_json(args.validation_report)
    if args.command == "plan":
        output = build_repair_action_plan(report)
    else:
        output = apply_repair_actions(report)
    write_json(args.output, output)
    print(json.dumps(output["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
