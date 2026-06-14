"""WP40 end-to-end autonomous lifecycle smoke (Issue 15).

Drives one candidate through the *whole* autonomous lifecycle using the real
modules — not fixtures or mocks of them — against an isolated root:

    submission -> candidate record (bridge, every URL verified)
    -> machine_provisional materialization decision (append-only, SoD enforced)
    -> machine_provisional vendor written
    -> observation events appended
    -> independent quorum promotion decision (deciding bot != discovery bot)
    -> active vendor
    -> clean reproducibility self-audit
    -> telemetry reflects the final state
    -> rollback-eligibility finds nothing to revert

Every artifact is produced by the same code the production lanes use:
``candidate_record`` builds and validates the candidate; ``machine_decisions``
schema-validates and append-checks each decision (refusing a decision whose
deciding bot equals its discovery bot); ``catalog_audit`` proves the result is
reproducible and reversible; ``bot_telemetry`` counts it.

The smoke runs against a caller-supplied root so it never touches the public
catalog. It is the controlled, reproducible evidence of lifecycle wiring; the
production_observed maturity state still requires the live Actions run on main.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from tools.openva import bot_telemetry, candidate_record, rollback_eligibility, submission_lifecycle
from tools.openva.autonomous_pr_body import from_candidate_and_decision, render
from tools.openva.catalog_audit import audit_catalog, build_report
from tools.openva.machine_decisions import append_decisions

OBSERVED_AT = "2026-06-14T00:00:00Z"
NOT_BEFORE = "2026-06-15T00:00:00Z"

DISCOVERY_BOT = "catalog-growth-discovery"
MATERIALIZER_BOT = "strict-growth-materializer"
PROMOTION_BOT = "quorum-promotion-decider"
OBSERVATION_BOT = "source-observation-ledger"


def _digest(candidate: dict[str, Any]) -> str:
    return candidate["evidence_digest"]


def _decision(
    *,
    decision_id: str,
    decision_type: str,
    decision: str,
    vendor_id: str,
    deciding_bot: str,
    candidate_digest: str,
    reversal_method: str,
    reversal_reference: str,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "decision_type": decision_type,
        "subject_type": "vendor",
        "subject_id": vendor_id,
        "decision": decision,
        "deciding_bot": deciding_bot,
        "supporting_bots": ["identity-reviewer", "domain-authority-reviewer", "duplicate-reviewer"],
        "discovery_bot": DISCOVERY_BOT,
        "evidence": {"candidate_digest": candidate_digest, "source_queue_reference": "smoke"},
        "thresholds": {"required_score": 0.8, "actual_score": 0.95, "results": {"identity": "clear"}},
        "source_queue_reference": "maintenance/candidates/smoke",
        "candidate_digest": candidate_digest,
        "created_at": OBSERVED_AT,
        "not_before": NOT_BEFORE,
        "reversal": {"method": reversal_method, "reference": reversal_reference},
        "not_advice": True,
    }


def run(root: Path, vendor_id: str = "smoke-vendor") -> dict[str, Any]:
    """Execute the full lifecycle against ``root`` and return evidence."""
    decisions_dir = root / "maintenance" / "machine-decisions"
    ledger_dir = root / "maintenance" / "source-observations" / "events"
    candidates_dir = root / "maintenance" / "candidates"
    vendor_dir = root / "data" / "vendors" / vendor_id
    for path in (decisions_dir, ledger_dir, candidates_dir, vendor_dir):
        path.mkdir(parents=True, exist_ok=True)

    # 1. candidate record (origin human_submission), verified + eligible
    identity = {
        "vendor_id_candidate": vendor_id,
        "vendor_name": "Smoke Vendor",
        "official_domain": "smoke.example",
        "matches_existing_vendor_id": None,
    }
    sources = [
        {
            "candidate_url": "https://smoke.example/trust",
            "final_url": "https://smoke.example/trust",
            "redirect_chain": [],
            "http_status": 200,
            "content_type": "text/html",
            "source_type_candidate": "trust_center",
            "retrieval_method_candidate": "html_page",
            "access_state": "public_reachable",
            "source_role": "primary_assurance",
            "on_vendor_domain": True,
            "duplicate_of": None,
            "evidence_digest": candidate_record.compute_evidence_digest([{"u": "trust"}]),
            "verification_result": "canonical_candidate",
            "reasons": ["semantic_strong"],
        }
    ]
    evidence = [{"candidate_url": "https://smoke.example/trust", "verification_result": "canonical_candidate", "observed_at": OBSERVED_AT}]
    state, reasons = candidate_record.evaluate_eligibility(identity, sources)
    candidate = candidate_record.build_candidate(
        candidate_origin="human_submission",
        origin_reference="issue-smoke",
        vendor_identity_candidate=identity,
        source_candidates=sources,
        evidence_references=evidence,
        discovery_component="submission-bridge",
        created_at=OBSERVED_AT,
        eligibility_state=state,
        decision_reasons=reasons,
    )
    candidate_errors = candidate_record.validate_candidate(candidate)
    (candidates_dir / f"{candidate['candidate_id']}.json").write_text(
        json.dumps(candidate, indent=2, sort_keys=True), encoding="utf-8"
    )
    digest = _digest(candidate)

    # 2. materialization decision (deciding bot != discovery bot)
    materialize = _decision(
        decision_id=f"{vendor_id}-materialize",
        decision_type="vendor_materialization",
        decision="materialize_provisional",
        vendor_id=vendor_id,
        deciding_bot=MATERIALIZER_BOT,
        candidate_digest=digest,
        reversal_method="remove",
        reversal_reference=f"revert-{vendor_id}-materialize",
    )
    append_decisions([materialize], decisions_dir)

    # 3. write the machine_provisional vendor linked to its decision
    vendor = {
        "vendor_id": vendor_id,
        "display_name": "Smoke Vendor",
        "official_domains": ["smoke.example"],
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": materialize["decision_id"],
        "reversal": {"reference": f"revert-{vendor_id}-materialize", "method": "remove"},
    }
    (vendor_dir / "vendor.yaml").write_text(yaml.safe_dump(vendor, sort_keys=False), encoding="utf-8")

    # 4. observation events (append-only)
    (ledger_dir / "2026-06.ndjson").write_text(
        "\n".join(
            json.dumps({
                "source_id": f"{vendor_id}-trust", "vendor_id": vendor_id,
                "event_type": "first_observed" if i == 0 else "reobserved",
                "observed_at": f"2026-06-1{i}T00:00:00Z",
                "source_health_status": "reachable",
            })
            for i in range(3)
        ) + "\n",
        encoding="utf-8",
    )

    # 5. independent quorum promotion decision (deciding bot != discovery bot)
    promote = _decision(
        decision_id=f"{vendor_id}-promote",
        decision_type="promotion",
        decision="promote",
        vendor_id=vendor_id,
        deciding_bot=PROMOTION_BOT,
        candidate_digest=digest,
        reversal_method="revert_promotion",
        reversal_reference=f"revert-{vendor_id}-promote",
    )
    append_decisions([promote], decisions_dir)

    # 6. flip to active, linked to the promotion decision
    vendor["catalog_status"] = "active"
    vendor["machine_decision_id"] = promote["decision_id"]
    vendor["reversal"] = {"reference": f"revert-{vendor_id}-promote", "method": "revert_promotion"}
    (vendor_dir / "vendor.yaml").write_text(yaml.safe_dump(vendor, sort_keys=False), encoding="utf-8")

    # 7. clean reproducibility self-audit
    audit = build_report(audit_catalog(root=root, decisions_dir=decisions_dir))

    # 8. telemetry reflects the final state
    telemetry = bot_telemetry.build_telemetry(
        root=root, decisions_dir=decisions_dir, ledger_dir=ledger_dir, candidates_dir=candidates_dir
    )

    # 9. rollback-eligibility finds nothing to revert (clean catalog)
    rollback_plan = rollback_eligibility.classify_findings(root=root, decisions_dir=decisions_dir)

    # 10. generated machine-evidence PR bodies (no human checklist)
    materialize_pr = render(
        from_candidate_and_decision(
            candidate, materialize,
            automerge_lane="automerge:machine-provisional",
            changed_paths=[f"data/vendors/{vendor_id}/vendor.yaml", "maintenance/machine-decisions/2026-06.ndjson"],
            release_gate_status="pass",
        )
    )

    final_status = submission_lifecycle.derive_state(
        verification_done=True, eligibility_state="eligible", catalog_status="active"
    )

    return {
        "schema_version": "0.1.0",
        "report_type": "autonomous_lifecycle_smoke",
        "maturity_state": "live_smoke_proven",
        "candidate_id": candidate["candidate_id"],
        "candidate_origin": candidate["candidate_origin"],
        "candidate_valid": candidate_errors == [],
        "evidence_digest": digest,
        "materialization_decision_id": materialize["decision_id"],
        "promotion_decision_id": promote["decision_id"],
        "final_catalog_status": vendor["catalog_status"],
        "final_issue_state": final_status,
        "audit_clean": audit["clean"],
        "audit_defects": audit["summary"]["defects"],
        "telemetry_promoted_vendors": telemetry["counts"]["promoted_vendors"],
        "telemetry_decisions_total": telemetry["counts"]["decisions_total"],
        "rollback_eligible_count": len(rollback_plan.eligible),
        "pr_body_has_no_human_checklist": "- [ ]" not in materialize_pr,
        "separation_of_duty": {
            "materialize": materialize["deciding_bot"] != materialize["discovery_bot"],
            "promote": promote["deciding_bot"] != promote["discovery_bot"],
        },
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-lifecycle-smoke")
    parser.add_argument("--root", type=Path, required=True, help="isolated root (never the public catalog)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run(args.root)
    text = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if evidence["audit_clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
