"""WP35.5 autonomous observation-ledger append lane.

Two responsibilities:

  plan   Given a source-maintenance `observation-ledger-delta.ndjson`, filter it
         to the genuinely-new rows (idempotent on re-trigger), validate each new
         row against the ledger-record schema and append ordering, and emit a
         filtered delta plus a summary (counts, digest, affected monthly shards).
         The append-PR workflow uses this; zero new rows => no PR.

  check  The agent-automerge observation job's eligibility gate. Verifies the PR
         touches only the committed ledger events path, is strictly append-only
         against the base revision (existing lines never rewritten or removed),
         every new row validates against the schema, and the required lane labels
         are present. Fails closed.

This lane writes ONLY append-only operational observation events under
maintenance/source-observations/events/**. It never writes catalog truth,
mutates sources/vendors/schemas/tools/workflows, or merges by itself; merge is
enabled by the agent-automerge job after the WP35 release gate passes.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import jsonschema

from tools.openva.indexes import ROOT
from tools.openva.observation_ledger import last_observed_per_source, load_ledger_events, month_key

AUTOMERGE_OBSERVATION_LABEL = "automerge:observation"
OBSERVATION_LEDGER_LABEL = "observation-ledger"
LEDGER_EVENTS_PREFIX = "maintenance/source-observations/events/"
LEDGER_FILE_RE = re.compile(r"^maintenance/source-observations/events/\d{4}-\d{2}\.ndjson$")
RECORD_SCHEMA_PATH = ROOT / "schemas" / "openva" / "observation-ledger-record.schema.json"
DEFAULT_MAX_APPENDED_ROWS = 5000


@dataclass(frozen=True)
class ObservationAutomergeResult:
    eligible: bool
    reasons: tuple[str, ...]
    appended_rows: int = 0


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def load_record_schema() -> dict[str, Any]:
    return json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))


def is_ledger_event_path(path: str) -> bool:
    return bool(LEDGER_FILE_RE.match(path.strip()))


def parse_ndjson(text: str) -> list[str]:
    """Return non-blank stripped lines, preserving order."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def rows_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines]


def schema_violations(rows: list[dict[str, Any]], schema: dict[str, Any], *, where: str) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    reasons: list[str] = []
    for index, row in enumerate(rows):
        for error in validator.iter_errors(row):
            reasons.append(f"{where}[{index}] schema: {error.message}")
    return reasons


def append_only_new_lines(base_text: str | None, head_text: str) -> tuple[list[str], list[str]]:
    """Return (new_lines, violations). head must begin with exactly the base
    lines (no rewrites or removals); only appended lines are allowed."""
    head_lines = parse_ndjson(head_text)
    base_lines = parse_ndjson(base_text) if base_text is not None else []
    violations: list[str] = []
    if head_lines[: len(base_lines)] != base_lines:
        violations.append("not_append_only:existing_lines_modified_or_removed")
        return [], violations
    return head_lines[len(base_lines):], violations


def _safe_git_show(loader: Callable[[str, str], str], ref: str, path: str) -> str | None:
    try:
        return loader(ref, path)
    except subprocess.CalledProcessError:
        return None  # path did not exist at base (new monthly shard) => treat as empty
    except Exception:  # noqa: BLE001 - fail closed elsewhere; signal "unreadable" distinctly
        raise


# --------------------------------------------------------------------------- #
# plan: filter the artifact delta to genuinely-new, valid rows
# --------------------------------------------------------------------------- #
def plan_new_rows(delta_rows: list[dict[str, Any]], ledger_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    existing_ids = {str(event.get("ledger_record_id")) for event in load_ledger_events(ledger_dir)}
    last = last_observed_per_source(ledger_dir)
    new_rows: list[dict[str, Any]] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for row in delta_rows:
        record_id = str(row.get("ledger_record_id") or "")
        if record_id in existing_ids:
            continue  # idempotent: already committed
        if record_id in seen:
            reasons.append(f"duplicate_in_delta:{record_id}")
            continue
        seen.add(record_id)
        source_id = str(row.get("source_id") or "")
        observed_at = str(row.get("observed_at") or "")
        if source_id in last and observed_at < last[source_id]:
            reasons.append(f"out_of_order:{source_id}:{observed_at}<{last[source_id]}")
            continue
        new_rows.append(row)
    return new_rows, reasons


def summarize(new_rows: list[dict[str, Any]], filtered_text: str) -> dict[str, Any]:
    by_event_type: dict[str, int] = {}
    months: set[str] = set()
    for row in new_rows:
        by_event_type[str(row.get("event_type"))] = by_event_type.get(str(row.get("event_type")), 0) + 1
        months.add(month_key(str(row.get("observed_at"))))
    digest = "sha256:" + hashlib.sha256(filtered_text.encode("utf-8")).hexdigest()
    return {
        "schema_version": "0.1.0",
        "report_type": "observation_ledger_append_plan",
        "new_row_count": len(new_rows),
        "by_event_type": dict(sorted(by_event_type.items())),
        "affected_months": sorted(months),
        "filtered_delta_digest": digest,
        "not_advice": True,
    }


def run_plan(delta_path: Path, ledger_dir: Path, out_delta: Path, out_summary: Path) -> int:
    schema = load_record_schema()
    delta_rows = rows_from_lines(parse_ndjson(delta_path.read_text(encoding="utf-8")))
    new_rows, reasons = plan_new_rows(delta_rows, ledger_dir)
    reasons.extend(schema_violations(new_rows, schema, where="delta"))
    filtered_text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in new_rows)
    out_delta.write_text(filtered_text, encoding="utf-8")
    summary = summarize(new_rows, filtered_text)
    summary["reasons"] = reasons
    out_summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "reasons"}, indent=2, sort_keys=True))
    if reasons:
        for reason in reasons:
            print(f"reason={reason}")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# check: agent-automerge eligibility gate
# --------------------------------------------------------------------------- #
def check_observation_automerge(
    changed_paths: list[str],
    labels: list[str],
    base_ref: str,
    head_ref: str,
    *,
    loader: Callable[[str, str], str] = git_show,
    max_appended_rows: int = DEFAULT_MAX_APPENDED_ROWS,
    schema: dict[str, Any] | None = None,
) -> ObservationAutomergeResult:
    reasons: list[str] = []
    clean_labels = {label.strip() for label in labels if label.strip()}
    for required in (AUTOMERGE_OBSERVATION_LABEL, OBSERVATION_LEDGER_LABEL):
        if required not in clean_labels:
            reasons.append(f"missing_label:{required}")

    paths = [path.strip() for path in changed_paths if path.strip()]
    if not paths:
        return ObservationAutomergeResult(False, ("no_changed_paths",), 0)
    bad = [path for path in paths if not is_ledger_event_path(path)]
    reasons.extend(f"disallowed_path:{path}" for path in bad)

    schema = schema or load_record_schema()
    appended = 0
    for path in (p for p in paths if is_ledger_event_path(p)):
        try:
            base_text = _safe_git_show(loader, base_ref, path)
            head_text = loader(head_ref, path)
        except Exception as exc:  # noqa: BLE001 - eligibility fails closed
            reasons.append(f"ledger_load_failed:{path}:{type(exc).__name__}")
            continue
        new_lines, violations = append_only_new_lines(base_text, head_text)
        reasons.extend(f"{path}:{v}" for v in violations)
        try:
            new_rows = rows_from_lines(new_lines)
        except json.JSONDecodeError as exc:
            reasons.append(f"{path}:invalid_json:{exc}")
            continue
        reasons.extend(schema_violations(new_rows, schema, where=path))
        appended += len(new_rows)

    if appended == 0 and not reasons:
        reasons.append("no_appended_rows")
    if appended > max_appended_rows:
        reasons.append(f"appended_row_limit_exceeded:{appended}>{max_appended_rows}")

    return ObservationAutomergeResult(not reasons, tuple(reasons), appended)


def max_appended_rows_from_policy(path: str) -> int:
    import yaml

    try:
        policy = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return DEFAULT_MAX_APPENDED_ROWS
    return int((policy.get("observation") or {}).get("max_appended_rows", DEFAULT_MAX_APPENDED_ROWS))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-observation-automerge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="filter a delta to genuinely-new valid rows")
    plan.add_argument("--delta", type=Path, required=True)
    plan.add_argument("--ledger-dir", type=Path, default=ROOT / "maintenance" / "source-observations" / "events")
    plan.add_argument("--out-delta", type=Path, required=True)
    plan.add_argument("--out-summary", type=Path, required=True)

    check = subparsers.add_parser("check", help="agent-automerge eligibility gate")
    check.add_argument("--paths-file", required=True)
    check.add_argument("--labels", default="")
    check.add_argument("--base-ref", required=True)
    check.add_argument("--head-ref", required=True)
    check.add_argument("--policy", default="config/automerge-policy.yaml")

    args = parser.parse_args(argv)
    if args.command == "plan":
        return run_plan(args.delta, args.ledger_dir, args.out_delta, args.out_summary)

    paths = Path(args.paths_file).read_text(encoding="utf-8").splitlines()
    result = check_observation_automerge(
        paths,
        args.labels.split(","),
        args.base_ref,
        args.head_ref,
        max_appended_rows=max_appended_rows_from_policy(args.policy),
    )
    print(f"eligible={str(result.eligible).lower()}")
    print(f"appended_rows={result.appended_rows}")
    for reason in result.reasons:
        print(f"reason={reason}")
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
