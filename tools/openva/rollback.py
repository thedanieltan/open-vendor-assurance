"""WP38b Level-5 autonomous rollback.

Reverts recent machine-created state through a pull request:

- promotion (decision: promote)            -> restore catalog_status machine_provisional
- materialization (materialize_provisional) -> remove the machine-created vendor
- quarantine (decision: quarantine)        -> restore the prior review_state

A rollback APPENDS a rollback decision record linking the original; it never
rewrites the committed observation ledger or decision history. The rollback bot
must NOT be the bot that authored the state it reverts (separation of duty:
reverser != author) — this is enforced both here and by the append-time
separation-of-duty check, since the rollback decision's discovery_bot is set to
the original decision's deciding bot.

Level-5 authority. Reversible-of-the-reversal is `reapply` (re-run the forward
lane). Operational metadata only; not legal, compliance, procurement, security,
KYC, AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT, build_indexes
from tools.openva.machine_decisions import DEFAULT_DECISIONS_DIR, append_decisions, load_decisions
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.source_verification import display_path

THRESHOLDS_PATH = ROOT / "config" / "machine-evidence-thresholds.yaml"

ROLLBACK_BOT = "rollback-controller"
REVERSIBLE_DECISIONS = {"promote", "materialize_provisional", "quarantine"}


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(config.get("rollback") or {})


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def rollback_decision_id(target_decision_id: str) -> str:
    return f"{target_decision_id}-rollback"


def already_rolled_back(target_decision_id: str, decisions_dir: Path) -> bool:
    target = rollback_decision_id(target_decision_id)
    return any(str(r.get("decision_id")) == target for r in load_decisions(decisions_dir))


# --------------------------------------------------------------------------- #
# Build the rollback decision
# --------------------------------------------------------------------------- #
def build_rollback_decision(target: dict[str, Any], *, thresholds: dict[str, Any], now: datetime) -> dict[str, Any]:
    author = str(target.get("deciding_bot") or "")
    if author == ROLLBACK_BOT:
        raise ValueError("separation_of_duty: the rollback bot may not roll back state it authored")
    decision_id = rollback_decision_id(str(target["decision_id"]))
    delay = int(thresholds.get("rollback_not_before_delay_hours", 48))
    not_before = now + timedelta(hours=delay)
    evidence = {
        "rolled_back_decision_id": str(target["decision_id"]),
        "rolled_back_decision_type": str(target.get("decision_type")),
        "rolled_back_decision": str(target.get("decision")),
        "original_author": author,
    }
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "decision_type": "rollback",
        "subject_type": str(target.get("subject_type")),
        "subject_id": str(target.get("subject_id")),
        "decision": "rollback",
        "deciding_bot": ROLLBACK_BOT,
        "supporting_bots": [],
        # Reverser != author: the original author is recorded as the discovery
        # bot, so the append-time separation-of-duty check enforces the rule.
        "discovery_bot": author,
        "evidence": evidence,
        "counter_evidence": [],
        "thresholds": {"required_score": 1.0, "actual_score": 1.0, "results": {"reverser_not_author": True}},
        "source_queue_reference": f"rollback:{target['decision_id']}",
        "candidate_digest": sha256_bytes(canonical_json(evidence)),
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "not_before": not_before.isoformat().replace("+00:00", "Z"),
        "reversal": {
            "method": "reapply",
            "reference": f"Re-run the forward lane to re-apply decision {target['decision_id']}.",
            "reversal_decision_id": None,
        },
        "not_advice": True,
    }


# --------------------------------------------------------------------------- #
# Apply the inverse to the catalog
# --------------------------------------------------------------------------- #
def vendor_path(vendor_id: str, root: Path) -> Path:
    return root / "data" / "vendors" / vendor_id / "vendor.yaml"


def source_path_for(source_id: str, root: Path) -> Path | None:
    matches = sorted((root / "data" / "vendors").glob(f"*/sources/{source_id}.yaml"))
    return matches[0] if matches else None


def revert_promotion(target: dict[str, Any], root: Path) -> list[str]:
    vendor_id = str(target["subject_id"])
    path = vendor_path(vendor_id, root)
    vendor = load_yaml(path)
    if vendor.get("catalog_status") != "active":
        raise ValueError(f"cannot revert promotion: vendor is not active ({vendor.get('catalog_status')})")
    materialization_id = str((target.get("evidence") or {}).get("materialization_decision_id") or "")
    vendor["catalog_status"] = "machine_provisional"
    if materialization_id:
        vendor["machine_decision_id"] = materialization_id
    vendor["reversal"] = {
        "method": "remove",
        "reference": f"Revert the materialization PR for {vendor_id}.",
        "reversal_decision_id": None,
    }
    write_yaml(path, vendor)
    return [display_path(path, root)]


def revert_materialization(target: dict[str, Any], root: Path) -> list[str]:
    vendor_id = str(target["subject_id"])
    vendor_dir = root / "data" / "vendors" / vendor_id
    path = vendor_path(vendor_id, root)
    if not path.exists():
        raise ValueError(f"cannot revert materialization: vendor {vendor_id} not present")
    vendor = load_yaml(path)
    if vendor.get("machine_generated") is not True:
        raise ValueError("cannot revert materialization: vendor is not machine_generated")
    if vendor.get("catalog_status") != "machine_provisional":
        raise ValueError(f"cannot revert materialization: vendor is not machine_provisional ({vendor.get('catalog_status')})")
    removed = sorted(display_path(p, root) for p in vendor_dir.rglob("*") if p.is_file())
    shutil.rmtree(vendor_dir)
    return removed


def revert_quarantine(target: dict[str, Any], root: Path) -> list[str]:
    source_id = str(target["subject_id"])
    path = source_path_for(source_id, root)
    if path is None:
        raise ValueError(f"cannot revert quarantine: source {source_id} not found")
    source = load_yaml(path)
    if source.get("review_state") != "quarantined":
        raise ValueError(f"cannot revert quarantine: source is not quarantined ({source.get('review_state')})")
    quarantine = source.get("quarantine") or {}
    prior = quarantine.get("prior_review_state") or "validated"
    source["review_state"] = prior
    source.pop("quarantine", None)
    write_yaml(path, source)
    return [display_path(path, root)]


INVERSES = {
    "promote": revert_promotion,
    "materialize_provisional": revert_materialization,
    "quarantine": revert_quarantine,
}


@dataclass(frozen=True)
class PreparedRollback:
    target_decision_id: str
    target: dict[str, Any]
    decision: dict[str, Any]


def prepare_rollback(
    target_decision_id: str,
    *,
    root: Path = ROOT,
    now: datetime | None = None,
    thresholds: dict[str, Any] | None = None,
    decisions_dir: Path = DEFAULT_DECISIONS_DIR,
) -> PreparedRollback:
    now = now or datetime.now(UTC)
    thresholds = thresholds if thresholds is not None else load_thresholds()
    target = next((r for r in load_decisions(decisions_dir) if str(r.get("decision_id")) == target_decision_id), None)
    if target is None:
        raise ValueError(f"target decision not found: {target_decision_id}")
    if str(target.get("decision")) not in REVERSIBLE_DECISIONS:
        raise ValueError(f"decision is not rollback-eligible: {target.get('decision')}")
    if already_rolled_back(target_decision_id, decisions_dir):
        raise ValueError(f"decision already rolled back: {target_decision_id}")
    decision = build_rollback_decision(target, thresholds=thresholds, now=now)
    return PreparedRollback(target_decision_id, target, decision)


def apply_rollback(
    prepared: PreparedRollback,
    *,
    root: Path = ROOT,
    decisions_dir: Path = DEFAULT_DECISIONS_DIR,
    now: datetime | None = None,
    rebuild: bool = True,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    target = prepared.target
    inverse = INVERSES[str(target["decision"])]
    # Append the rollback decision first so the catalog change always links a
    # committed, append-only decision (existing decision lines are untouched).
    decision_files = append_decisions([prepared.decision], decisions_dir)
    affected = inverse(target, root)
    if rebuild and root.resolve() == ROOT.resolve():
        build_indexes()
    return {
        "schema_version": "0.1.0",
        "report_type": "rollback_apply_report",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "rolled_back_decision_id": prepared.target_decision_id,
        "rollback_decision_id": prepared.decision["decision_id"],
        "subject_type": prepared.decision["subject_type"],
        "subject_id": prepared.decision["subject_id"],
        "deciding_bot": prepared.decision["deciding_bot"],
        "original_author": prepared.decision["discovery_bot"],
        "not_before": prepared.decision["not_before"],
        "affected_paths": affected,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": True,
            "rewrites_decision_history": False,
            "non_advisory": True,
        },
        "decision_files": [display_path(p, root) for p in decision_files],
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-rollback")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="report the rollback that would be applied (no write)")
    plan.add_argument("--decision-id", required=True)
    plan.add_argument("--now", default=None)
    plan.add_argument("--output", type=Path)

    rollback = sub.add_parser("rollback", help="apply a rollback for one target decision")
    rollback.add_argument("--decision-id", required=True)
    rollback.add_argument("--now", default=None)
    rollback.add_argument("--output", type=Path, default=Path("rollback-report.json"))

    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None

    if args.command == "plan":
        prepared = prepare_rollback(args.decision_id, now=now)
        payload = {
            "target_decision_id": prepared.target_decision_id,
            "rollback_decision_id": prepared.decision["decision_id"],
            "subject_id": prepared.decision["subject_id"],
            "original_author": prepared.decision["discovery_bot"],
            "reverser": prepared.decision["deciding_bot"],
        }
        text = json.dumps(payload, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0

    prepared = prepare_rollback(args.decision_id, now=now)
    report = apply_rollback(prepared, now=now)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
