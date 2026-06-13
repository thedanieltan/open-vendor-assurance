"""WP39 catalog reproducibility audit.

Every machine-created catalog claim must be reconstructable from its committed
machine decision record(s) and reversible. This audit cross-checks the committed
catalog against the committed decision store and reports four defect classes:

- missing       : a machine claim whose linked decision is absent from the store
- orphan        : a forward decision whose subject claim is absent (and was not
                  rolled back)
- contradictory : a claim whose lifecycle state disagrees with its linked
                  decision (e.g. an active machine vendor linked to a
                  materialization rather than a promotion decision)
- non_reversible: a machine claim that carries no reversal reference

A rollback decision legitimately removes/ restores its target, so a forward
decision that has been rolled back is not reported as orphan.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT
from tools.openva.machine_decisions import DEFAULT_DECISIONS_DIR, load_decisions

FORWARD_DECISIONS = {"materialize_provisional", "promote", "quarantine"}
# Which linked decision a machine vendor's catalog_status implies.
STATUS_EXPECTED_DECISION = {"machine_provisional": "materialize_provisional", "active": "promote"}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@dataclass
class AuditReport:
    findings: list[dict[str, str]] = field(default_factory=list)
    machine_vendors: int = 0
    machine_sources: int = 0
    decisions: int = 0

    def add(self, defect: str, subject_type: str, subject_id: str, detail: str) -> None:
        self.findings.append({"defect": defect, "subject_type": subject_type, "subject_id": subject_id, "detail": detail})

    @property
    def clean(self) -> bool:
        return not self.findings


def rolled_back_decision_ids(decisions: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for record in decisions:
        if record.get("decision") == "rollback":
            ids.add(str((record.get("evidence") or {}).get("rolled_back_decision_id") or ""))
    return ids


def audit_catalog(root: Path = ROOT, decisions_dir: Path = DEFAULT_DECISIONS_DIR) -> AuditReport:
    report = AuditReport()
    decisions = load_decisions(decisions_dir)
    report.decisions = len(decisions)
    by_id = {str(r.get("decision_id")): r for r in decisions}
    rolled_back = rolled_back_decision_ids(decisions)

    vendor_ids: set[str] = set()
    source_ids: set[str] = set()

    # --- machine-created vendors ---
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        vendor_id = str(vendor.get("vendor_id") or path.parent.name)
        vendor_ids.add(vendor_id)
        if vendor.get("machine_generated") is not True:
            continue
        report.machine_vendors += 1
        decision_id = str(vendor.get("machine_decision_id") or "")
        decision = by_id.get(decision_id)
        if not decision_id or decision is None:
            report.add("missing", "vendor", vendor_id, f"machine_decision_id {decision_id!r} not in decision store")
        else:
            if str(decision.get("subject_id")) != vendor_id:
                report.add("contradictory", "vendor", vendor_id, "linked decision subject_id mismatch")
            expected = STATUS_EXPECTED_DECISION.get(str(vendor.get("catalog_status")))
            if expected and decision.get("decision") != expected:
                report.add("contradictory", "vendor", vendor_id, f"status {vendor.get('catalog_status')} expects {expected}, linked decision is {decision.get('decision')}")
        if not (vendor.get("reversal") or {}).get("reference"):
            report.add("non_reversible", "vendor", vendor_id, "machine vendor has no reversal reference")

    # --- quarantined sources ---
    for path in sorted((root / "data" / "vendors").glob("*/sources/*.yaml")):
        source = load_yaml(path)
        source_id = str(source.get("source_id") or path.stem)
        source_ids.add(source_id)
        if source.get("review_state") != "quarantined":
            continue
        report.machine_sources += 1
        quarantine = source.get("quarantine") or {}
        decision_id = str(quarantine.get("decision_id") or "")
        decision = by_id.get(decision_id)
        if not decision_id or decision is None:
            report.add("missing", "source", source_id, f"quarantine.decision_id {decision_id!r} not in decision store")
        else:
            if str(decision.get("subject_id")) != source_id:
                report.add("contradictory", "source", source_id, "linked quarantine decision subject_id mismatch")
            if decision.get("decision") != "quarantine":
                report.add("contradictory", "source", source_id, f"linked decision is {decision.get('decision')}, expected quarantine")
        if not (quarantine.get("reversal") or {}).get("reference"):
            report.add("non_reversible", "source", source_id, "quarantined source has no reversal reference")

    # --- orphan forward decisions ---
    for record in decisions:
        if record.get("decision") not in FORWARD_DECISIONS:
            continue
        decision_id = str(record.get("decision_id"))
        if decision_id in rolled_back:
            continue  # legitimately reverted
        subject_id = str(record.get("subject_id"))
        present = subject_id in vendor_ids if record.get("subject_type") == "vendor" else subject_id in source_ids
        if not present:
            report.add("orphan", str(record.get("subject_type")), subject_id, f"decision {decision_id} ({record.get('decision')}) has no catalog subject and was not rolled back")

    return report


def build_report(report: AuditReport) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for finding in report.findings:
        counts[finding["defect"]] = counts.get(finding["defect"], 0) + 1
    from datetime import UTC, datetime

    return {
        "schema_version": "0.1.0",
        "report_type": "catalog_reproducibility_audit",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "summary": {
            "machine_vendors": report.machine_vendors,
            "machine_sources": report.machine_sources,
            "decisions": report.decisions,
            "defects": len(report.findings),
            "by_defect": counts,
        },
        "findings": report.findings,
        "clean": report.clean,
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-audit")
    parser.add_argument("command", choices=["audit"])
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--enforce", action="store_true", help="exit non-zero if any defect is found")
    args = parser.parse_args(argv)

    report = build_report(audit_catalog(decisions_dir=args.decisions_dir))
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if args.enforce and not report["clean"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
