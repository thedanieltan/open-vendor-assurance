"""WP38b rollback automerge lane.

The eligibility gate for the agent-automerge rollback job. A rollback PR may
merge only when it:

- carries the rollback lane labels;
- adds exactly one committed rollback decision (decision: rollback) whose
  not_before delay has passed and whose deciding bot differs from the discovery
  bot (reverser != author);
- appends to the machine-decision store WITHOUT rewriting history (every line
  present at the base revision is unchanged at the head);
- makes ONLY the catalog change that matches the rolled-back decision:
    * promote            -> the one subject vendor returns active -> machine_provisional (status-only),
    * materialize_provisional -> the one subject vendor's directory is fully removed,
    * quarantine         -> the one subject source returns quarantined -> not-quarantined (status-only, quarantine block dropped);
- touches nothing else beyond deterministic generated outputs.

Fails closed. The WP35 release gate is enforced separately by the workflow job.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Callable

import yaml

MARKER_LABEL = "rollback"
ROLLBACK_LABEL = "automerge:rollback"
DECISION_PREFIX = "maintenance/machine-decisions/"
GENERATED_EXACT = {"openva-pack.json"}
GENERATED_PREFIXES = ("indexes/", "dist/")

VENDOR_STATUS_ONLY_FIELDS = {"catalog_status", "machine_decision_id", "reversal"}
SOURCE_STATUS_ONLY_FIELDS = {"review_state", "quarantine"}


@dataclass(frozen=True)
class RollbackResult:
    eligible: bool
    reasons: tuple[str, ...]
    subject_id: str | None = None


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def is_vendor_yaml(path: str) -> str | None:
    p = _parts(path)
    if len(p) == 4 and p[0] == "data" and p[1] == "vendors" and p[3] == "vendor.yaml":
        return p[2]
    return None


def is_source_yaml(path: str) -> str | None:
    p = _parts(path)
    if len(p) == 5 and p[0] == "data" and p[1] == "vendors" and p[3] == "sources" and p[4].endswith(".yaml"):
        return p[2]  # vendor_id
    return None


def vendor_of(path: str) -> str | None:
    p = _parts(path)
    if len(p) >= 3 and p[0] == "data" and p[1] == "vendors":
        return p[2]
    return None


def is_decision_path(path: str) -> bool:
    return path.startswith(DECISION_PREFIX) and path.endswith(".ndjson")


def is_generated_path(path: str) -> bool:
    return path in GENERATED_EXACT or any(path.startswith(prefix) for prefix in GENERATED_PREFIXES)


def _load_lines(loader: Callable[[str, str], str], ref: str, path: str) -> list[str] | None:
    try:
        return [ln for ln in loader(ref, path).splitlines() if ln.strip()]
    except subprocess.CalledProcessError:
        return None


def append_only_violations(loader: Callable[[str, str], str], base_ref: str, head_ref: str, decision_paths: list[str]) -> list[str]:
    """Every decision line present at base must be unchanged at head."""
    reasons: list[str] = []
    for path in decision_paths:
        base_lines = _load_lines(loader, base_ref, path) or []
        head_lines = _load_lines(loader, head_ref, path)
        if head_lines is None:
            reasons.append(f"decision_file_removed:{path}")
            continue
        if head_lines[: len(base_lines)] != base_lines:
            reasons.append(f"decision_history_rewritten:{path}")
    return reasons


def new_rollback_decisions(loader, head_ref, base_ref, decision_paths) -> list[dict[str, Any]]:
    base_ids: set[str] = set()
    for path in decision_paths:
        for line in _load_lines(loader, base_ref, path) or []:
            base_ids.add(str(json.loads(line).get("decision_id")))
    new_records: list[dict[str, Any]] = []
    for path in decision_paths:
        for line in _load_lines(loader, head_ref, path) or []:
            record = json.loads(line)
            if str(record.get("decision_id")) not in base_ids and record.get("decision") == "rollback":
                new_records.append(record)
    return new_records


def status_only_reasons(base: dict[str, Any], head: dict[str, Any], allowed: set[str]) -> list[str]:
    reasons: list[str] = []
    for key in sorted((set(base) | set(head)) - allowed):
        if base.get(key) != head.get(key):
            reasons.append(f"non_status_field_changed:{key}")
    return reasons


def check_rollback_automerge(
    changed_paths: list[str],
    labels: list[str],
    base_ref: str,
    head_ref: str,
    *,
    loader: Callable[[str, str], str] = git_show,
    now: datetime | None = None,
) -> RollbackResult:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    clean_labels = {label.strip() for label in labels if label.strip()}
    for required in (MARKER_LABEL, ROLLBACK_LABEL):
        if required not in clean_labels:
            reasons.append(f"missing_label:{required}")

    paths = [p.strip() for p in changed_paths if p.strip()]
    if not paths:
        return RollbackResult(False, ("no_changed_paths",))

    vendor_yaml_paths: set[str] = set()
    source_paths: set[str] = set()
    vendor_subtree: set[str] = set()
    decision_paths: list[str] = []
    for path in paths:
        if is_decision_path(path):
            decision_paths.append(path)
        elif is_generated_path(path):
            continue
        elif is_vendor_yaml(path):
            vendor_yaml_paths.add(path)
            vendor_subtree.add(is_vendor_yaml(path))
        elif is_source_yaml(path):
            source_paths.add(path)
        elif vendor_of(path):
            vendor_subtree.add(vendor_of(path))
        else:
            reasons.append(f"disallowed_path:{path}")

    if not decision_paths:
        return RollbackResult(False, tuple(reasons + ["missing_rollback_decision_record"]))
    reasons.extend(append_only_violations(loader, base_ref, head_ref, decision_paths))

    records = new_rollback_decisions(loader, head_ref, base_ref, decision_paths)
    if len(records) != 1:
        return RollbackResult(False, tuple(reasons + [f"expected_exactly_one_rollback_decision:{len(records)}"]))
    decision = records[0]
    subject_id = str(decision.get("subject_id") or "")
    rolled_back = str((decision.get("evidence") or {}).get("rolled_back_decision") or "")

    deciding = decision.get("deciding_bot")
    discovery = decision.get("discovery_bot")
    if deciding and discovery and deciding == discovery:
        reasons.append("separation_of_duty:reverser == author")
    not_before = decision.get("not_before")
    if not not_before:
        reasons.append("decision_missing_not_before")
    else:
        try:
            if now < datetime.fromisoformat(str(not_before).replace("Z", "+00:00")):
                reasons.append(f"not_before_not_passed:{not_before}")
        except ValueError:
            reasons.append("not_before_unparseable")

    if rolled_back == "promote":
        reasons.extend(_check_promotion_rollback(loader, base_ref, head_ref, subject_id, vendor_yaml_paths, source_paths, vendor_subtree))
    elif rolled_back == "quarantine":
        reasons.extend(_check_quarantine_rollback(loader, base_ref, head_ref, subject_id, vendor_yaml_paths, source_paths))
    elif rolled_back == "materialize_provisional":
        reasons.extend(_check_materialization_rollback(loader, base_ref, head_ref, subject_id, vendor_subtree, vendor_yaml_paths, source_paths))
    else:
        reasons.append(f"unsupported_rolled_back_decision:{rolled_back}")

    return RollbackResult(not reasons, tuple(reasons), subject_id)


def _check_promotion_rollback(loader, base_ref, head_ref, vendor_id, vendor_yaml_paths, source_paths, vendor_subtree) -> list[str]:
    reasons: list[str] = []
    if source_paths:
        reasons.append("unexpected_source_change_for_promotion_rollback")
    if vendor_subtree - {vendor_id}:
        reasons.append(f"unexpected_vendor_touched:{sorted(vendor_subtree - {vendor_id})}")
    expected = f"data/vendors/{vendor_id}/vendor.yaml"
    if vendor_yaml_paths != {expected}:
        return reasons + [f"expected_only_subject_vendor_yaml:{sorted(vendor_yaml_paths)}"]
    base = yaml.safe_load(loader(base_ref, expected))
    head = yaml.safe_load(loader(head_ref, expected))
    if base.get("catalog_status") != "active":
        reasons.append(f"base_not_active:{base.get('catalog_status')}")
    if head.get("catalog_status") != "machine_provisional":
        reasons.append(f"head_not_machine_provisional:{head.get('catalog_status')}")
    reasons.extend(status_only_reasons(base, head, VENDOR_STATUS_ONLY_FIELDS))
    return reasons


def _check_quarantine_rollback(loader, base_ref, head_ref, source_id, vendor_yaml_paths, source_paths) -> list[str]:
    reasons: list[str] = []
    if vendor_yaml_paths:
        reasons.append("unexpected_vendor_change_for_quarantine_rollback")
    if len(source_paths) != 1:
        return reasons + [f"expected_exactly_one_source:{sorted(source_paths)}"]
    spath = next(iter(source_paths))
    base = yaml.safe_load(loader(base_ref, spath))
    head = yaml.safe_load(loader(head_ref, spath))
    if str(head.get("source_id")) != source_id:
        reasons.append("source_subject_mismatch")
    if base.get("review_state") != "quarantined":
        reasons.append(f"base_not_quarantined:{base.get('review_state')}")
    if head.get("review_state") == "quarantined":
        reasons.append("head_still_quarantined")
    if "quarantine" in head:
        reasons.append("head_quarantine_block_not_removed")
    reasons.extend(status_only_reasons(base, head, SOURCE_STATUS_ONLY_FIELDS))
    return reasons


def _check_materialization_rollback(loader, base_ref, head_ref, vendor_id, vendor_subtree, vendor_yaml_paths, source_paths) -> list[str]:
    reasons: list[str] = []
    if vendor_subtree - {vendor_id}:
        reasons.append(f"unexpected_vendor_touched:{sorted(vendor_subtree - {vendor_id})}")
    # The subject vendor must exist at base as a machine_provisional, machine-
    # generated vendor and be ABSENT at head.
    vpath = f"data/vendors/{vendor_id}/vendor.yaml"
    try:
        base = yaml.safe_load(loader(base_ref, vpath))
    except subprocess.CalledProcessError:
        return reasons + [f"vendor_absent_at_base:{vendor_id}"]
    if base.get("machine_generated") is not True:
        reasons.append("base_vendor_not_machine_generated")
    if base.get("catalog_status") != "machine_provisional":
        reasons.append(f"base_vendor_not_machine_provisional:{base.get('catalog_status')}")
    try:
        loader(head_ref, vpath)
        reasons.append("vendor_still_present_at_head")
    except subprocess.CalledProcessError:
        pass  # absent at head: correct
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-rollback-automerge")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--paths-file", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    paths = open(args.paths_file, encoding="utf-8").read().splitlines()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    result = check_rollback_automerge(paths, args.labels.split(","), args.base_ref, args.head_ref, now=now)
    print(f"eligible={str(result.eligible).lower()}")
    print(f"subject_id={result.subject_id}")
    for reason in result.reasons:
        print(f"reason={reason}")
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
