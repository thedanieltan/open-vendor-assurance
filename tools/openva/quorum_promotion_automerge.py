"""WP37 quorum-promotion automerge lane.

The eligibility gate for the agent-automerge quorum-promotion job. A promotion
PR may merge only when it:

- changes ONLY a single EXISTING vendor's lifecycle record
  (data/vendors/<id>/vendor.yaml), its linked promotion decision record
  (maintenance/machine-decisions/**), and deterministic generated outputs
  (indexes/, dist/, openva-pack.json) — it must NOT add, remove, or edit any
  source, artifact, or change record, and must not touch another vendor;
- transitions that one vendor from catalog_status machine_provisional (at the
  base revision) to active (at the head revision), changing ONLY the status-only
  lifecycle fields (catalog_status, machine_decision_id, reversal) — every other
  field is byte-for-byte unchanged;
- carries a reversal reference whose method is revert_promotion;
- links a committed promotion decision (decision: promote) whose subject is the
  vendor, whose deciding bot differs from the discovery bot, that is not
  supported solely by the deciding bot, that carries the configured minimum of
  independent supporting bots, and whose not_before delay has passed;
- carries the quorum-promotion lane labels.

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

MARKER_LABEL = "quorum-promotion"
QUORUM_PROMOTION_LABEL = "automerge:quorum-promotion"
DECISION_PREFIX = "maintenance/machine-decisions/"
GENERATED_EXACT = {"openva-pack.json"}
GENERATED_PREFIXES = ("indexes/", "dist/")

# Only these vendor fields may differ between base and head (status-only).
STATUS_ONLY_FIELDS = {"catalog_status", "machine_decision_id", "reversal"}
DEFAULT_MIN_INDEPENDENT_SUPPORTING_BOTS = 2


@dataclass(frozen=True)
class QuorumPromotionResult:
    eligible: bool
    reasons: tuple[str, ...]
    vendor_id: str | None = None


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def vendor_lifecycle_id(path: str) -> str | None:
    """Return the vendor_id only if path is exactly data/vendors/<id>/vendor.yaml."""
    parts = PurePosixPath(path).parts
    if len(parts) == 4 and parts[0] == "data" and parts[1] == "vendors" and parts[3] == "vendor.yaml":
        return parts[2]
    return None


def is_vendor_subtree(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if len(parts) >= 4 and parts[0] == "data" and parts[1] == "vendors" and parts[2]:
        return parts[2]
    return None


def is_decision_path(path: str) -> bool:
    return path.startswith(DECISION_PREFIX) and path.endswith(".ndjson")


def is_generated_path(path: str) -> bool:
    return path in GENERATED_EXACT or any(path.startswith(prefix) for prefix in GENERATED_PREFIXES)


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


def status_only_diff_reasons(base_vendor: dict[str, Any], head_vendor: dict[str, Any]) -> list[str]:
    """Every field outside STATUS_ONLY_FIELDS must be byte-identical."""
    reasons: list[str] = []
    keys = set(base_vendor) | set(head_vendor)
    for key in sorted(keys - STATUS_ONLY_FIELDS):
        if base_vendor.get(key) != head_vendor.get(key):
            reasons.append(f"non_status_field_changed:{key}")
    return reasons


def min_independent_supporting_bots() -> int:
    try:
        from tools.openva.quorum_promotion import load_thresholds

        return int(load_thresholds().get("min_independent_supporting_modules", DEFAULT_MIN_INDEPENDENT_SUPPORTING_BOTS))
    except Exception:  # noqa: BLE001 - fail safe to the constitutional floor
        return DEFAULT_MIN_INDEPENDENT_SUPPORTING_BOTS


def check_quorum_promotion_automerge(
    changed_paths: list[str],
    labels: list[str],
    base_ref: str,
    head_ref: str,
    *,
    loader: Callable[[str, str], str] = git_show,
    now: datetime | None = None,
) -> QuorumPromotionResult:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    clean_labels = {label.strip() for label in labels if label.strip()}
    for required in (MARKER_LABEL, QUORUM_PROMOTION_LABEL):
        if required not in clean_labels:
            reasons.append(f"missing_label:{required}")

    paths = [path.strip() for path in changed_paths if path.strip()]
    if not paths:
        return QuorumPromotionResult(False, ("no_changed_paths",))

    vendor_ids: set[str] = set()
    decision_paths: list[str] = []
    for path in paths:
        lifecycle_id = vendor_lifecycle_id(path)
        if lifecycle_id:
            vendor_ids.add(lifecycle_id)
        elif is_vendor_subtree(path):
            # A non-vendor.yaml file under data/vendors/<id>/ is a non-status
            # change (source, artifact, or change record) -> reject.
            reasons.append(f"non_status_only_vendor_path:{path}")
        elif is_decision_path(path):
            decision_paths.append(path)
        elif is_generated_path(path):
            continue
        else:
            reasons.append(f"disallowed_path:{path}")

    if len(vendor_ids) != 1:
        reasons.append(f"expected_exactly_one_vendor:{sorted(vendor_ids)}")
        return QuorumPromotionResult(False, tuple(reasons))
    vendor_id = next(iter(vendor_ids))

    if not decision_paths:
        reasons.append("missing_promotion_decision_record")

    vendor_path = f"data/vendors/{vendor_id}/vendor.yaml"
    try:
        base_vendor = yaml.safe_load(loader(base_ref, vendor_path))
    except subprocess.CalledProcessError:
        return QuorumPromotionResult(False, tuple(reasons + [f"vendor_absent_at_base:{vendor_id}"]), vendor_id)
    try:
        head_vendor = yaml.safe_load(loader(head_ref, vendor_path))
    except Exception as exc:  # noqa: BLE001 - fail closed
        return QuorumPromotionResult(False, tuple(reasons + [f"head_vendor_load_failed:{type(exc).__name__}"]), vendor_id)
    if not isinstance(base_vendor, dict) or not isinstance(head_vendor, dict):
        return QuorumPromotionResult(False, tuple(reasons + ["vendor_not_mapping"]), vendor_id)

    if base_vendor.get("catalog_status") != "machine_provisional":
        reasons.append(f"base_status_not_machine_provisional:{base_vendor.get('catalog_status')}")
    if head_vendor.get("catalog_status") != "active":
        reasons.append(f"head_status_not_active:{head_vendor.get('catalog_status')}")
    reasons.extend(status_only_diff_reasons(base_vendor, head_vendor))

    if (head_vendor.get("reversal") or {}).get("method") != "revert_promotion":
        reasons.append("head_reversal_method_not_revert_promotion")

    decision_id = head_vendor.get("machine_decision_id")
    if not decision_id:
        reasons.append("vendor_missing_machine_decision_id")

    if decision_paths and decision_id:
        try:
            decisions = load_decisions_from_changed(loader, head_ref, decision_paths)
        except Exception as exc:  # noqa: BLE001 - fail closed
            return QuorumPromotionResult(False, tuple(reasons + [f"decision_load_failed:{type(exc).__name__}"]), vendor_id)
        decision = decisions.get(str(decision_id))
        if decision is None:
            reasons.append(f"promotion_decision_not_found:{decision_id}")
        else:
            if decision.get("decision") != "promote":
                reasons.append(f"unexpected_decision:{decision.get('decision')}")
            if decision.get("subject_id") != vendor_id:
                reasons.append("decision_subject_mismatch")
            deciding = decision.get("deciding_bot")
            discovery = decision.get("discovery_bot")
            if deciding and discovery and deciding == discovery:
                reasons.append("separation_of_duty:deciding_bot == discovery_bot")
            supporting = [str(b) for b in decision.get("supporting_bots") or []]
            independent = sorted({b for b in supporting if b != deciding})
            if not independent:
                reasons.append("separation_of_duty:deciding_bot is the sole supporter")
            minimum = min_independent_supporting_bots()
            if len(independent) < minimum:
                reasons.append(f"insufficient_independent_supporting_bots:{len(independent)}<{minimum}")
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

    return QuorumPromotionResult(not reasons, tuple(reasons), vendor_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-quorum-promotion-automerge")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--paths-file", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    paths = open(args.paths_file, encoding="utf-8").read().splitlines()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    result = check_quorum_promotion_automerge(
        paths, args.labels.split(","), args.base_ref, args.head_ref, now=now
    )
    print(f"eligible={str(result.eligible).lower()}")
    print(f"vendor_id={result.vendor_id}")
    for reason in result.reasons:
        print(f"reason={reason}")
    return 0 if result.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
