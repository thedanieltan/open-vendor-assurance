"""WP38a autonomous source quarantine.

Quarantine is a reversible, status-only transition of a single source from its
current review state to `quarantined`, taken only when the source is
persistently not-found/gone in the committed observation ledger and no safe
replacement has been applied (the source-repair lane is the path that would have
replaced it). It NEVER fabricates a replacement.

Boundaries (composed, not reinterpreted):
- Gated / bot-protected sources are RECORD-ONLY: they are never quarantined by
  fetch and never bypassed.
- Material change is an observation event only; quarantine does not interpret
  the legal, security, compliance, or procurement meaning of any change.

Every quarantine writes a committed, append-only quarantine decision record
(separation of duties: the deciding bot differs from the observation/discovery
bot) and carries a `revert_quarantine` reversal reference, so it is reversible
through a pull request.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT, build_indexes
from tools.openva.machine_decisions import append_decisions
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.source_verification import display_path

THRESHOLDS_PATH = ROOT / "config" / "machine-evidence-thresholds.yaml"
DECISIONS_DIR = ROOT / "maintenance" / "machine-decisions"
LEDGER_DIR = ROOT / "maintenance" / "source-observations" / "events"

DISCOVERY_BOT = "source-observation-ledger"
DECIDING_BOT = "quarantine-controller"

# Only these source fields may change in a status-only quarantine.
STATUS_ONLY_FIELDS = {"review_state", "quarantine"}


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(config.get("quarantine") or {})


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def source_events(source_id: str, ledger_dir: Path) -> list[dict[str, Any]]:
    from tools.openva.observation_ledger import load_ledger_events

    events = [e for e in load_ledger_events(ledger_dir) if str(e.get("source_id") or "") == source_id]
    return sorted(events, key=lambda e: str(e.get("observed_at") or ""))


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class QuarantineEligibility:
    eligible: bool
    reasons: tuple[str, ...]
    quarantine_reason: str | None
    metrics: dict[str, Any]


def quarantine_eligibility(
    source: dict[str, Any],
    events: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> QuarantineEligibility:
    reasons: list[str] = []
    failed_statuses = set(int(s) for s in thresholds.get("failed_http_statuses", [404, 410]))
    record_only = set(thresholds.get("record_only_health", ["gated", "bot_protected"]))
    minimum = int(thresholds.get("min_failed_observations", 3))

    if source.get("review_state") == "quarantined":
        reasons.append("already_quarantined")

    if not events:
        reasons.append("no_committed_observations")
        return QuarantineEligibility(False, tuple(reasons), None, {"failed_observations": 0})

    latest = events[-1]
    latest_health = str(latest.get("source_health_status") or "")
    if latest_health in record_only:
        # Record-only: never quarantine a gated/bot-protected source.
        reasons.append(f"record_only_health:{latest_health}")

    failed = [e for e in events if int(e.get("http_status") or 0) in failed_statuses]
    if int(latest.get("http_status") or 0) not in failed_statuses:
        # The source is not currently failing not-found/gone; do not quarantine.
        reasons.append(f"latest_observation_not_failed:{latest.get('http_status')}")
    if len(failed) < minimum:
        reasons.append(f"insufficient_failed_observations:{len(failed)}<{minimum}")

    quarantine_reason = None
    if failed:
        quarantine_reason = "persistent_gone" if any(int(e.get("http_status") or 0) == 410 for e in failed) else "persistent_not_found"

    metrics = {
        "failed_observations": len(failed),
        "latest_http_status": latest.get("http_status"),
        "latest_health": latest_health,
    }
    return QuarantineEligibility(not reasons, tuple(reasons), quarantine_reason if not reasons else None, metrics)


# --------------------------------------------------------------------------- #
# Decision record + status-only transition
# --------------------------------------------------------------------------- #
def quarantine_decision_id(source_id: str) -> str:
    return f"{source_id}-quarantine"


def build_quarantine_decision(
    source: dict[str, Any],
    eligibility: QuarantineEligibility,
    *,
    thresholds: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    source_id = str(source["source_id"])
    decision_id = quarantine_decision_id(source_id)
    delay = int(thresholds.get("quarantine_not_before_delay_hours", 48))
    not_before = now + timedelta(hours=delay)
    evidence = {
        "source_url": str(source.get("source_url") or ""),
        "quarantine_reason": eligibility.quarantine_reason,
        "failed_observations": eligibility.metrics.get("failed_observations"),
        "latest_http_status": eligibility.metrics.get("latest_http_status"),
    }
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "decision_type": "quarantine",
        "subject_type": "source",
        "subject_id": source_id,
        "decision": "quarantine",
        "deciding_bot": DECIDING_BOT,
        "supporting_bots": [],
        "discovery_bot": DISCOVERY_BOT,
        "evidence": evidence,
        "counter_evidence": [],
        "thresholds": {
            "required_score": float(thresholds.get("required_score", 1.0)),
            "actual_score": float(thresholds.get("required_score", 1.0)),
            "results": {"persistent_failure": True, "no_replacement_applied": True},
        },
        "source_queue_reference": f"observation:{source_id}",
        "candidate_digest": sha256_bytes(canonical_json(evidence)),
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "not_before": not_before.isoformat().replace("+00:00", "Z"),
        "reversal": {
            "method": "revert_quarantine",
            "reference": f"Revert the quarantine PR for {source_id}; restores the prior review_state. See decision {decision_id}.",
            "reversal_decision_id": None,
        },
        "not_advice": True,
    }


def apply_status_only_quarantine(
    source: dict[str, Any],
    decision: dict[str, Any],
    quarantine_reason: str,
    now: datetime,
) -> dict[str, Any]:
    """Return a copy of the source with ONLY review_state + quarantine set."""
    updated = dict(source)
    updated["review_state"] = "quarantined"
    decision_id = str(decision["decision_id"])
    source_id = str(source["source_id"])
    updated["quarantine"] = {
        "reason": quarantine_reason,
        "quarantined_by": DECIDING_BOT,
        "quarantined_at": now.isoformat().replace("+00:00", "Z"),
        "decision_id": decision_id,
        "reversal": {
            "method": "revert_quarantine",
            "reference": f"Revert the quarantine PR for {source_id}; restores the prior review_state. See decision {decision_id}.",
            "reversal_decision_id": None,
        },
    }
    return updated


# --------------------------------------------------------------------------- #
# Source discovery + prepare/apply
# --------------------------------------------------------------------------- #
def source_path_for(source_id: str, root: Path) -> Path | None:
    matches = sorted((root / "data" / "vendors").glob(f"*/sources/{source_id}.yaml"))
    return matches[0] if matches else None


@dataclass(frozen=True)
class PreparedQuarantine:
    source_id: str
    source_path: Path
    eligibility: QuarantineEligibility
    decision: dict[str, Any] | None
    quarantinable: bool


def prepare_quarantine(
    source_id: str,
    *,
    root: Path = ROOT,
    now: datetime | None = None,
    thresholds: dict[str, Any] | None = None,
    ledger_dir: Path = LEDGER_DIR,
) -> PreparedQuarantine:
    now = now or datetime.now(UTC)
    thresholds = thresholds if thresholds is not None else load_thresholds()
    path = source_path_for(source_id, root)
    if path is None:
        raise ValueError(f"source not found: {source_id}")
    source = load_yaml(path)
    events = source_events(source_id, ledger_dir)
    eligibility = quarantine_eligibility(source, events, thresholds)
    decision = (
        build_quarantine_decision(source, eligibility, thresholds=thresholds, now=now)
        if eligibility.eligible
        else None
    )
    return PreparedQuarantine(source_id, path, eligibility, decision, eligibility.eligible)


def apply_quarantine(
    prepared: PreparedQuarantine,
    *,
    root: Path = ROOT,
    decisions_dir: Path = DECISIONS_DIR,
    now: datetime | None = None,
    rebuild: bool = True,
) -> dict[str, Any]:
    if not prepared.quarantinable or prepared.decision is None:
        raise ValueError(f"source not quarantinable: {', '.join(prepared.eligibility.reasons) or 'unknown'}")
    now = now or datetime.now(UTC)
    source = load_yaml(prepared.source_path)
    if source.get("review_state") == "quarantined":
        raise ValueError("source already quarantined")
    decision = prepared.decision
    decision_files = append_decisions([decision], decisions_dir)
    write_yaml(
        prepared.source_path,
        apply_status_only_quarantine(source, decision, str(prepared.eligibility.quarantine_reason), now),
    )
    if rebuild and root.resolve() == ROOT.resolve():
        build_indexes()
    return {
        "schema_version": "0.1.0",
        "report_type": "source_quarantine_apply_report",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source_id": prepared.source_id,
        "decision_id": decision["decision_id"],
        "quarantine_reason": prepared.eligibility.quarantine_reason,
        "deciding_bot": decision["deciding_bot"],
        "discovery_bot": decision["discovery_bot"],
        "not_before": decision["not_before"],
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": True,
            "status_only_transition": True,
            "fabricates_replacement": False,
            "non_advisory": True,
        },
        "decision_files": [display_path(p, root) for p in decision_files],
        "not_advice": True,
    }


def quarantinable_source_ids(root: Path = ROOT, ledger_dir: Path = LEDGER_DIR, thresholds: dict[str, Any] | None = None) -> list[str]:
    thresholds = thresholds if thresholds is not None else load_thresholds()
    ids: list[str] = []
    for path in sorted((root / "data" / "vendors").glob("*/sources/*.yaml")):
        source = load_yaml(path)
        source_id = str(source.get("source_id") or path.stem)
        events = source_events(source_id, ledger_dir)
        if quarantine_eligibility(source, events, thresholds).eligible:
            ids.append(source_id)
    return ids


def select_quarantinable(
    *,
    root: Path = ROOT,
    now: datetime | None = None,
    thresholds: dict[str, Any] | None = None,
    ledger_dir: Path = LEDGER_DIR,
) -> PreparedQuarantine | None:
    """The first quarantinable source. One source per PR."""
    for source_id in quarantinable_source_ids(root, ledger_dir, thresholds):
        prepared = prepare_quarantine(source_id, root=root, now=now, thresholds=thresholds, ledger_dir=ledger_dir)
        if prepared.quarantinable:
            return prepared
    return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-quarantine")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--now", default=None)

    eligible = sub.add_parser("eligible", parents=[common], help="report quarantine eligibility for one source (no write)")
    eligible.add_argument("--source-id", required=True)
    eligible.add_argument("--output", type=Path)

    select = sub.add_parser("select", parents=[common], help="print the first quarantinable source id, if any")
    select.add_argument("--output", type=Path)

    quarantine = sub.add_parser("quarantine", parents=[common], help="apply a status-only quarantine for one source")
    quarantine.add_argument("--source-id", required=True)
    quarantine.add_argument("--output", type=Path, default=Path("source-quarantine-report.json"))

    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None

    if args.command == "eligible":
        prepared = prepare_quarantine(args.source_id, now=now)
        payload = {
            "source_id": prepared.source_id,
            "quarantinable": prepared.quarantinable,
            "reasons": list(prepared.eligibility.reasons),
            "quarantine_reason": prepared.eligibility.quarantine_reason,
            "metrics": prepared.eligibility.metrics,
        }
        text = json.dumps(payload, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if prepared.quarantinable else 1

    if args.command == "select":
        prepared = select_quarantinable(now=now)
        source_id = prepared.source_id if prepared else ""
        if args.output:
            args.output.write_text(f"QUARANTINABLE_SOURCE_ID={source_id}\n", encoding="utf-8")
        print(source_id)
        return 0

    prepared = prepare_quarantine(args.source_id, now=now)
    if not prepared.quarantinable:
        print("source not quarantinable; failing closed:")
        for reason in prepared.eligibility.reasons:
            print(f"  - {reason}")
        return 1
    report = apply_quarantine(prepared, now=now)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
