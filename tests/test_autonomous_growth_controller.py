"""WP40A Issue 3: scheduled autonomous growth controller decides one cycle."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.openva import autonomous_growth_controller as agc

NOW = datetime(2026, 6, 14, tzinfo=UTC)
LANE = "catalog_growth_promotion"


def _live_state(**overrides):
    state = {
        "lane_id": LANE,
        "state_source": "github_live",
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "pause": {"active": False},
        "evidence": {"generated_at": "2026-06-14T00:00:00Z"},
    }
    state.update(overrides)
    return state


def _candidate(cid, state="eligible", created_at="2026-06-10T00:00:00Z"):
    return {"candidate_id": cid, "eligibility_state": state, "created_at": created_at}


def test_authorises_one_cycle_with_one_candidate():
    result = agc.decide_cycle(_live_state(), [_candidate("cand-a")], now=NOW)
    assert result["proceed"] is True
    assert result["max_vendors_this_cycle"] == 1
    assert result["selected_candidate_id"] == "cand-a"


def test_selects_oldest_eligible_deterministically():
    cands = [
        _candidate("cand-new", created_at="2026-06-12T00:00:00Z"),
        _candidate("cand-old", created_at="2026-06-01T00:00:00Z"),
        _candidate("cand-mid", created_at="2026-06-05T00:00:00Z"),
    ]
    result = agc.decide_cycle(_live_state(), cands, now=NOW)
    assert result["selected_candidate_id"] == "cand-old"


def test_never_more_than_one_vendor_per_cycle():
    cands = [_candidate(f"cand-{i}") for i in range(5)]
    result = agc.decide_cycle(_live_state(), cands, now=NOW)
    assert result["max_vendors_this_cycle"] == 1


def test_fallback_state_blocks_growth():
    result = agc.decide_cycle(_live_state(fallback_state=True), [_candidate("cand-a")], now=NOW)
    assert result["proceed"] is False
    assert result["state_authoritative"] is False


def test_hold_blocks_growth():
    result = agc.decide_cycle(_live_state(pause={"active": True}), [_candidate("cand-a")], now=NOW)
    assert result["proceed"] is False
    assert result["queue_decision"] == "pause"


def test_reserved_capacity_yields_to_integrity_work():
    result = agc.decide_cycle(
        _live_state(open_prs=[]), [_candidate("cand-a")], now=NOW,
        pending_integrity_work=True, total_pr_budget=3, open_prs_total=2,
    )
    assert result["proceed"] is False
    assert result["reason"] == "reserved_capacity_held_for_integrity_work"


def test_no_eligible_candidate_defers():
    result = agc.decide_cycle(_live_state(), [_candidate("cand-a", state="deferred_insufficient_evidence")], now=NOW)
    assert result["proceed"] is False
    assert result["reason"] == "no_eligible_candidate"
