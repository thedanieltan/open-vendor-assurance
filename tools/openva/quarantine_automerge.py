"""WP38a quarantine automerge lane.

The eligibility gate for the agent-automerge quarantine job. A quarantine PR may
merge only when it:

- changes ONLY a single EXISTING source record
  (data/vendors/<vendor>/sources/<source>.yaml), its linked quarantine decision
  record (maintenance/machine-decisions/**), and deterministic generated outputs
  (indexes/, dist/, openva-pack.json) — it must NOT add, remove, or edit any
  other source, vendor, artifact, or change record;
- transitions that one source's review_state to `quarantined` (it was not
  quarantined at the base revision), changing ONLY the status-only quarantine
  fields (review_state, quarantine) — every other field is byte-for-byte
  unchanged;
- carries a quarantine block whose reversal method is revert_quarantine;
- links a committed quarantine decision (decision: quarantine) whose subject is
  the source, whose deciding bot differs from the discovery bot, and whose
  not_before delay has passed;
- carries the quarantine lane labels.

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

MARKER_LABEL = "quarantine"
QUARANTINE_LABEL = "automerge:quarantine"
DECISION_PREFIX = "maintenance/machine-decisions/"
GENERATED_EXACT = {"openva-pack.json"}
GENERATED_PREFIXES = ("indexes/", "dist/")

# Only these source fields may differ between base and head (status-only).
STATUS_ONLY_FIELDS = {"review_state", "quarantine"}


@dataclass(frozen=True)
class QuarantineResult:
    eligible: bool
    reasons: tuple[str, ...]
    source_id: str | None = None


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def source_file_path(path: str) -> str | None:
    """Return the path only if it is data/vendors/<vendor>/sources/<source>.yaml."""
    parts = PurePosixPath(path).parts
    if len(parts) == 5 and parts[0] == "data" and parts[1] == "vendors" and parts[3] == "sources" and parts[4].endswith(".yaml"):
        return path
    return None


def is_vendor_subtree(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) >= 3 and parts[0] == "data" and parts[1] == "vendors"


def is_decision_path(path: str) -> bool:
    return path.startswith(DECISION_PREFIX) and path.endswith(".ndjson")


def is_generated_path(path: str) -> bool:
    return path in GENERATED_EXACT or any(path.startswith(prefix) for prefix in GENERATED_PREFIXES)


def load_decisions_from_changed(loader: Callable[[str, str], str], head_ref: str, decision_paths: list[str]) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for path in decision_paths:
        for line in loader(head_ref, path).splitlines():
            line = line.strip()
            if line:
                record = json.loads(line)
                decisions[str(record.get("decision_id"))] = record
    return decisions


def status_only_diff_reasons(base_source: dict[str, Any], head_source: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    keys = set(base_source) | set(head_source)
    for key in sorted(keys - STATUS_ONLY_FIELDS):
        if base_source.get(key) != head_source.get(key):
            reasons.append(f"non_status_field_changed:{key}")
    return reasons


def check_quarantine_automerge(
    changed_paths: list[str],
    labels: list[str],
    base_ref: str,
    head_ref: str,
    *,
    loader: Callable[[str, str], str] = git_show,
    now: datetime | None = None,
) -> QuarantineResult:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    clean_labels = {label.strip() for label in labels if label.strip()}
    for required in (MARKER_LABEL, QUARANTINE_LABEL):
        if required not in clean_labels:
            reasons.append(f"missing_label:{required}")

    paths = [path.strip() for path in changed_paths if path.strip()]
    if not paths:
        return QuarantineResult(False, ("no_changed_paths",))

    source_paths: set[str] = set()
    decision_paths: list[str] = []
    for path in paths:
        sfile = source_file_path(path)
        if sfile:
            source_paths.add(sfile)
        elif is_vendor_subtree(path):
            reasons.append(f"non_source_vendor_path:{path}")
        elif is_decision_path(path):
            decision_paths.append(path)
        elif is_generated_path(path):
            continue
        else:
            reasons.append(f"disallowed_path:{path}")

    if len(source_paths) != 1:
        reasons.append(f"expected_exactly_one_source:{sorted(source_paths)}")
        return QuarantineResult(False, tuple(reasons))
    source_path = next(iter(source_paths))

    if not decision_paths:
        reasons.append("missing_quarantine_decision_record")

    try:
        base_source = yaml.safe_load(loader(base_ref, source_path))
    except subprocess.CalledProcessError:
        return QuarantineResult(False, tuple(reasons + ["source_absent_at_base"]), None)
    try:
        head_source = yaml.safe_load(loader(head_ref, source_path))
    except Exception as exc:  # noqa: BLE001 - fail closed
        return QuarantineResult(False, tuple(reasons + [f"head_source_load_failed:{type(exc).__name__}"]), None)
    if not isinstance(base_source, dict) or not isinstance(head_source, dict):
        return QuarantineResult(False, tuple(reasons + ["source_not_mapping"]), None)

    source_id = str(head_source.get("source_id") or "")

    if base_source.get("review_state") == "quarantined":
        reasons.append("base_already_quarantined")
    if head_source.get("review_state") != "quarantined":
        reasons.append(f"head_review_state_not_quarantined:{head_source.get('review_state')}")
    reasons.extend(status_only_diff_reasons(base_source, head_source))

    quarantine = head_source.get("quarantine") or {}
    if (quarantine.get("reversal") or {}).get("method") != "revert_quarantine":
        reasons.append("head_reversal_method_not_revert_quarantine")
    decision_id = quarantine.get("decision_id")
    if not decision_id:
        reasons.append("source_missing_quarantine_decision_id")

    if decision_paths and decision_id:
        try:
            decisions = load_decisions_from_changed(loader, head_ref, decision_paths)
        except Exception as exc:  # noqa: BLE001 - fail closed
            return QuarantineResult(False, tuple(reasons + [f"decision_load_failed:{type(exc).__name__}"]), source_id)
        decision = decisions.get(str(decision_id))
        if decision is None:
            reasons.append(f"quarantine_decision_not_found:{decision_id}")
        else:
            if decision.get("decision") != "quarantine":
                reasons.append(f"unexpected_decision:{decision.get('decision')}")
            if decision.get("subject_id") != source_id:
                reasons.append("decision_subject_mismatch")
            deciding = decision.get("deciding_bot")
            discovery = decision.get("discovery_bot")
            if deciding and discovery and deciding == discovery:
                reasons.append("separation_of_duty:deciding_bot == discovery_bot")
            not_before = decision.get("not_before")
            if not not_before:
                reasons.append("decision_missing_not_before")
            else:
                try:
                    not_before_dt = datetime.fromisoformat(str(not_before).replace("Z", "+00:00"))
                    if now < not_before_dt:
                        reasons.append(f"not_before_not_passed:{not_before}")
                except ValueError:
                    reasons.append("not_before_unparseable")

    return QuarantineResult(not reasons, tuple(reasons), source_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-quarantine-automerge")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--paths-file", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    paths = open(args.paths_file, encoding="utf-8").read().splitlines()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    result = check_quarantine_automerge(paths, args.labels.split(","), args.base_ref, args.head_ref, now=now)
    print(f"eligible={str(result.eligible).lower()}")
    print(f"source_id={result.source_id}")
    for reason in result.reasons:
        print(f"reason={reason}")
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
