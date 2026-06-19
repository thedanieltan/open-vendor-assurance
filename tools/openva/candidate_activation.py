"""WP-OPENVA-CANDIDATE-ACTIVATION-01 candidate-bound activation.

Binds one staged candidate record end-to-end through the autonomous
catalogue-growth path so the candidate the controller *selects* is provably the
candidate ultimately *mutated* and proposed for catalogue inclusion. Identity is
never re-derived later from a separate queue.

The control path this module wires:

    persisted candidate (maintenance/candidates/<id>.json, non-canonical)
      -> evaluate_persisted_candidate  (recompute eligibility + identity)
      -> candidate identity + content digest bound
      -> candidate-bound controller decision (autonomous_growth_controller)
      -> candidate-bound promotion dispatch (candidate-promotion-pr.yml)
      -> verify_binding on the exact PR head            <- fail closed on drift
      -> materialize_candidate  (machine_provisional vendor + decision)
      -> catalogue PR

It reuses, never forks, the canonical pieces:

- ``vendor_resolution.evaluate_persisted_candidate`` — the one canonical
  eligibility evaluator (no second or simplified evaluator);
- ``candidate_promotion_actions`` source / artifact / change builders;
- ``machine_decisions.append_decisions`` — the append-only, schema-validated,
  separation-of-duties-enforced decision writer.

Candidate intake may stage candidates and bind their identity through the gated
decision path; it may not directly write canonical catalogue truth, may not
merge, and may not bypass the independent quorum. Materialization writes a NEW
``machine_provisional`` vendor only, linked to an append-only decision; promotion
to a terminal status remains the independent WP37 quorum.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.openva import candidate_record, vendor_resolution
from tools.openva.candidate_promotion_actions import (
    artifact_from_source,
    materialization_decision_id,
    not_before_delay_hours,
    source_from_candidate,
    write_yaml,
)
from tools.openva.catalog_lifecycle import change_event
from tools.openva.indexes import ROOT
from tools.openva.machine_decisions import append_decisions
from tools.openva.source_verification import display_path

# Separation of duties: the deciding bot must differ from the candidate's own
# discovery component (enforced again at append time by machine_decisions).
MATERIALIZER_BOT = "candidate-activation-materializer"

BINDING_FIELDS = ("candidate_id", "candidate_path", "content_digest", "origin", "selected_vendor")


class CandidateBindingError(ValueError):
    """A candidate failed its end-to-end identity/eligibility binding.

    Raised (and surfaced as a non-zero CLI exit) so the mutation path fails
    closed and never creates or modifies a canonical catalogue PR.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons) or "candidate binding failed")


def load_candidate(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(Path(path))}: expected a candidate record object")
    return data


def binding_from_args(
    *, candidate_id: str, candidate_path: str | None, content_digest: str, origin: str, selected_vendor: str
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "candidate_path": candidate_path,
        "content_digest": content_digest,
        "origin": origin,
        "selected_vendor": selected_vendor,
    }


def collect_eligible_candidates(candidates_dir: Path, root: Path = ROOT) -> list[dict[str, Any]]:
    """Eligible candidate records with their bound path, for the controller.

    Globs ``maintenance/candidates/*.json``, recomputes eligibility and identity
    for each (never trusting the stored ``eligibility_state``) and returns only
    the records that are internally consistent *and* recompute to ``eligible``,
    each enriched with its ``candidate_path``. The controller re-runs the same
    gate on the one it selects, so this is a pre-filter, not a trust boundary.
    """
    out: list[dict[str, Any]] = []
    for path in sorted(Path(candidates_dir).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        rel = path.relative_to(root).as_posix()
        decision = vendor_resolution.evaluate_persisted_candidate(record, candidate_path=rel)
        if decision.eligible:
            enriched = dict(record)
            enriched["candidate_path"] = rel
            out.append(enriched)
    return out


def verify_intake_paths(changed_paths: list[str], root: Path = ROOT) -> dict[str, tuple[str, ...]]:
    """Recompute each staged candidate's internal consistency for the intake lane.

    For every changed ``maintenance/candidates/*.json`` that exists on the PR
    head, the persisted record must recompute consistently — deterministic id and
    evidence digest reproduce and the stored ``eligibility_state`` recomputes to
    the same value (never trusted). This is the eligibility-reproducibility check
    the candidate-intake spine deferred to its consuming job; staging a deferred
    or rejected candidate is allowed (so this requires *consistency*, not
    *eligibility*). Deletions and non-candidate paths are ignored — the guard
    already enforces path confinement. Returns ``{path: reasons}`` with empty
    reasons meaning consistent.
    """
    from tools.openva.automerge_lanes import is_candidate_intake_path

    results: dict[str, tuple[str, ...]] = {}
    for raw in changed_paths:
        path = (raw or "").strip()
        if not path or not is_candidate_intake_path(path):
            continue
        full = Path(root) / path
        if not full.exists():
            continue
        try:
            record = json.loads(full.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            results[path] = (f"unreadable:{type(exc).__name__}",)
            continue
        if not isinstance(record, dict):
            results[path] = ("not_a_candidate_record",)
            continue
        decision = vendor_resolution.evaluate_persisted_candidate(record, candidate_path=path)
        results[path] = () if decision.consistent else decision.reasons
    return results


def verify_binding(record: dict[str, Any], candidate_path: str | None, expected: dict[str, Any]) -> list[str]:
    """Verify a candidate against an expected binding; return mismatch reasons.

    Empty list == verified. Re-runs the canonical recompute (eligibility +
    deterministic id/digest) and compares every bound field — candidate_id,
    candidate_path, content_digest, origin, selected_vendor — against the
    identity the controller decided. Catches: stale/forged/changed records,
    digest mismatch, candidate-id mismatch, off-origin / source-origin mismatch,
    selected-vendor mismatch, path substitution, and a PR head differing from
    the reviewed candidate state.
    """
    reasons: list[str] = []
    decision = vendor_resolution.evaluate_persisted_candidate(record, candidate_path=candidate_path)
    if not decision.eligible:
        reasons.extend(decision.reasons or ("recomputed_not_eligible",))
    actual = decision.binding()
    for key in ("candidate_id", "content_digest", "origin", "selected_vendor"):
        if str(expected.get(key)) != str(actual.get(key)):
            reasons.append(f"{key}_mismatch:{expected.get(key)}!={actual.get(key)}")
    expected_path = expected.get("candidate_path")
    if expected_path is not None and str(expected_path) != str(candidate_path):
        reasons.append(f"candidate_path_mismatch:{expected_path}!={candidate_path}")
    return reasons


def _usable_sources(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The on-authority public assurance sources the evaluator would count.

    Mirrors candidate_record.evaluate_eligibility's usable-source rule so the
    materialized sources are exactly the evidence the eligibility was based on.
    """
    usable: list[dict[str, Any]] = []
    for source in record.get("source_candidates", []) or []:
        if source.get("access_state") not in candidate_record.PUBLIC_ACCESS_STATES:
            continue
        if source.get("source_role") not in candidate_record.USEFUL_SOURCE_ROLES:
            continue
        if source.get("on_vendor_domain") is False:
            continue
        usable.append(source)
    return usable


def vendor_from_candidate(record: dict[str, Any], decision_id: str) -> dict[str, Any]:
    """A schema-valid ``machine_provisional`` vendor built from the candidate.

    Fails closed (raises) when the candidate lacks the metadata a canonical
    vendor profile requires — a display name and a valid ISO-3166 alpha-2
    headquarters country — rather than fabricating it.
    """
    identity = record.get("vendor_identity_candidate") or {}
    vendor_id = str(identity.get("vendor_id_candidate") or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", vendor_id):
        raise CandidateBindingError([f"invalid_vendor_id:{vendor_id}"])
    display_name = str(identity.get("vendor_name") or "").strip() or vendor_id.replace("-", " ").title()
    country = str(identity.get("headquarters_country") or "").strip()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise CandidateBindingError(
            [f"missing_iso_headquarters_country:{vendor_id} (got {country!r}); fail closed"]
        )
    domain = str(identity.get("official_domain") or "").lower().removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        raise CandidateBindingError([f"invalid_official_domain:{domain}"])
    return {
        "schema_version": "0.1.0",
        "vendor_id": vendor_id,
        "display_name": display_name[:160],
        "legal_name": identity.get("legal_name"),
        "headquarters_country": country,
        "regions_served": ["global"],
        "official_domains": [domain],
        "public_entrypoints": [f"https://{domain}"],
        "vendor_categories": [],
        "source_policy": {
            "public_sources_only": True,
            "gated_materials_excluded": True,
            "raw_documents_mirrored_by_default": False,
        },
        # Candidate-bound materialization enters as machine_provisional, never
        # directly active. Promotion to active is the independent WP37 quorum.
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": decision_id,
        "reversal": {
            "method": "remove",
            "reference": f"Revert the candidate-bound materialization PR for {vendor_id}; see decision {decision_id}.",
            "reversal_decision_id": None,
        },
        "notes": "Machine-provisional vendor materialized from a bound, eligibility-recomputed candidate record. Metadata-only; not advisory; reversible.",
        "entity_surface": "global_brand",
        "source_authority_language": "en",
    }


def sources_from_candidate(record: dict[str, Any], vendor_id: str) -> list[dict[str, Any]]:
    """Canonical source records for the candidate's usable assurance sources."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in _usable_sources(record):
        candidate_input = {
            "vendor_id": vendor_id,
            "source_type_candidate": str(source.get("source_type_candidate") or ""),
            "candidate_url": str(source.get("final_url") or source.get("candidate_url") or ""),
            "confidence": "likely",
            "evidence": {"page_title": None},
        }
        built = source_from_candidate(candidate_input)
        if built["source_id"] in seen:
            continue
        seen.add(built["source_id"])
        records.append(built)
    return records


def materialization_decision_for_candidate(
    record: dict[str, Any],
    *,
    vendor_id: str,
    decision_id: str,
    candidate_path: str | None,
    content_digest: str,
    now: datetime,
) -> dict[str, Any]:
    """Append-only materialization decision carrying the full candidate binding.

    ``candidate_digest`` is the candidate content digest, so the committed
    decision pins exactly which candidate state authorised the vendor.
    Separation of duties: the deciding bot differs from the candidate's
    discovery component.
    """
    identity = record.get("vendor_identity_candidate") or {}
    discovery_bot = str(record.get("discovery_component") or "candidate-intake")[:100] or "candidate-intake"
    created = now.replace(microsecond=0)
    not_before_iso = (created + timedelta(hours=not_before_delay_hours())).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "decision_type": "vendor_materialization",
        "subject_type": "vendor",
        "subject_id": vendor_id,
        "subject_lineage_id": vendor_id,
        "supersedes_decision_id": None,
        "reapplies_after_rollback_id": None,
        "decision": "materialize_provisional",
        "deciding_bot": MATERIALIZER_BOT,
        "supporting_bots": [],
        "discovery_bot": discovery_bot,
        "evidence": {
            "candidate_id": str(record.get("candidate_id") or ""),
            "candidate_path": candidate_path,
            "candidate_origin": str(record.get("candidate_origin") or ""),
            "selected_vendor": vendor_id,
            "content_digest": content_digest,
            "official_domain": str(identity.get("official_domain") or ""),
            "usable_source_count": len(_usable_sources(record)),
        },
        "counter_evidence": [],
        "thresholds": {
            "required_score": 1.0,
            "actual_score": 1.0,
            "results": {"eligibility": candidate_record.ELIGIBLE_STATE, "binding": "verified"},
        },
        "source_queue_reference": str(candidate_path or f"candidate_intake:{record.get('candidate_id')}")[:300],
        "candidate_digest": content_digest,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "not_before": not_before_iso,
        "reversal": {
            "method": "remove",
            "reference": f"Revert the candidate-bound materialization PR for {vendor_id}; see decision {decision_id}.",
            "reversal_decision_id": None,
        },
        "not_advice": True,
    }


def materialize_candidate(
    record: dict[str, Any],
    candidate_path: str | None,
    expected: dict[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Materialize the bound candidate into a machine_provisional vendor + decision.

    Verifies the binding first and fails closed on any mismatch — nothing is
    written unless the candidate is provably the controller-selected one. The
    materialized vendor id is asserted equal to the bound ``selected_vendor``
    (selected == mutated). Writes the append-only decision before the vendor so
    the vendor always links a committed decision.
    """
    now = now or datetime.now(UTC)
    root = Path(root)

    reasons = verify_binding(record, candidate_path, expected)
    if reasons:
        raise CandidateBindingError(reasons)

    # Hash and materialize the on-disk record only: drop any transient routing
    # key so the report/decision digest always equals the bound content digest.
    record = {k: v for k, v in record.items() if k != "candidate_path"}
    vendor_id = str((record.get("vendor_identity_candidate") or {}).get("vendor_id_candidate") or "")
    if vendor_id != str(expected.get("selected_vendor")):
        raise CandidateBindingError(
            [f"mutated_vendor_not_selected:{vendor_id}!={expected.get('selected_vendor')}"]
        )

    content_digest = candidate_record.compute_candidate_content_digest(record)
    decisions_dir = root / "maintenance" / "machine-decisions"
    sources = sources_from_candidate(record, vendor_id)
    if not sources:
        raise CandidateBindingError([f"no_usable_assurance_source:{vendor_id}"])

    base = root / "data" / "vendors" / vendor_id
    v_path = base / "vendor.yaml"
    if v_path.exists():
        # Replay / re-dispatch of an already-materialized candidate: fail closed.
        raise CandidateBindingError([f"vendor_already_exists:{display_path(v_path, root)}"])

    decision_id = materialization_decision_id(vendor_id, record, decisions_dir)
    vendor = vendor_from_candidate(record, decision_id)
    decision = materialization_decision_for_candidate(
        record,
        vendor_id=vendor_id,
        decision_id=decision_id,
        candidate_path=candidate_path,
        content_digest=content_digest,
        now=now,
    )

    # Pre-check source/artifact/change targets before any write.
    planned: list[tuple[Path, dict[str, Any]]] = []
    for source in sources:
        s_path = base / "sources" / f"{source['source_id']}.yaml"
        a_path = base / "artifacts" / f"{source['source_id']}.yaml"
        c_path = base / "changes" / f"candidate-intake-{source['source_id']}.yaml"
        for path in (s_path, a_path, c_path):
            if path.exists():
                raise CandidateBindingError([f"target_already_exists:{display_path(path, root)}"])
        planned.append((s_path, source))

    # Append-only decision first (schema + separation-of-duties validated).
    decision_files = append_decisions([decision], decisions_dir)
    write_yaml(v_path, vendor)

    file_actions: list[dict[str, str]] = [
        {"action": "write", "path": display_path(v_path, root), "candidate_path": str(candidate_path)},
    ]
    for decision_file in decision_files:
        file_actions.append(
            {"action": "append", "path": display_path(decision_file, root), "candidate_path": "machine_decision_record"}
        )
    for s_path, source in planned:
        artifact = artifact_from_source(source)
        a_path = base / "artifacts" / f"{artifact['artifact_id']}.yaml"
        c_path = base / "changes" / f"candidate-intake-{source['source_id']}.yaml"
        write_yaml(s_path, source)
        write_yaml(a_path, artifact)
        write_yaml(
            c_path,
            change_event(
                change_id=f"candidate-intake-{source['source_id']}",
                vendor_id=vendor_id,
                source_id=str(source["source_id"]),
                artifact_id=str(artifact["artifact_id"]),
                change_type="created",
                detected_at=str(source["provenance"]["collected_at"]),
                summary="Candidate-bound machine-provisional source materialized from a recomputed, identity-bound candidate.",
            ),
        )
        file_actions.extend(
            [
                {"action": "write", "path": display_path(s_path, root), "candidate_path": str(candidate_path)},
                {"action": "write", "path": display_path(a_path, root), "candidate_path": str(candidate_path)},
                {"action": "write", "path": display_path(c_path, root), "candidate_path": str(candidate_path)},
            ]
        )

    return {
        "schema_version": "0.1.0",
        "report_type": "candidate_bound_materialization_report",
        "candidate_id": str(record.get("candidate_id") or ""),
        "candidate_path": candidate_path,
        "content_digest": content_digest,
        "origin": str(record.get("candidate_origin") or ""),
        "selected_vendor": vendor_id,
        "mutated_vendor": vendor_id,
        "decision_id": decision_id,
        "candidate_digest": decision["candidate_digest"],
        "posture": {
            "writes_repository_state": True,
            "writes_canonical_vendors": True,
            "opens_pull_requests": False,
            "auto_merge": False,
            "non_advisory": True,
        },
        "file_actions": file_actions,
        "not_advice": True,
    }


def _cli_collect_eligible(args: argparse.Namespace) -> int:
    records = collect_eligible_candidates(args.candidates_dir, root=args.root)
    text = json.dumps(records, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(f"eligible candidates: {len(records)}")
    return 0


def _cli_verify_intake(args: argparse.Namespace) -> int:
    paths = Path(args.paths_file).read_text(encoding="utf-8").splitlines()
    results = verify_intake_paths(paths, root=args.root)
    ok = True
    for path, reasons in sorted(results.items()):
        if reasons:
            ok = False
            for reason in reasons:
                print(f"reason={path}:{reason}")
        else:
            print(f"consistent={path}")
    print(f"verified={'true' if ok else 'false'}")
    return 0 if ok else 1


def _expected_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return binding_from_args(
        candidate_id=args.candidate_id,
        candidate_path=args.candidate_path,
        content_digest=args.content_digest,
        origin=args.origin,
        selected_vendor=args.selected_vendor,
    )


def _cli_verify(args: argparse.Namespace) -> int:
    record = load_candidate(args.candidate)
    candidate_path = args.candidate_path or Path(args.candidate).relative_to(args.root).as_posix()
    reasons = verify_binding(record, candidate_path, _expected_from_args(args))
    if reasons:
        for reason in reasons:
            print(f"reason={reason}")
        print("verified=false")
        return 1
    print("verified=true")
    return 0


def _cli_materialize(args: argparse.Namespace) -> int:
    record = load_candidate(args.candidate)
    candidate_path = args.candidate_path or Path(args.candidate).relative_to(args.root).as_posix()
    try:
        report = materialize_candidate(
            record, candidate_path, _expected_from_args(args), root=args.root
        )
    except CandidateBindingError as exc:
        for reason in exc.reasons:
            print(f"reason={reason}")
        print("materialized=false")
        return 1
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(f"materialized=true vendor={report['mutated_vendor']} decision={report['decision_id']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-candidate-activation")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect-eligible", help="list eligible candidate records with bound paths")
    collect.add_argument("--candidates-dir", type=Path, default=ROOT / "maintenance" / "candidates")
    collect.add_argument("--root", type=Path, default=ROOT)
    collect.add_argument("--output", type=Path)
    collect.set_defaults(func=_cli_collect_eligible)

    intake = sub.add_parser(
        "verify-intake", help="recompute consistency of staged candidate-intake records (fail closed)"
    )
    intake.add_argument("--paths-file", required=True)
    intake.add_argument("--root", type=Path, default=ROOT)
    intake.set_defaults(func=_cli_verify_intake)

    for name, func, helptext in (
        ("verify", _cli_verify, "verify a candidate against an expected binding (fail closed)"),
        ("materialize", _cli_materialize, "materialize the bound candidate into a machine_provisional vendor"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--candidate", type=Path, required=True)
        p.add_argument("--candidate-id", required=True)
        p.add_argument("--content-digest", required=True)
        p.add_argument("--selected-vendor", required=True)
        p.add_argument("--origin", required=True)
        p.add_argument("--candidate-path", default=None)
        p.add_argument("--root", type=Path, default=ROOT)
        p.add_argument("--output", type=Path)
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
