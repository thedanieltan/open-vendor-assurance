"""WP40B self-audit → rollback eligibility classifier.

Connects the catalog reproducibility audit to the rollback lane so invalid
machine-created state is reverted autonomously instead of waiting for a manual
dispatch with a hand-supplied decision id.

For each audit finding this classifier decides whether the defect is
*rollback-eligible*, identifies the target machine decision, and records the
reversal-author constraint that the rollback lane must satisfy
(reverser != original author). It never decides the rollback itself — that
remains a separate, independently-bounded deciding component — and it only ever
proposes reverting **machine-created** state.

Decisions are append-only downstream: a rollback appends a new decision linking
the original; this classifier never rewrites history.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.openva.catalog_audit import audit_catalog, build_report
from tools.openva.indexes import ROOT
from tools.openva.machine_decisions import DEFAULT_DECISIONS_DIR, load_decisions

# Defect classes that a rollback can remediate. A `missing` decision cannot be
# rolled back (there is no committed decision to reverse — that needs a
# forward repair/quarantine), so it is reported ineligible.
ROLLBACK_ELIGIBLE_DEFECTS = {"contradictory", "non_reversible", "orphan"}


@dataclass
class RollbackProposal:
    subject_type: str
    subject_id: str
    defect: str
    eligible: bool
    target_decision_id: str | None
    original_author: str | None
    reason: str
    reversal_method: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "defect": self.defect,
            "eligible": self.eligible,
            "target_decision_id": self.target_decision_id,
            "original_author": self.original_author,
            "reversal_method": self.reversal_method,
            "reason": self.reason,
        }


@dataclass
class RollbackPlan:
    proposals: list[RollbackProposal] = field(default_factory=list)

    @property
    def eligible(self) -> list[RollbackProposal]:
        return [p for p in self.proposals if p.eligible]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "report_type": "rollback_eligibility_plan",
            "proposals": [p.as_dict() for p in self.proposals],
            "eligible_count": len(self.eligible),
            "not_advice": True,
        }


# How a machine vendor's current status maps to the reversal a rollback applies.
_VENDOR_REVERSAL = {"materialize_provisional": "remove", "promote": "revert_promotion"}


def _find_decision_for_subject(
    decisions: list[dict[str, Any]], subject_type: str, subject_id: str
) -> dict[str, Any] | None:
    """The most recent forward decision for a subject (last write wins)."""
    forward = {"materialize_provisional", "promote", "quarantine"}
    match: dict[str, Any] | None = None
    for record in decisions:
        if (
            record.get("subject_type") == subject_type
            and str(record.get("subject_id")) == subject_id
            and record.get("decision") in forward
        ):
            match = record
    return match


def classify_findings(root: Path = ROOT, decisions_dir: Path = DEFAULT_DECISIONS_DIR) -> RollbackPlan:
    audit = build_report(audit_catalog(root=root, decisions_dir=decisions_dir))
    decisions = load_decisions(decisions_dir)
    plan = RollbackPlan()

    for finding in audit["findings"]:
        defect = finding["defect"]
        subject_type = finding["subject_type"]
        subject_id = finding["subject_id"]

        if defect not in ROLLBACK_ELIGIBLE_DEFECTS:
            plan.proposals.append(
                RollbackProposal(
                    subject_type, subject_id, defect, False, None, None,
                    f"{defect}_not_rollback_eligible_needs_forward_repair",
                )
            )
            continue

        decision = _find_decision_for_subject(decisions, subject_type, subject_id)
        if decision is None:
            plan.proposals.append(
                RollbackProposal(
                    subject_type, subject_id, defect, False, None, None,
                    "no_committed_machine_decision_to_reverse",
                )
            )
            continue

        original_author = str(decision.get("discovery_bot") or "") or None
        decision_kind = str(decision.get("decision"))
        reversal_method = (
            _VENDOR_REVERSAL.get(decision_kind)
            if subject_type == "vendor"
            else "revert_quarantine"
        )
        plan.proposals.append(
            RollbackProposal(
                subject_type, subject_id, defect, True,
                str(decision.get("decision_id")), original_author,
                f"machine_created_{decision_kind}_reversible_by_independent_reverser",
                reversal_method=reversal_method,
            )
        )

    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-rollback-eligibility")
    parser.add_argument("command", choices=["classify"])
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    plan = classify_findings(decisions_dir=args.decisions_dir).as_dict()
    text = json.dumps(plan, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
