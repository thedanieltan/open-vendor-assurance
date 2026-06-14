"""WP40B self-audit -> rollback eligibility tests.

Only machine-created state is eligible; the reverser must differ from the
original author; nothing escalates to a human queue.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva import rollback_eligibility as re


def _seed(tmp_path: Path, *, vendor: dict, decision: dict | None):
    vdir = tmp_path / "data" / "vendors" / vendor["vendor_id"]
    vdir.mkdir(parents=True)
    (vdir / "vendor.yaml").write_text(yaml.safe_dump(vendor), encoding="utf-8")
    decisions_dir = tmp_path / "maintenance" / "machine-decisions"
    decisions_dir.mkdir(parents=True)
    if decision is not None:
        (decisions_dir / "2026-06.ndjson").write_text(json.dumps(decision) + "\n", encoding="utf-8")
    return decisions_dir


def test_contradictory_machine_vendor_is_rollback_eligible(tmp_path):
    # active machine vendor whose linked decision is a materialization, not a
    # promotion -> contradictory, and rollback-eligible.
    decisions_dir = _seed(
        tmp_path,
        vendor={
            "vendor_id": "acme", "catalog_status": "active", "machine_generated": True,
            "machine_decision_id": "acme-mat", "reversal": {"reference": "r"},
        },
        decision={
            "decision_id": "acme-mat", "decision": "materialize_provisional",
            "subject_type": "vendor", "subject_id": "acme",
            "deciding_bot": "materializer", "discovery_bot": "discovery",
        },
    )
    plan = re.classify_findings(root=tmp_path, decisions_dir=decisions_dir)
    eligible = plan.eligible
    assert len(eligible) == 1
    proposal = eligible[0]
    assert proposal.subject_id == "acme"
    assert proposal.target_decision_id == "acme-mat"
    assert proposal.original_author == "discovery"
    assert proposal.reversal_method == "remove"


def test_missing_decision_is_not_rollback_eligible(tmp_path):
    # machine vendor referencing a decision that is absent from the store ->
    # `missing` defect; cannot be rolled back (no decision to reverse).
    decisions_dir = _seed(
        tmp_path,
        vendor={
            "vendor_id": "ghost", "catalog_status": "machine_provisional", "machine_generated": True,
            "machine_decision_id": "absent", "reversal": {"reference": "r"},
        },
        decision=None,
    )
    plan = re.classify_findings(root=tmp_path, decisions_dir=decisions_dir)
    assert plan.eligible == []
    assert any(p.defect == "missing" and not p.eligible for p in plan.proposals)


def test_only_machine_created_state_considered(tmp_path):
    # a human (non machine_generated) vendor produces no findings at all.
    decisions_dir = _seed(
        tmp_path,
        vendor={"vendor_id": "human", "catalog_status": "active"},
        decision=None,
    )
    plan = re.classify_findings(root=tmp_path, decisions_dir=decisions_dir)
    assert plan.proposals == []


def test_clean_catalog_yields_no_proposals(tmp_path):
    decisions_dir = _seed(
        tmp_path,
        vendor={
            "vendor_id": "ok", "catalog_status": "machine_provisional", "machine_generated": True,
            "machine_decision_id": "ok-mat", "reversal": {"reference": "r"},
        },
        decision={
            "decision_id": "ok-mat", "decision": "materialize_provisional",
            "subject_type": "vendor", "subject_id": "ok",
            "deciding_bot": "materializer", "discovery_bot": "discovery",
        },
    )
    plan = re.classify_findings(root=tmp_path, decisions_dir=decisions_dir)
    assert plan.eligible == []
