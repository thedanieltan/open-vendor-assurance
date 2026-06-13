"""WP39 operational telemetry tests: counts only, never scores/rankings."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva import bot_telemetry as bt
from tools.openva.advisory_wording import load_prohibited_terms, prohibited_terms_in_text


def _seed(tmp_path: Path):
    # one machine_provisional vendor + one promoted (active machine_generated) vendor
    for vid, status in (("prov", "machine_provisional"), ("prom", "active")):
        p = tmp_path / "data" / "vendors" / vid / "vendor.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump({"vendor_id": vid, "catalog_status": status, "machine_generated": True,
                                     "machine_decision_id": f"{vid}-d", "reversal": {"reference": "r"}}), encoding="utf-8")
    # one quarantined source
    sp = tmp_path / "data" / "vendors" / "acme" / "sources" / "acme-dpa.yaml"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(yaml.safe_dump({"source_id": "acme-dpa", "review_state": "quarantined",
                                  "quarantine": {"decision_id": "acme-dpa-quarantine", "reversal": {"reference": "r"}}}), encoding="utf-8")
    decisions = tmp_path / "maintenance" / "machine-decisions"
    decisions.mkdir(parents=True)
    rows = [
        {"decision_id": "prov-d", "decision": "materialize_provisional", "subject_type": "vendor", "subject_id": "prov", "deciding_bot": "strict-growth-materializer", "discovery_bot": "catalog-growth-discovery"},
        {"decision_id": "prom-d", "decision": "promote", "subject_type": "vendor", "subject_id": "prom", "deciding_bot": "quorum-promotion-decider", "discovery_bot": "catalog-growth-discovery"},
        {"decision_id": "acme-dpa-quarantine", "decision": "quarantine", "subject_type": "source", "subject_id": "acme-dpa", "deciding_bot": "quarantine-controller", "discovery_bot": "source-observation-ledger"},
    ]
    (decisions / "2026-06.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    ledger = tmp_path / "maintenance" / "source-observations" / "events"
    ledger.mkdir(parents=True)
    (ledger / "2026-06.ndjson").write_text(json.dumps({"source_id": "acme-dpa", "observed_at": "2026-06-12T00:00:00Z", "review_signal": {"required": True, "reason": "source_health_unreachable"}}) + "\n", encoding="utf-8")
    return decisions, ledger


def test_counts_reflect_committed_state(tmp_path):
    decisions, ledger = _seed(tmp_path)
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger)
    c = t["counts"]
    assert c["provisional_vendors"] == 1
    assert c["promoted_vendors"] == 1
    assert c["quarantined_sources"] == 1
    assert c["open_challenged_sources"] == 1
    assert c["decisions_total"] == 3
    assert t["decisions_by_deciding_bot"]["quorum-promotion-decider"] == 1


def test_telemetry_carries_no_scores_or_rankings(tmp_path):
    decisions, ledger = _seed(tmp_path)
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger)
    assert t["carries_scores_or_rankings"] is False
    assert t["not_advice"] is True
    # The rendered telemetry must not contain prohibited advisory/scoring vocabulary.
    md = bt.render_markdown(t)
    assert prohibited_terms_in_text(md, load_prohibited_terms()) == []


def test_empty_state_is_all_zero(tmp_path):
    (tmp_path / "data" / "vendors").mkdir(parents=True)
    decisions = tmp_path / "maintenance" / "machine-decisions"
    decisions.mkdir(parents=True)
    ledger = tmp_path / "maintenance" / "source-observations" / "events"
    ledger.mkdir(parents=True)
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger)
    assert t["counts"]["decisions_total"] == 0
    assert t["counts"]["provisional_vendors"] == 0
