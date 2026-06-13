"""WP36b machine-provisional vendor automerge lane.

The eligibility gate for the agent-automerge machine-provisional job. A
materialization PR may merge only when it:

- changes ONLY a single NEW vendor directory (data/vendors/<id>/**), its linked
  machine decision record (maintenance/machine-decisions/**), and deterministic
  generated outputs (indexes/, dist/, openva-pack.json);
- does NOT modify an existing vendor (the vendor directory must be absent at the
  base revision);
- writes the vendor as catalog_status: machine_provisional with machine
  provenance and a reversal reference;
- links a committed machine decision record whose deciding bot differs from the
  discovery bot (separation of duties) and whose not_before delay has passed;
- carries the machine-provisional lane labels.

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

MACHINE_PROVISIONAL_LABEL = "automerge:machine-provisional"
MARKER_LABEL = "machine-provisional"
DECISION_PREFIX = "maintenance/machine-decisions/"
GENERATED_EXACT = {"openva-pack.json"}
GENERATED_PREFIXES = ("indexes/", "dist/")


@dataclass(frozen=True)
class MachineProvisionalResult:
    eligible: bool
    reasons: tuple[str, ...]
    vendor_id: str | None = None


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def is_vendor_path(path: str) -> str | None:
    """Return the vendor_id if path is under data/vendors/<id>/, else None."""
    parts = PurePosixPath(path).parts
    if len(parts) >= 4 and parts[0] == "data" and parts[1] == "vendors" and parts[2]:
        return parts[2]
    return None


def is_decision_path(path: str) -> bool:
    return path.startswith(DECISION_PREFIX) and path.endswith(".ndjson")


def is_generated_path(path: str) -> bool:
    return path in GENERATED_EXACT or any(path.startswith(prefix) for prefix in GENERATED_PREFIXES)


def vendor_exists_at_base(loader: Callable[[str, str], str], base_ref: str, vendor_id: str) -> bool:
    try:
        loader(base_ref, f"data/vendors/{vendor_id}/vendor.yaml")
        return True
    except subprocess.CalledProcessError:
        return False


def load_decisions_from_changed(
    loader: Callable[[str, str], str],
    head_ref: str,
    decision_paths: list[str],
) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for path in decision_paths:
        for line in loader(head_ref, path).splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            decisions[str(record.get("decision_id"))] = record
    return decisions


def check_machine_provisional_automerge(
    changed_paths: list[str],
    labels: list[str],
    base_ref: str,
    head_ref: str,
    *,
    loader: Callable[[str, str], str] = git_show,
    now: datetime | None = None,
) -> MachineProvisionalResult:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    clean_labels = {label.strip() for label in labels if label.strip()}
    for required in (MARKER_LABEL, MACHINE_PROVISIONAL_LABEL):
        if required not in clean_labels:
            reasons.append(f"missing_label:{required}")

    paths = [path.strip() for path in changed_paths if path.strip()]
    if not paths:
        return MachineProvisionalResult(False, ("no_changed_paths",))

    vendor_ids: set[str] = set()
    decision_paths: list[str] = []
    for path in paths:
        vendor_id = is_vendor_path(path)
        if vendor_id:
            vendor_ids.add(vendor_id)
        elif is_decision_path(path):
            decision_paths.append(path)
        elif is_generated_path(path):
            continue
        else:
            reasons.append(f"disallowed_path:{path}")

    if len(vendor_ids) != 1:
        reasons.append(f"expected_exactly_one_new_vendor:{sorted(vendor_ids)}")
        return MachineProvisionalResult(False, tuple(reasons))
    vendor_id = next(iter(vendor_ids))

    if not decision_paths:
        reasons.append("missing_machine_decision_record")

    # The vendor must be NEW: absent at the base revision.
    if vendor_exists_at_base(loader, base_ref, vendor_id):
        reasons.append(f"vendor_already_exists:{vendor_id}")

    # Load and validate the head vendor record.
    try:
        vendor = yaml.safe_load(loader(head_ref, f"data/vendors/{vendor_id}/vendor.yaml"))
    except Exception as exc:  # noqa: BLE001 - fail closed
        return MachineProvisionalResult(False, tuple(reasons + [f"vendor_load_failed:{type(exc).__name__}"]), vendor_id)
    if not isinstance(vendor, dict):
        return MachineProvisionalResult(False, tuple(reasons + ["vendor_not_mapping"]), vendor_id)
    if vendor.get("catalog_status") != "machine_provisional":
        reasons.append(f"catalog_status_not_machine_provisional:{vendor.get('catalog_status')}")
    if vendor.get("machine_generated") is not True:
        reasons.append("vendor_not_marked_machine_generated")
    decision_id = vendor.get("machine_decision_id")
    if not decision_id:
        reasons.append("vendor_missing_machine_decision_id")
    if not (vendor.get("reversal") or {}).get("method"):
        reasons.append("vendor_missing_reversal")

    # Validate the linked decision record.
    if decision_paths and decision_id:
        try:
            decisions = load_decisions_from_changed(loader, head_ref, decision_paths)
        except Exception as exc:  # noqa: BLE001 - fail closed
            return MachineProvisionalResult(False, tuple(reasons + [f"decision_load_failed:{type(exc).__name__}"]), vendor_id)
        decision = decisions.get(str(decision_id))
        if decision is None:
            reasons.append(f"decision_record_not_found:{decision_id}")
        else:
            if decision.get("subject_id") != vendor_id:
                reasons.append("decision_subject_mismatch")
            if decision.get("decision") != "materialize_provisional":
                reasons.append(f"unexpected_decision:{decision.get('decision')}")
            if decision.get("deciding_bot") == decision.get("discovery_bot"):
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

    return MachineProvisionalResult(not reasons, tuple(reasons), vendor_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-machine-provisional-automerge")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--paths-file", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    paths = open(args.paths_file, encoding="utf-8").read().splitlines()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    result = check_machine_provisional_automerge(
        paths, args.labels.split(","), args.base_ref, args.head_ref, now=now
    )
    print(f"eligible={str(result.eligible).lower()}")
    print(f"vendor_id={result.vendor_id}")
    for reason in result.reasons:
        print(f"reason={reason}")
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
