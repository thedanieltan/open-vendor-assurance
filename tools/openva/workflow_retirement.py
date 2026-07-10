from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")
WORKFLOW_RETIREMENT = Path("docs/operations/contracts/workflow-retirement.yaml")
WORKFLOW_RETIREMENT_EXTENSIONS = "workflow-retirement.*.yaml"
DEFAULT_REPORT = Path("maintenance/workflow-retirement-report.md")


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def load_retirement_contract(root: Path = ROOT) -> dict[str, Any]:
    """Load the base contract plus additive, name-unique workflow extensions."""

    base_path = root / WORKFLOW_RETIREMENT
    retirement = load_yaml(base_path)
    workflows = list(retirement.get("workflows", []) or [])
    names = {str(entry.get("name") or "") for entry in workflows}
    for path in sorted(base_path.parent.glob(WORKFLOW_RETIREMENT_EXTENSIONS)):
        if path == base_path:
            continue
        extension = load_yaml(path)
        if extension.get("contract") != "workflow-retirement-extension":
            raise ValueError(f"{path}: expected workflow-retirement-extension contract")
        if extension.get("extends") != WORKFLOW_RETIREMENT.as_posix():
            raise ValueError(f"{path}: extension target mismatch")
        for entry in extension.get("workflows", []) or []:
            name = str(entry.get("name") or "")
            if not name:
                raise ValueError(f"{path}: retirement extension entry missing name")
            if name in names:
                raise ValueError(f"{path}: duplicate retirement entry {name}")
            names.add(name)
            workflows.append(entry)
    return {**retirement, "workflows": workflows}


def load_contracts(root: Path = ROOT) -> dict[str, Any]:
    return {
        "inventory": load_yaml(root / WORKFLOW_INVENTORY),
        "retirement": load_retirement_contract(root),
    }


def inventory_entries(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    return list(inventory.get("public_workflows", []) or [])


def retirement_entries(retirement: dict[str, Any]) -> list[dict[str, Any]]:
    return list(retirement.get("workflows", []) or [])


def entries_by_name(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(entry["name"]): entry for entry in entries}


def validate_contracts(contracts: dict[str, Any]) -> list[str]:
    inventory = contracts["inventory"]
    retirement = contracts["retirement"]
    inventory_by_name = entries_by_name(inventory_entries(inventory))
    retirement_by_name = entries_by_name(retirement_entries(retirement))
    statuses = set(retirement.get("statuses", []) or [])
    errors: list[str] = []

    missing = sorted(set(inventory_by_name) - set(retirement_by_name))
    extra = sorted(set(retirement_by_name) - set(inventory_by_name))
    if missing:
        errors.append(f"missing_retirement_entries: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown_retirement_entries: {', '.join(extra)}")

    posture = retirement.get("default_posture", {})
    if posture.get("unclassified_workflows_block_retirement") is not True:
        errors.append("default_posture.unclassified_workflows_block_retirement must be true")
    if posture.get("workflow_deletion_allowed_in_this_contract") is not False:
        errors.append("default_posture.workflow_deletion_allowed_in_this_contract must be false")

    for name, entry in retirement_by_name.items():
        status = entry.get("current_status")
        if status not in statuses:
            errors.append(f"{name}: invalid current_status {status}")
        if status == "active" and entry.get("retirement_ready") is True:
            errors.append(f"{name}: active workflow cannot be retirement_ready")
        if entry.get("retirement_candidate") and not entry.get("replacement_owner") and not entry.get("retirement_blockers"):
            errors.append(f"{name}: retirement candidate needs replacement_owner or blockers")
        if name in inventory_by_name and entry.get("inventory_status") != inventory_by_name[name].get("status"):
            errors.append(f"{name}: inventory_status mismatch")
        if entry.get("current_status") == "retired":
            errors.append(f"{name}: retired workflows must not remain in public inventory")

    return errors


def safe_for_future_consideration(entry: dict[str, Any]) -> bool:
    return bool(entry.get("retirement_candidate")) and entry.get("current_status") in {
        "shadow_report_only",
        "deprecated_callable",
        "quarantined",
    }


def build_report(contracts: dict[str, Any]) -> str:
    inventory = contracts["inventory"]
    retirement = contracts["retirement"]
    retirement_by_name = entries_by_name(retirement_entries(retirement))
    errors = validate_contracts(contracts)

    lines = [
        "# Workflow Retirement Report",
        "",
        "Source document: `docs/operations/WORKFLOW_RETIREMENT_PLAN.md`",
        "",
        f"Validation status: {'blocked' if errors else 'ok'}",
        "",
        "## Summary",
        "",
    ]

    counts: dict[str, int] = {status: 0 for status in retirement.get("statuses", []) or []}
    for entry in retirement_entries(retirement):
        counts[str(entry["current_status"])] = counts.get(str(entry["current_status"]), 0) + 1
    for status in retirement.get("statuses", []) or []:
        lines.append(f"- `{status}`: {counts.get(status, 0)}")

    lines.extend(
        [
            "",
            "## Workflow Classification",
            "",
            "| Workflow | Inventory status | Retirement status | Candidate | Ready | Replacement owner |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for inventory_entry in inventory_entries(inventory):
        entry = retirement_by_name[inventory_entry["name"]]
        lines.append(
            "| `{name}` | `{inventory_status}` | `{current_status}` | {candidate} | {ready} | {owner} |".format(
                name=entry["name"],
                inventory_status=entry["inventory_status"],
                current_status=entry["current_status"],
                candidate="yes" if entry.get("retirement_candidate") else "no",
                ready="yes" if entry.get("retirement_ready") else "no",
                owner=str(entry.get("replacement_owner", "")).replace("|", "/"),
            )
        )

    candidates = [entry for entry in retirement_entries(retirement) if safe_for_future_consideration(entry)]
    lines.extend(["", "## Future Retirement Consideration", ""])
    if candidates:
        for entry in candidates:
            blockers = "; ".join(str(blocker) for blocker in entry.get("retirement_blockers", []))
            lines.append(f"- `{entry['name']}`: {entry['current_status']}; blockers: {blockers}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Contract Validation", ""])
    if errors:
        for error in errors:
            lines.append(f"- {error}")
    else:
        lines.append("- All inventory workflows have retirement entries.")
        lines.append("- No workflow is marked retired in the public inventory.")
        lines.append("- Destructive workflow retirement remains disallowed in this contract.")

    return "\n".join(lines) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-workflow-retirement")
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--out", type=Path, default=ROOT / DEFAULT_REPORT)
    report_parser.add_argument("--json", action="store_true", help="Print machine-readable validation summary.")
    args = parser.parse_args(argv)

    if args.command == "report":
        contracts = load_contracts()
        report = build_report(contracts)
        out = args.out if args.out.is_absolute() else ROOT / args.out
        write_text(out, report)
        errors = validate_contracts(contracts)
        summary = {"status": "blocked" if errors else "ok", "errors": errors, "out": str(out)}
        print(json.dumps(summary, sort_keys=True) if args.json else summary["status"])
        return 1 if errors else 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
