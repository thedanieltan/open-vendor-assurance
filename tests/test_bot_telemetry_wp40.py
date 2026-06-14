"""WP40C telemetry expansion: candidate buckets, repair count, next action, live block."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva import bot_telemetry as bt
from tools.openva.advisory_wording import load_prohibited_terms, prohibited_terms_in_text


def _empty_dirs(tmp_path: Path):
    (tmp_path / "data" / "vendors").mkdir(parents=True)
    decisions = tmp_path / "maintenance" / "machine-decisions"
    decisions.mkdir(parents=True)
    ledger = tmp_path / "maintenance" / "source-observations" / "events"
    ledger.mkdir(parents=True)
    candidates = tmp_path / "maintenance" / "candidates"
    candidates.mkdir(parents=True)
    return decisions, ledger, candidates


def _candidate(cid: str, state: str, created_at: str) -> dict:
    return {
        "candidate_id": cid,
        "candidate_origin": "human_submission",
        "eligibility_state": state,
        "created_at": created_at,
    }


def test_candidate_buckets_and_oldest_deferred(tmp_path):
    decisions, ledger, candidates = _empty_dirs(tmp_path)
    (candidates / "a.json").write_text(json.dumps(_candidate("cand-a", "eligible", "2026-06-10T00:00:00Z")), encoding="utf-8")
    (candidates / "b.json").write_text(json.dumps(_candidate("cand-b", "deferred_insufficient_evidence", "2026-06-01T00:00:00Z")), encoding="utf-8")
    (candidates / "c.json").write_text(json.dumps(_candidate("cand-c", "rejected_duplicate", "2026-06-05T00:00:00Z")), encoding="utf-8")
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger, candidates_dir=candidates)
    c = t["counts"]
    assert c["candidate_total"] == 3
    assert c["eligible_candidates"] == 1
    assert c["deferred_candidates"] == 1
    assert c["rejected_candidates"] == 1
    assert t["oldest_deferred_candidate"] == "cand-b"
    # one eligible candidate -> next action is machine_provisional_growth
    assert t["next_eligible_action"] == "machine_provisional_growth"


def test_autonomous_repair_decisions_counted(tmp_path):
    decisions, ledger, candidates = _empty_dirs(tmp_path)
    rows = [
        {"decision_id": "r1", "decision": "quarantine", "decision_type": "repair", "subject_type": "source", "subject_id": "s1", "deciding_bot": "repair", "discovery_bot": "obs"},
        {"decision_id": "r2", "decision": "quarantine", "decision_type": "repair", "subject_type": "source", "subject_id": "s2", "deciding_bot": "repair", "discovery_bot": "obs"},
    ]
    (decisions / "2026-06.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger, candidates_dir=candidates)
    assert t["counts"]["autonomous_repair_decisions"] == 2


def test_pr_budget_reads_queue_policy(tmp_path):
    decisions, ledger, candidates = _empty_dirs(tmp_path)
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger, candidates_dir=candidates)
    # uses the repository's real queue policy (3/day, 10/week)
    assert t["pr_budget"]["daily"] >= 1
    assert t["pr_budget"]["weekly"] >= t["pr_budget"]["daily"]


def test_live_block_absent_is_null_not_fabricated(tmp_path):
    decisions, ledger, candidates = _empty_dirs(tmp_path)
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger, candidates_dir=candidates)
    assert t["live"]["available"] is False
    assert t["live"]["open_bot_prs_by_lane"] is None


def test_live_block_passes_through_supplied_state(tmp_path):
    decisions, ledger, candidates = _empty_dirs(tmp_path)
    live = {
        "open_bot_prs_by_lane": {"catalog_growth_promotion": 1},
        "daily_prs_used": 2,
        "weekly_prs_used": 5,
        "latest_success_by_lane": {"source_repair": "2026-06-13T00:00:00Z"},
        "latest_failure_by_lane": {},
        "next_scheduled_action": "2026-06-17T08:47:00Z",
    }
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger, candidates_dir=candidates, live_state=live)
    assert t["live"]["available"] is True
    assert t["live"]["open_bot_prs_by_lane"] == {"catalog_growth_promotion": 1}
    assert t["live"]["next_scheduled_action"] == "2026-06-17T08:47:00Z"


def test_expanded_telemetry_stays_non_advisory(tmp_path):
    decisions, ledger, candidates = _empty_dirs(tmp_path)
    (candidates / "a.json").write_text(json.dumps(_candidate("cand-a", "eligible", "2026-06-10T00:00:00Z")), encoding="utf-8")
    t = bt.build_telemetry(root=tmp_path, decisions_dir=decisions, ledger_dir=ledger, candidates_dir=candidates)
    md = bt.render_markdown(t)
    assert prohibited_terms_in_text(md, load_prohibited_terms()) == []
    assert t["carries_scores_or_rankings"] is False
