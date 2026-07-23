"""Fail-closed schedule budget for scheduled GitHub Actions workflows.

WP-OPENVA-WORKFLOW-SCHEDULE-BUDGET-01 (four-plane refactor / workflow consolidation).

The workflow-inventory contract already pins which workflows exist and their trigger *types*
(`test_workflow_contracts.py`), but nothing declares or bounds how *often* the scheduled ones
run. A `*/10 * * * *` poll (agent-automerge) is ~1,008 runs/week; a silent change to `*/5`
would double the CI/compute budget with no review, and a new scheduled workflow could be added
with no frequency ceiling. That is exactly the trigger-sprawl / minutes-cost failure mode the
four-plane redesign calls out.

This guard makes the schedule surface auditable and enforced. Given
`docs/operations/contracts/workflow-schedule-budget.yaml` it fails closed when:

  1. a workflow with a `schedule:` trigger is not declared in the budget (or a declared
     workflow no longer schedules) — no undeclared scheduled workflow;
  2. a declared workflow's crons do not exactly match its actual `on.schedule` crons — a
     silent schedule change (drift) is caught, just as the inventory catches trigger-type drift;
  3. a workflow's computed runs-per-week exceeds its declared `max_runs_per_week` ceiling; or
  4. the aggregate runs-per-week across all scheduled workflows exceeds the declared budget.

Raising a ceiling or the aggregate budget is therefore a reviewed edit to the contract, not a
silent workflow change. No workflow is added, removed, or rescheduled by this guard.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
BUDGET_CONTRACT = ROOT / "docs" / "operations" / "contracts" / "workflow-schedule-budget.yaml"

_FIELD_BOUNDS = {
    "minute": (0, 59),
    "hour": (0, 23),
    "dom": (1, 31),
    "month": (1, 12),
    "dow": (0, 6),
}


def _parse_field(field: str, low: int, high: int) -> set[int]:
    """Expand one cron field into the set of matched integers in [low, high].

    Day-of-week 7 is normalized to 0 (Sunday). Supports '*', '*/step', 'a-b', 'a-b/step',
    single values, and comma lists of those.
    """
    matched: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
        else:
            base = part
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)
        for value in range(start, end + 1, step):
            if high == 6 and value == 7:  # day-of-week Sunday alias
                value = 0
            if low <= value <= high:
                matched.add(value)
    return matched


def runs_per_week(cron: str) -> float:
    """Estimate how many times a 5-field cron fires per week.

    minutes*hours per active day, times active days per week. Day selection follows cron's
    OR of day-of-month and day-of-week when both are restricted (upper-bounded at 7/week)."""
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(f"expected a 5-field cron expression, got {cron!r}")
    minute, hour, dom, month, dow = fields
    minutes = _parse_field(minute, *_FIELD_BOUNDS["minute"])
    hours = _parse_field(hour, *_FIELD_BOUNDS["hour"])
    months = _parse_field(month, *_FIELD_BOUNDS["month"])
    per_active_day = len(minutes) * len(hours)

    dom_restricted = dom.strip() != "*"
    dow_restricted = dow.strip() != "*"
    if not dom_restricted and not dow_restricted:
        active_days_per_week = 7.0
    elif dow_restricted and not dom_restricted:
        active_days_per_week = float(len(_parse_field(dow, *_FIELD_BOUNDS["dow"])))
    elif dom_restricted and not dow_restricted:
        # Day-of-month restricted: convert matched days per month to a weekly rate.
        active_days_per_week = min(7.0, len(_parse_field(dom, *_FIELD_BOUNDS["dom"])) * 12.0 / 52.14)
    else:
        # cron ORs day-of-month and day-of-week; upper-bound the union at a full week.
        dow_days = float(len(_parse_field(dow, *_FIELD_BOUNDS["dow"])))
        dom_days = len(_parse_field(dom, *_FIELD_BOUNDS["dom"])) * 12.0 / 52.14
        active_days_per_week = min(7.0, dow_days + dom_days)

    month_fraction = len(months) / 12.0
    return per_active_day * active_days_per_week * month_fraction * 12.0 / 12.0


def _workflow_crons(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML parses a bare `on:` key as the boolean True; accept either spelling.
    on = doc.get("on", doc.get(True)) if isinstance(doc, dict) else None
    if not isinstance(on, dict):
        return []
    schedule = on.get("schedule") or []
    return [entry["cron"] for entry in schedule if isinstance(entry, dict) and "cron" in entry]


def scheduled_workflows() -> dict[str, list[str]]:
    """Actual scheduled workflows -> their cron expressions."""
    result: dict[str, list[str]] = {}
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        crons = _workflow_crons(path)
        if crons:
            result[path.name] = crons
    return result


def load_contract(path: Path = BUDGET_CONTRACT) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check(contract_path: Path = BUDGET_CONTRACT) -> list[str]:
    problems: list[str] = []
    contract = load_contract(contract_path)
    declared = {entry["name"]: entry for entry in contract.get("workflows", [])}
    actual = scheduled_workflows()

    undeclared = sorted(set(actual) - set(declared))
    for name in undeclared:
        problems.append(f"{name}: schedules {actual[name]} but is not declared in the schedule budget")
    stale = sorted(set(declared) - set(actual))
    for name in stale:
        problems.append(f"{name}: declared in the schedule budget but no longer has a schedule trigger")

    total = 0.0
    for name in sorted(set(actual) & set(declared)):
        entry = declared[name]
        declared_crons = list(entry.get("crons") or [])
        if declared_crons != actual[name]:
            problems.append(
                f"{name}: declared crons {declared_crons} do not match the workflow's actual "
                f"crons {actual[name]} (schedule changed without a reviewed budget update)"
            )
        weekly = sum(runs_per_week(cron) for cron in actual[name])
        total += weekly
        ceiling = entry.get("max_runs_per_week")
        if ceiling is None:
            problems.append(f"{name}: missing max_runs_per_week in the schedule budget")
        elif weekly > ceiling + 1e-9:
            problems.append(
                f"{name}: ~{weekly:.0f} runs/week exceeds declared ceiling {ceiling} "
                "(raise the ceiling in the contract only as a reviewed decision)"
            )

    aggregate = contract.get("aggregate_max_runs_per_week")
    if aggregate is None:
        problems.append("schedule budget is missing aggregate_max_runs_per_week")
    elif total > aggregate + 1e-9:
        problems.append(
            f"aggregate ~{total:.0f} runs/week exceeds the declared budget {aggregate} "
            "(reduce schedule frequency or raise the budget as a reviewed decision)"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenVA workflow schedule budget guard")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    report = sub.add_parser("report")
    report.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    if args.command == "report":
        actual = scheduled_workflows()
        rows = sorted(
            ((name, sum(runs_per_week(c) for c in crons), crons) for name, crons in actual.items()),
            key=lambda row: row[1],
            reverse=True,
        )
        if getattr(args, "json", False):
            import json

            print(json.dumps({name: {"crons": crons, "runs_per_week": round(weekly, 1)}
                              for name, weekly, crons in rows}, indent=2))
        else:
            for name, weekly, crons in rows:
                print(f"{name:52s} ~{weekly:7.0f}/wk  {crons}")
            print(f"{'TOTAL':52s} ~{sum(r[1] for r in rows):7.0f}/wk")
        return 0

    problems = check()
    if problems:
        print("Workflow schedule budget FAILED:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print("Workflow schedule budget: all scheduled workflows declared and within budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
