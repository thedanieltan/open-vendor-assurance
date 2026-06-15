"""Append-only discovery event ledger.

Discovery remains report-only. This module is the separate executor used by
path-restricted PR lanes to append discovery-event deltas under
maintenance/discovery-events/*.ndjson.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from tools.openva.indexes import ROOT

DEFAULT_LEDGER_DIR = ROOT / "maintenance" / "discovery-events"
MAX_APPEND_COUNT = 500
HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
EVENT_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}: expected NDJSON object rows")
            events.append(value)
    return events


def ledger_files(ledger_dir: Path) -> list[Path]:
    if not ledger_dir.exists():
        return []
    return sorted(ledger_dir.glob("*.ndjson"))


def load_existing_event_ids(ledger_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in ledger_files(ledger_dir):
        for event in load_events(path):
            event_id = event.get("discovery_event_id")
            if event_id:
                ids.add(str(event_id))
    return ids


def validate_event(event: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    required = (
        "schema_version",
        "discovery_event_id",
        "candidate_id",
        "origin",
        "candidate_url",
        "evidence_digest",
        "classification",
        "reason_codes",
        "discovery_run_id",
        "policy_version",
        "discovered_at",
        "not_advice",
    )
    for field in required:
        if field not in event:
            reasons.append(f"missing:{field}")
    if event.get("schema_version") != "0.1.0":
        reasons.append("schema_version_invalid")
    if not EVENT_ID_RE.fullmatch(str(event.get("discovery_event_id") or "")):
        reasons.append("discovery_event_id_invalid")
    if not HASH_RE.fullmatch(str(event.get("evidence_digest") or "")):
        reasons.append("evidence_digest_invalid")
    if not isinstance(event.get("reason_codes"), list):
        reasons.append("reason_codes_not_list")
    if event.get("not_advice") is not True:
        reasons.append("not_advice_not_true")
    return reasons


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda event: (
            str(event.get("discovered_at") or ""),
            str(event.get("candidate_id") or ""),
            str(event.get("discovery_event_id") or ""),
        ),
    )


def append_events(
    delta: list[dict[str, Any]],
    ledger_dir: Path = DEFAULT_LEDGER_DIR,
    *,
    max_append_count: int = MAX_APPEND_COUNT,
) -> list[Path]:
    if len(delta) > max_append_count:
        raise ValueError(f"too_many_discovery_events:{len(delta)}>{max_append_count}")
    failures: list[str] = []
    for event in delta:
        failures.extend(f"{event.get('discovery_event_id', '(missing)')}: {reason}" for reason in validate_event(event))
    ids = [str(event.get("discovery_event_id") or "") for event in delta]
    duplicate_delta_ids = [event_id for event_id, count in Counter(ids).items() if event_id and count > 1]
    if duplicate_delta_ids:
        failures.append("duplicate_delta_event_id:" + ",".join(sorted(duplicate_delta_ids)))
    existing_ids = load_existing_event_ids(ledger_dir)
    duplicate_existing_ids = sorted(existing_ids & set(ids))
    if duplicate_existing_ids:
        failures.append("duplicate_existing_event_id:" + ",".join(duplicate_existing_ids))
    if failures:
        raise ValueError("; ".join(failures))

    by_month: dict[str, list[dict[str, Any]]] = {}
    for event in sort_events(delta):
        by_month.setdefault(str(event["discovered_at"])[:7], []).append(event)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    touched: list[Path] = []
    for month, rows in sorted(by_month.items()):
        path = ledger_dir / f"{month}.ndjson"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        touched.append(path)
    return touched


def events_from_discovery_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for vendor in report.get("vendors", []) or []:
        if isinstance(vendor, dict):
            events.extend(event for event in vendor.get("discovery_events", []) or [] if isinstance(event, dict))
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)
    append = subparsers.add_parser("append")
    append.add_argument("--delta", type=Path, help="NDJSON discovery event delta")
    append.add_argument("--discovery-report", type=Path, help="source-discovery-report.json artifact")
    append.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    append.add_argument("--max-append-count", type=int, default=MAX_APPEND_COUNT)
    append.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)

    if args.command == "append":
        if bool(args.delta) == bool(args.discovery_report):
            raise SystemExit("exactly one of --delta or --discovery-report is required")
        delta = (
            load_events(args.delta)
            if args.delta
            else events_from_discovery_report(json.loads(args.discovery_report.read_text(encoding="utf-8")))
        )
        touched = append_events(delta, args.ledger_dir, max_append_count=args.max_append_count)
        summary = {
            "schema_version": "0.1.0",
            "appended": len(delta),
            "affected_months": [path.stem for path in touched],
            "not_advice": True,
        }
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
