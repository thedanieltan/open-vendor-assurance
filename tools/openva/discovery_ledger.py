"""Append-only discovery event ledger.

Discovery remains report-only. This module is the separate executor used by
path-restricted PR lanes to append discovery-event deltas under
maintenance/discovery-events/*.ndjson.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.openva.indexes import ROOT

DEFAULT_LEDGER_DIR = ROOT / "maintenance" / "discovery-events"
MAX_APPEND_COUNT = 500
HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
EVENT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
DISCOVERY_LEDGER_LABEL = "discovery-ledger"
AUTOMERGE_OBSERVATION_LABEL = "automerge:observation"
DISCOVERY_LEDGER_WORK_PACKAGE = "WP-DISCOVERY-LEDGER-APPEND-01"
LEDGER_EVENTS_PREFIX = "maintenance/discovery-events/"
LEDGER_FILE_RE = re.compile(r"^maintenance/discovery-events/\d{4}-\d{2}\.ndjson$")
DISCOVERY_LEDGER_TITLE_RE = re.compile(r"^Discovery ledger: append events run \d+$")


@dataclass(frozen=True)
class DiscoveryAutomergeResult:
    eligible: bool
    reasons: tuple[str, ...]
    appended_rows: int = 0


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def git_list_ledger_paths(ref: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", LEDGER_EVENTS_PREFIX.rstrip("/")],
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def is_discovery_ledger_path(path: str) -> bool:
    return bool(LEDGER_FILE_RE.fullmatch(path.strip()))


def parse_ndjson(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def rows_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("expected NDJSON object rows")
        rows.append(value)
    return rows


def append_only_new_lines(base_text: str | None, head_text: str) -> tuple[list[str], list[str]]:
    head_lines = parse_ndjson(head_text)
    base_lines = parse_ndjson(base_text) if base_text is not None else []
    if head_lines[: len(base_lines)] != base_lines:
        return [], ["not_append_only:existing_lines_modified_or_removed"]
    return head_lines[len(base_lines):], []


def _safe_git_show(loader: Callable[[str, str], str], ref: str, path: str) -> str | None:
    try:
        return loader(ref, path)
    except subprocess.CalledProcessError:
        return None


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
        "vendor_id",
        "source_type",
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


def _body_declares_work_package(body: str, work_package: str) -> bool:
    return bool(re.search(rf"(?m)^Work-Package:\s*{re.escape(work_package)}\s*$", body or ""))


def _prohibited_terms() -> list[str]:
    import yaml

    config = ROOT / "config" / "prohibited-claims.yaml"
    try:
        policy = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return []
    return [str(term).lower() for term in policy.get("prohibited_terms", []) or []]


def _field_exempt(field_name: str) -> bool:
    return field_name.endswith(("_id", "_ids", "_url", "_urls"))


def advisory_violations(event: dict[str, Any], *, terms: list[str] | None = None) -> list[str]:
    blocked = terms if terms is not None else _prohibited_terms()
    reasons: list[str] = []

    def visit(value: Any, field_name: str) -> None:
        if _field_exempt(field_name):
            return
        if isinstance(value, str):
            lower = value.lower()
            for term in blocked:
                if term and term in lower:
                    reasons.append(f"advisory_term:{field_name}:{term}")
        elif isinstance(value, list):
            for item in value:
                visit(item, field_name)
        elif isinstance(value, dict):
            for key, item in value.items():
                visit(item, str(key))

    for key, value in event.items():
        visit(value, str(key))
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


def load_committed_event_ids(
    base_ref: str,
    *,
    loader: Callable[[str, str], str] = git_show,
    list_paths: Callable[[str], list[str]] = git_list_ledger_paths,
) -> set[str]:
    ids: set[str] = set()
    for path in list_paths(base_ref):
        if not is_discovery_ledger_path(path):
            continue
        for row in rows_from_lines(parse_ndjson(loader(base_ref, path))):
            event_id = row.get("discovery_event_id")
            if event_id:
                ids.add(str(event_id))
    return ids


def check_discovery_automerge(
    changed_paths: list[str],
    labels: list[str],
    base_ref: str,
    head_ref: str,
    *,
    head_branch: str | None = None,
    title: str | None = None,
    body: str | None = None,
    loader: Callable[[str, str], str] = git_show,
    list_paths: Callable[[str], list[str]] = git_list_ledger_paths,
    committed_event_ids: set[str] | None = None,
    max_appended_rows: int = MAX_APPEND_COUNT,
) -> DiscoveryAutomergeResult:
    reasons: list[str] = []
    clean_labels = {label.strip() for label in labels if label.strip()}
    for required in (DISCOVERY_LEDGER_LABEL, AUTOMERGE_OBSERVATION_LABEL):
        if required not in clean_labels:
            reasons.append(f"missing_label:{required}")
    if head_branch is not None and not head_branch.startswith("agent-discovery-ledger-append-"):
        reasons.append(f"head_branch_not_discovery_ledger:{head_branch}")
    if title is not None and not DISCOVERY_LEDGER_TITLE_RE.fullmatch(title):
        reasons.append(f"title_not_discovery_ledger:{title}")
    if body is not None and not _body_declares_work_package(body, DISCOVERY_LEDGER_WORK_PACKAGE):
        reasons.append(f"missing_work_package:{DISCOVERY_LEDGER_WORK_PACKAGE}")

    paths = [path.strip() for path in changed_paths if path.strip()]
    if not paths:
        return DiscoveryAutomergeResult(False, ("no_changed_paths",), 0)
    bad_paths = [path for path in paths if not is_discovery_ledger_path(path)]
    reasons.extend(f"disallowed_path:{path}" for path in bad_paths)

    new_rows: list[dict[str, Any]] = []
    advisory_terms = _prohibited_terms()
    for path in (path for path in paths if is_discovery_ledger_path(path)):
        try:
            base_text = _safe_git_show(loader, base_ref, path)
            head_text = loader(head_ref, path)
        except Exception as exc:  # noqa: BLE001 - eligibility fails closed
            reasons.append(f"ledger_load_failed:{path}:{type(exc).__name__}")
            continue
        new_lines, violations = append_only_new_lines(base_text, head_text)
        reasons.extend(f"{path}:{violation}" for violation in violations)
        try:
            rows = rows_from_lines(new_lines)
        except (json.JSONDecodeError, ValueError) as exc:
            reasons.append(f"{path}:invalid_json:{exc}")
            continue
        for index, row in enumerate(rows):
            event_reasons = validate_event(row) + advisory_violations(row, terms=advisory_terms)
            reasons.extend(f"{path}[{index}]:{reason}" for reason in event_reasons)
        new_rows.extend(rows)

    appended = len(new_rows)
    new_ids = [str(row.get("discovery_event_id") or "") for row in new_rows]
    duplicate_delta_ids = sorted(event_id for event_id, count in Counter(new_ids).items() if event_id and count > 1)
    if duplicate_delta_ids:
        reasons.append("duplicate_delta_event_id:" + ",".join(duplicate_delta_ids))

    try:
        existing_ids = (
            committed_event_ids
            if committed_event_ids is not None
            else load_committed_event_ids(base_ref, loader=loader, list_paths=list_paths)
        )
    except Exception as exc:  # noqa: BLE001 - eligibility fails closed
        reasons.append(f"committed_ledger_load_failed:{type(exc).__name__}")
        existing_ids = set()
    duplicate_existing_ids = sorted(existing_ids & set(new_ids))
    if duplicate_existing_ids:
        reasons.append("duplicate_existing_event_id:" + ",".join(duplicate_existing_ids))

    if appended == 0 and not reasons:
        reasons.append("no_appended_rows")
    if appended > max_appended_rows:
        reasons.append(f"appended_row_limit_exceeded:{appended}>{max_appended_rows}")

    return DiscoveryAutomergeResult(not reasons, tuple(reasons), appended)


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
    check = subparsers.add_parser("check", help="agent-automerge eligibility gate")
    check.add_argument("--paths-file", required=True)
    check.add_argument("--labels", default="")
    check.add_argument("--head-branch", default=None)
    check.add_argument("--title", default=None)
    check.add_argument("--body-file", type=Path, default=None)
    check.add_argument("--base-ref", required=True)
    check.add_argument("--head-ref", required=True)
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
    if args.command == "check":
        paths = Path(args.paths_file).read_text(encoding="utf-8").splitlines()
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else None
        result = check_discovery_automerge(
            paths,
            args.labels.split(","),
            args.base_ref,
            args.head_ref,
            head_branch=args.head_branch,
            title=args.title,
            body=body,
        )
        print(f"eligible={str(result.eligible).lower()}")
        print(f"appended_rows={result.appended_rows}")
        for reason in result.reasons:
            print(f"reason={reason}")
        return 0 if result.eligible else 1
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
