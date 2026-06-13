"""WP37 quorum promotion: machine_provisional -> active.

Composes the independent bot quorum (tools/openva/bot_quorum.py) with the
committed-state promotion preconditions and a STATUS-ONLY lifecycle transition.

A machine_provisional vendor is promoted to active only when ALL hold:

  * committed-state preconditions: a minimum stable-observation age, a minimum
    number of healthy committed observations, no open duplicate / adversarial /
    domain-drift challenge, and >= the configured number of useful source roles;
  * an independent quorum (separate identity, domain-authority, source,
    duplicate, and adversarial reviewers plus the release gate) clears, with
    separation of duties (deciding bot != discovery bot; deciding bot is not the
    sole supporter; independence counted by distinct reviewer module);
  * a committed, append-only promotion decision record links the vendor.

The transition is STATUS-ONLY: it changes only the vendor's lifecycle/provenance
fields (catalog_status -> active, the promotion machine_decision_id, and the
reversal reference -> revert_promotion) and appends the promotion decision
record. It never edits a source, artifact, or change record, and never touches
another vendor. Terminal status is `active`; canonical remains a source /
legal-entity term, not a machine lifecycle state.

Submission bridge: a candidate:verified submission for an EXISTING vendor enters
the same machinery — there is no weaker promotion path.

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

from tools.openva import bot_quorum as quorum
from tools.openva.catalog_growth_eligibility import normalize_domain, normalize_name
from tools.openva.indexes import ROOT, build_indexes
from tools.openva.machine_decisions import append_decisions
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.source_verification import display_path

THRESHOLDS_PATH = ROOT / "config" / "machine-evidence-thresholds.yaml"
DECISIONS_DIR = ROOT / "maintenance" / "machine-decisions"
MATCH_INDEX_PATH = ROOT / "indexes" / "vendor-match-index.json"
LEDGER_DIR = ROOT / "maintenance" / "source-observations" / "events"

# Status-only promotion may change ONLY these vendor fields.
STATUS_ONLY_FIELDS = {"catalog_status", "machine_decision_id", "reversal"}

HEALTHY_CHANGE_CLASSES = {"none", "non_material", ""}


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(config.get("promotion") or {})


# --------------------------------------------------------------------------- #
# Subject assembly from committed repository state
# --------------------------------------------------------------------------- #
def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def vendor_sources(vendor_id: str, root: Path) -> list[dict[str, Any]]:
    sources_dir = root / "data" / "vendors" / vendor_id / "sources"
    return [load_yaml(path) for path in sorted(sources_dir.glob("*.yaml"))] if sources_dir.exists() else []


def vendor_events(vendor_id: str, ledger_dir: Path) -> list[dict[str, Any]]:
    from tools.openva.observation_ledger import load_ledger_events

    return [event for event in load_ledger_events(ledger_dir) if str(event.get("vendor_id") or "") == vendor_id]


def other_vendor_identity(vendor_id: str, root: Path) -> tuple[set[str], set[str]]:
    """Domains and names of OTHER vendors (excluding the subject), for collision
    and duplicate detection."""
    domains: set[str] = set()
    names: set[str] = set()
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        if str(vendor.get("vendor_id") or path.parent.name) == vendor_id:
            continue
        for key in ("official_domains", "public_entrypoints", "previous_domains"):
            for value in vendor.get(key, []) or []:
                if normalize_domain(value):
                    domains.add(normalize_domain(value))
        if normalize_name(vendor.get("display_name")):
            names.add(normalize_name(vendor.get("display_name")))
        for alias in vendor.get("display_aliases", []) or []:
            if normalize_name(alias):
                names.add(normalize_name(alias))
    return domains, names


def latest_materialization_decision(vendor_id: str, decisions_dir: Path) -> dict[str, Any] | None:
    from tools.openva.machine_decisions import load_decisions

    candidates = [
        record
        for record in load_decisions(decisions_dir)
        if str(record.get("subject_id")) == vendor_id and record.get("decision") == "materialize_provisional"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: str(r.get("created_at") or ""))


def load_match_index_items(path: Path = MATCH_INDEX_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)]


def build_subject(
    vendor_id: str,
    *,
    root: Path = ROOT,
    now: datetime | None = None,
    thresholds: dict[str, Any] | None = None,
    ledger_dir: Path = LEDGER_DIR,
    decisions_dir: Path = DECISIONS_DIR,
    match_index_path: Path = MATCH_INDEX_PATH,
) -> quorum.PromotionSubject:
    now = now or datetime.now(UTC)
    vendor = load_yaml(root / "data" / "vendors" / vendor_id / "vendor.yaml")
    other_domains, other_names = other_vendor_identity(vendor_id, root)
    return quorum.PromotionSubject(
        vendor=vendor,
        sources=vendor_sources(vendor_id, root),
        events=vendor_events(vendor_id, ledger_dir),
        materialization_decision=latest_materialization_decision(vendor_id, decisions_dir),
        other_vendor_domains=other_domains,
        other_vendor_names=other_names,
        match_index_items=load_match_index_items(match_index_path),
        now=now,
        thresholds=thresholds if thresholds is not None else load_thresholds(),
    )


# --------------------------------------------------------------------------- #
# Committed-state promotion preconditions (the cheap gate before the quorum)
# --------------------------------------------------------------------------- #
def parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def successful_observation_count(events: list[dict[str, Any]]) -> int:
    return sum(
        1
        for event in events
        if str(event.get("source_health_status") or "") not in quorum.UNAVAILABLE_HEALTH
        and str(event.get("change_class") or "") in HEALTHY_CHANGE_CLASSES
        and str(event.get("event_type") or "") not in quorum.MATERIAL_CHANGE_CLASSES
    )


def stable_observation_age_hours(events: list[dict[str, Any]], now: datetime) -> float | None:
    observed = [parse_iso(event.get("observed_at")) for event in events]
    observed = [dt for dt in observed if dt is not None]
    if not observed:
        return None
    return max(0.0, (now - min(observed)).total_seconds() / 3600.0)


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...]
    metrics: dict[str, Any]


def promotion_eligibility(subject: quorum.PromotionSubject) -> EligibilityResult:
    now = subject.now or datetime.now(UTC)
    t = subject.thresholds
    reasons: list[str] = []

    if subject.vendor.get("catalog_status") != "machine_provisional":
        reasons.append(f"not_machine_provisional:{subject.vendor.get('catalog_status')}")

    age = stable_observation_age_hours(subject.events, now)
    min_age = float(t.get("min_stable_observation_age_hours", 168))
    if age is None:
        reasons.append("no_committed_observations")
    elif age < min_age:
        reasons.append(f"stable_observation_age_too_low:{age:.1f}h<{min_age:.0f}h")

    successful = successful_observation_count(subject.events)
    min_obs = int(t.get("min_successful_observations", 2))
    if successful < min_obs:
        reasons.append(f"insufficient_successful_observations:{successful}<{min_obs}")

    if t.get("require_no_open_challenge", True):
        open_reasons = quorum.open_challenge_reasons(subject.events)
        reasons.extend(open_reasons)

    roles = quorum.useful_source_roles(subject.sources)
    min_roles = int(t.get("min_useful_source_roles", 2))
    if len(roles) < min_roles:
        reasons.append(f"insufficient_useful_source_roles:{len(roles)}<{min_roles}")

    metrics = {
        "stable_observation_age_hours": round(age, 1) if age is not None else None,
        "successful_observations": successful,
        "useful_source_roles": sorted(roles),
        "open_challenges": quorum.open_challenge_reasons(subject.events),
    }
    return EligibilityResult(not reasons, tuple(reasons), metrics)


# --------------------------------------------------------------------------- #
# Promotion decision record + status-only transition
# --------------------------------------------------------------------------- #
def promotion_decision_id(vendor_id: str) -> str:
    return f"{vendor_id}-promotion"


def build_promotion_decision(
    subject: quorum.PromotionSubject,
    result: quorum.QuorumResult,
    *,
    deciding_bot: str = quorum.DECIDING_BOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or subject.now or datetime.now(UTC)
    vendor_id = subject.vendor_id
    t = subject.thresholds
    discovery_bot = str((subject.materialization_decision or {}).get("discovery_bot") or "")
    decision_id = promotion_decision_id(vendor_id)
    delay = int(t.get("promotion_not_before_delay_hours", 48))
    not_before = now + timedelta(hours=delay)
    supporting_bots = [b for b in result.supporting_bots if b != deciding_bot]
    materialization_id = str((subject.materialization_decision or {}).get("decision_id") or "")
    evidence = {
        "materialization_decision_id": materialization_id,
        "independent_supporting_modules": list(result.independent_modules),
        "stable_observation_age_hours": stable_observation_age_hours(subject.events, now),
        "successful_observations": successful_observation_count(subject.events),
        "useful_source_roles": sorted(quorum.useful_source_roles(subject.sources)),
    }
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "decision_type": "promotion",
        "subject_type": "vendor",
        "subject_id": vendor_id,
        "decision": "promote",
        "deciding_bot": deciding_bot,
        "supporting_bots": supporting_bots,
        "discovery_bot": discovery_bot,
        "evidence": evidence,
        "counter_evidence": [],
        "thresholds": {
            "required_score": float(t.get("required_score", 1.0)),
            "actual_score": float(t.get("required_score", 1.0)),
            "results": {
                "quorum_decision": result.decision,
                "independent_supporting_modules": len(result.independent_modules),
                "separation_of_duty_clean": True,
            },
        },
        "source_queue_reference": f"machine_provisional:{vendor_id}",
        "candidate_digest": sha256_bytes(canonical_json(evidence)),
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "not_before": not_before.isoformat().replace("+00:00", "Z"),
        "reversal": {
            "method": "revert_promotion",
            "reference": f"Revert the promotion PR for {vendor_id}; restores catalog_status machine_provisional. See decision {decision_id}.",
            "reversal_decision_id": None,
        },
        "not_advice": True,
    }


def apply_status_only_transition(vendor: dict[str, Any], decision_id: str, vendor_id: str) -> dict[str, Any]:
    """Return a copy of the vendor record with ONLY lifecycle/provenance fields
    changed. Preserves key order so the committed diff is status-only."""
    updated = dict(vendor)
    updated["catalog_status"] = "active"
    updated["machine_decision_id"] = decision_id
    updated["reversal"] = {
        "method": "revert_promotion",
        "reference": f"Revert the promotion PR for {vendor_id}; restores catalog_status machine_provisional. See decision {decision_id}.",
        "reversal_decision_id": None,
    }
    return updated


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


@dataclass(frozen=True)
class PreparedPromotion:
    vendor_id: str
    eligibility: EligibilityResult
    quorum_result: quorum.QuorumResult
    decision: dict[str, Any] | None
    promotable: bool
    reasons: tuple[str, ...]


def prepare_promotion(
    vendor_id: str,
    *,
    release_gate_decision: str,
    root: Path = ROOT,
    now: datetime | None = None,
    thresholds: dict[str, Any] | None = None,
    ledger_dir: Path = LEDGER_DIR,
    decisions_dir: Path = DECISIONS_DIR,
    match_index_path: Path = MATCH_INDEX_PATH,
) -> PreparedPromotion:
    now = now or datetime.now(UTC)
    subject = build_subject(
        vendor_id,
        root=root,
        now=now,
        thresholds=thresholds,
        ledger_dir=ledger_dir,
        decisions_dir=decisions_dir,
        match_index_path=match_index_path,
    )
    eligibility = promotion_eligibility(subject)
    result = run_quorum_for(subject, release_gate_decision=release_gate_decision)
    reasons = list(eligibility.reasons) + list(result.reasons)
    promotable = eligibility.eligible and result.promote
    decision = build_promotion_decision(subject, result, now=now) if promotable else None
    return PreparedPromotion(
        vendor_id=vendor_id,
        eligibility=eligibility,
        quorum_result=result,
        decision=decision,
        promotable=promotable,
        reasons=tuple(reasons),
    )


def run_quorum_for(subject: quorum.PromotionSubject, *, release_gate_decision: str) -> quorum.QuorumResult:
    return quorum.run_quorum(subject, release_gate_decision=release_gate_decision)


def apply_promotion(
    prepared: PreparedPromotion,
    *,
    root: Path = ROOT,
    decisions_dir: Path = DECISIONS_DIR,
    rebuild: bool = True,
) -> dict[str, Any]:
    if not prepared.promotable or prepared.decision is None:
        raise ValueError(f"vendor not promotable: {', '.join(prepared.reasons) or 'unknown'}")
    vendor_id = prepared.vendor_id
    decision = prepared.decision
    v_path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    vendor = load_yaml(v_path)
    if vendor.get("catalog_status") != "machine_provisional":
        raise ValueError(f"vendor is not machine_provisional: {vendor.get('catalog_status')}")

    # Append the committed promotion decision BEFORE mutating the vendor, so the
    # vendor always links a real, committed decision (mirrors materialization).
    decision_files = append_decisions([decision], decisions_dir)
    write_yaml(v_path, apply_status_only_transition(vendor, str(decision["decision_id"]), vendor_id))

    if rebuild and root.resolve() == ROOT.resolve():
        build_indexes()

    return {
        "schema_version": "0.1.0",
        "report_type": "quorum_promotion_apply_report",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "vendor_id": vendor_id,
        "decision_id": decision["decision_id"],
        "supporting_bots": list(prepared.quorum_result.supporting_bots),
        "independent_supporting_modules": list(prepared.quorum_result.independent_modules),
        "deciding_bot": decision["deciding_bot"],
        "discovery_bot": decision["discovery_bot"],
        "not_before": decision["not_before"],
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": True,
            "status_only_transition": True,
            "non_advisory": True,
        },
        "decision_files": [display_path(p, root) for p in decision_files],
        "not_advice": True,
    }


# --------------------------------------------------------------------------- #
# Selection (which provisional vendor, if any, can be promoted now)
# --------------------------------------------------------------------------- #
def provisional_vendor_ids(root: Path = ROOT) -> list[str]:
    ids: list[str] = []
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        if vendor.get("catalog_status") == "machine_provisional":
            ids.append(str(vendor.get("vendor_id") or path.parent.name))
    return ids


def select_promotable(
    *,
    release_gate_decision: str,
    root: Path = ROOT,
    now: datetime | None = None,
    thresholds: dict[str, Any] | None = None,
    ledger_dir: Path = LEDGER_DIR,
    decisions_dir: Path = DECISIONS_DIR,
    match_index_path: Path = MATCH_INDEX_PATH,
) -> PreparedPromotion | None:
    """The first machine_provisional vendor that is fully promotable now. One
    vendor per PR: selection stops at the first promotable vendor."""
    already_promoted = _promoted_subject_ids(decisions_dir)
    for vendor_id in provisional_vendor_ids(root):
        if promotion_decision_id(vendor_id) in already_promoted:
            continue
        prepared = prepare_promotion(
            vendor_id,
            release_gate_decision=release_gate_decision,
            root=root,
            now=now,
            thresholds=thresholds,
            ledger_dir=ledger_dir,
            decisions_dir=decisions_dir,
            match_index_path=match_index_path,
        )
        if prepared.promotable:
            return prepared
    return None


def _promoted_subject_ids(decisions_dir: Path) -> set[str]:
    from tools.openva.machine_decisions import load_decisions

    return {
        str(record.get("decision_id"))
        for record in load_decisions(decisions_dir)
        if record.get("decision") == "promote"
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _now_arg(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-quorum-promotion")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--release-gate-decision", choices=["pass", "blocked"], required=True)
    common.add_argument("--now", default=None)

    eligible = sub.add_parser("eligible", parents=[common], help="report eligibility + quorum for one vendor (no write)")
    eligible.add_argument("--vendor-id", required=True)
    eligible.add_argument("--output", type=Path)

    select = sub.add_parser("select", parents=[common], help="print the first promotable provisional vendor id, if any")
    select.add_argument("--output", type=Path)

    promote = sub.add_parser("promote", parents=[common], help="apply a status-only promotion for one vendor")
    promote.add_argument("--vendor-id", required=True)
    promote.add_argument("--output", type=Path, default=Path("quorum-promotion-report.json"))

    args = parser.parse_args(argv)
    now = _now_arg(args.now)

    if args.command == "eligible":
        prepared = prepare_promotion(args.vendor_id, release_gate_decision=args.release_gate_decision, now=now)
        payload = {
            "vendor_id": prepared.vendor_id,
            "promotable": prepared.promotable,
            "eligibility_reasons": list(prepared.eligibility.reasons),
            "quorum_reasons": list(prepared.quorum_result.reasons),
            "metrics": prepared.eligibility.metrics,
            "independent_supporting_modules": list(prepared.quorum_result.independent_modules),
        }
        text = json.dumps(payload, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if prepared.promotable else 1

    if args.command == "select":
        prepared = select_promotable(release_gate_decision=args.release_gate_decision, now=now)
        vendor_id = prepared.vendor_id if prepared else ""
        if args.output:
            args.output.write_text(f"PROMOTABLE_VENDOR_ID={vendor_id}\n", encoding="utf-8")
        print(vendor_id)
        return 0

    # promote
    prepared = prepare_promotion(args.vendor_id, release_gate_decision=args.release_gate_decision, now=now)
    if not prepared.promotable:
        print("vendor not promotable; failing closed:")
        for reason in prepared.reasons:
            print(f"  - {reason}")
        return 1
    report = apply_promotion(prepared)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
