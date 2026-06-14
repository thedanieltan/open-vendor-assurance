"""WP40C autonomous catalog PR body generator (Issue 13).

For an autonomous catalog mutation the PR body is *generated machine evidence*,
not a human checklist and not a duplicate of CI. It records exactly what the
machine proved so a reviewer (or an auditor after the fact) can reconstruct the
decision: candidate origin, candidate id, decision id, evidence digest, changed
paths, the machine-proven conditions, the separation-of-duty result, the
release-gate status, the not-before timestamp, the automerge lane, and the
reversal reference.

Human-oriented checklists remain only for code / policy / schema / workflow /
governance PRs; those are produced elsewhere. This generator intentionally
emits no ``- [ ]`` review checklist for a routine catalog record.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BODY_MARKER = "<!-- openva-autonomous-catalog-pr -->"


@dataclass
class AutonomousPRBody:
    candidate_origin: str
    candidate_id: str
    decision_id: str
    evidence_digest: str
    automerge_lane: str
    not_before: str
    reversal_reference: str
    changed_paths: list[str] = field(default_factory=list)
    machine_proven_conditions: list[str] = field(default_factory=list)
    separation_of_duty: dict[str, Any] = field(default_factory=dict)
    release_gate_status: str = "pending"
    title_hint: str | None = None


def _sod_line(sod: dict[str, Any]) -> str:
    deciding = sod.get("deciding_bot", "?")
    discovery = sod.get("discovery_bot", "?")
    ok = deciding != discovery and deciding and discovery
    verdict = "pass" if ok else "FAIL"
    return f"deciding `{deciding}` vs discovery `{discovery}` -> **{verdict}**"


def render(body: AutonomousPRBody) -> str:
    rows = [
        ("Candidate origin", f"`{body.candidate_origin}`"),
        ("Candidate ID", f"`{body.candidate_id}`"),
        ("Decision ID", f"`{body.decision_id}`"),
        ("Evidence digest", f"`{body.evidence_digest}`"),
        ("Separation of duty", _sod_line(body.separation_of_duty)),
        ("Release gate", f"`{body.release_gate_status}`"),
        ("Not before", f"`{body.not_before}`"),
        ("Automerge lane", f"`{body.automerge_lane}`"),
        ("Reversal reference", f"`{body.reversal_reference}`"),
    ]
    lines = [
        BODY_MARKER,
        "## Autonomous catalog change — machine evidence",
        "",
        "This pull request was generated and is governed autonomously. The table "
        "below is machine-proven evidence, not a human checklist; OpenVA records "
        "observable public metadata and provenance only and makes no vendor "
        "judgement. Merge is gated by the release gate and the automerge lane "
        "below, after the not-before delay.",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    lines += [f"| {label} | {value} |" for label, value in rows]

    lines += ["", "### Machine-proven conditions", ""]
    if body.machine_proven_conditions:
        lines += [f"- {cond}" for cond in body.machine_proven_conditions]
    else:
        lines.append("- (none recorded)")

    lines += ["", "### Changed paths", ""]
    if body.changed_paths:
        lines += [f"- `{path}`" for path in sorted(body.changed_paths)]
    else:
        lines.append("- (none)")

    lines += [
        "",
        "Reversible through a pull request via the reversal reference above; the "
        "linked machine decision and the append-only decision/observation history "
        "make this change auditable and reversible. No human approval is required "
        "for this routine catalog record.",
    ]
    return "\n".join(lines) + "\n"


def contains_human_checklist(body_text: str) -> bool:
    """True if the body contains a human review checklist (``- [ ]``)."""
    return "- [ ]" in body_text or "- [x]" in body_text.lower()


def from_candidate_and_decision(
    candidate: dict[str, Any],
    decision: dict[str, Any],
    *,
    automerge_lane: str,
    changed_paths: list[str],
    release_gate_status: str = "pending",
    machine_proven_conditions: list[str] | None = None,
) -> AutonomousPRBody:
    reversal = decision.get("reversal") or {}
    return AutonomousPRBody(
        candidate_origin=str(candidate.get("candidate_origin", "unknown")),
        candidate_id=str(candidate.get("candidate_id", "unknown")),
        decision_id=str(decision.get("decision_id", "unknown")),
        evidence_digest=str(candidate.get("evidence_digest") or decision.get("candidate_digest", "unknown")),
        automerge_lane=automerge_lane,
        not_before=str(decision.get("not_before", "unknown")),
        reversal_reference=str(reversal.get("reference") or reversal.get("method") or "unknown"),
        changed_paths=list(changed_paths),
        machine_proven_conditions=list(machine_proven_conditions or candidate.get("decision_reasons") or []),
        separation_of_duty={
            "deciding_bot": decision.get("deciding_bot"),
            "discovery_bot": decision.get("discovery_bot"),
        },
        release_gate_status=release_gate_status,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-autonomous-pr-body")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--automerge-lane", required=True)
    parser.add_argument("--changed-path", action="append", default=[])
    parser.add_argument("--release-gate-status", default="pending")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    decision = json.loads(args.decision.read_text(encoding="utf-8"))
    body = render(
        from_candidate_and_decision(
            candidate,
            decision,
            automerge_lane=args.automerge_lane,
            changed_paths=args.changed_path,
            release_gate_status=args.release_gate_status,
        )
    )
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
