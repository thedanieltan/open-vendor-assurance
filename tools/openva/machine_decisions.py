"""WP36 machine decision records.

An append-only, monthly-sharded NDJSON store of autonomous machine decisions
under maintenance/machine-decisions/YYYY-MM.ndjson, mirroring the observation
ledger's append discipline. Every machine-created catalog claim links to a
decision record here so it is reproducible and reversible.

Separation of duties is enforced at write time: the deciding bot must differ
from the discovery bot. Records are schema-validated and append-only; existing
records are never rewritten or reordered, and duplicate decision ids are
refused. The deeper independent-quorum separation (supporting-bot independence,
self-approval prohibition) lands in WP37; this module enforces the core
discovery != decision rule and the append/schema invariants WP36 needs.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema

from tools.openva.indexes import ROOT

DEFAULT_DECISIONS_DIR = ROOT / "maintenance" / "machine-decisions"
RECORD_SCHEMA_PATH = ROOT / "schemas" / "openva" / "machine-decision-record.schema.json"


def load_record_schema() -> dict[str, Any]:
    return json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))


def month_key(created_at: str) -> str:
    return str(created_at)[:7]


def decision_files(decisions_dir: Path) -> list[Path]:
    if not decisions_dir.exists():
        return []
    return sorted(decisions_dir.glob("*.ndjson"))


def load_decisions(decisions_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in decision_files(decisions_dir):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def separation_of_duty_violation(record: dict[str, Any]) -> str | None:
    """Core WP36 rule: a discovery component may not approve its own discovery."""
    deciding = str(record.get("deciding_bot") or "")
    discovery = str(record.get("discovery_bot") or "")
    if deciding and discovery and deciding == discovery:
        return f"separation_of_duty:deciding_bot == discovery_bot ({deciding})"
    supporting = [str(b) for b in record.get("supporting_bots") or []]
    if supporting and supporting == [deciding]:
        return "separation_of_duty:deciding_bot is the sole supporting bot"
    return None


def validate_record(record: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    schema = schema or load_record_schema()
    reasons: list[str] = []
    for error in jsonschema.Draft202012Validator(schema).iter_errors(record):
        reasons.append(f"schema: {error.message}")
    sod = separation_of_duty_violation(record)
    if sod:
        reasons.append(sod)
    return reasons


def validate_committed(decisions_dir: Path = DEFAULT_DECISIONS_DIR) -> list[str]:
    schema = load_record_schema()
    reasons: list[str] = []
    seen: set[str] = set()
    for record in load_decisions(decisions_dir):
        decision_id = str(record.get("decision_id") or "(missing)")
        for reason in validate_record(record, schema):
            reasons.append(f"{decision_id}: {reason}")
        if decision_id in seen:
            reasons.append(f"{decision_id}: duplicate decision_id")
        seen.add(decision_id)
    return reasons


def append_decisions(delta: list[dict[str, Any]], decisions_dir: Path = DEFAULT_DECISIONS_DIR) -> list[Path]:
    """Append decision records to the monthly committed store.

    Append-only: existing lines are never rewritten or reordered; duplicate
    decision ids are refused; every row is schema-validated and must satisfy
    separation of duties before any write occurs.
    """
    schema = load_record_schema()
    existing_ids = {str(record.get("decision_id")) for record in load_decisions(decisions_dir)}
    for record in delta:
        reasons = validate_record(record, schema)
        if reasons:
            raise ValueError(f"invalid decision record {record.get('decision_id')}: {'; '.join(reasons)}")
        if str(record.get("decision_id")) in existing_ids:
            raise ValueError(f"duplicate decision_id: {record.get('decision_id')}")
    touched: list[Path] = []
    decisions_dir.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[dict[str, Any]]] = {}
    for record in delta:
        by_month.setdefault(month_key(str(record["created_at"])), []).append(record)
    for month, rows in sorted(by_month.items()):
        path = decisions_dir / f"{month}.ndjson"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in rows:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        touched.append(path)
    return touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-machine-decisions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append = subparsers.add_parser("append", help="append decision records from an NDJSON delta")
    append.add_argument("--delta", type=Path, required=True)
    append.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)

    validate = subparsers.add_parser("validate", help="validate the committed decision store")
    validate.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)

    args = parser.parse_args(argv)
    if args.command == "append":
        rows = [json.loads(line) for line in args.delta.read_text(encoding="utf-8").splitlines() if line.strip()]
        touched = append_decisions(rows, args.decisions_dir)
        print(json.dumps({"appended": len(rows), "files": [str(p) for p in touched]}, indent=2, sort_keys=True))
        return 0

    reasons = validate_committed(args.decisions_dir)
    if reasons:
        for reason in reasons:
            print(reason)
        return 1
    print("machine decision store is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
