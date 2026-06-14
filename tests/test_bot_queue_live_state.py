"""WP40C Issue 7: fallback queue state can never authorise a production write."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.openva import bot_queue

NOW = datetime(2026, 6, 14, tzinfo=UTC)

# A write-capable lane with otherwise-clean state.
WRITE_LANE = "catalog_growth_promotion"


def _clean_state(**overrides):
    state = {
        "lane_id": WRITE_LANE,
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "pause": {"active": False},
        "evidence": {"generated_at": "2026-06-14T00:00:00Z"},
    }
    state.update(overrides)
    return state


def test_authoritative_detection():
    assert bot_queue.state_is_authoritative({"state_source": "github_live"}) is True
    assert bot_queue.state_is_authoritative({"fallback_state": True, "state_source": "github_live"}) is False
    assert bot_queue.state_is_authoritative({"state_source": "workflow_local_fallback"}) is False
    assert bot_queue.state_is_authoritative({}) is False


def test_fallback_state_cannot_authorize_write_when_enforced():
    state = _clean_state(fallback_state=True)
    report = bot_queue.evaluate(WRITE_LANE, state, now=NOW, enforce_live_state=True)
    assert report["decision"] != "allow"
    assert "non_authoritative_state_cannot_authorize_write" in report["reasons"]
    assert report["state_authoritative"] is False


def test_missing_provenance_cannot_authorize_write_when_enforced():
    state = _clean_state()  # no state_source
    report = bot_queue.evaluate(WRITE_LANE, state, now=NOW, enforce_live_state=True)
    assert report["decision"] == "defer"
    assert "non_authoritative_state_cannot_authorize_write" in report["reasons"]


def test_authoritative_live_state_may_be_allowed():
    state = _clean_state(state_source="github_live")
    report = bot_queue.evaluate(WRITE_LANE, state, now=NOW, enforce_live_state=True)
    assert report["state_authoritative"] is True
    assert report["decision"] == "allow"


def test_enforcement_off_preserves_legacy_behaviour():
    # Without enforcement the evaluator behaves as before (back-compat).
    state = _clean_state()
    report = bot_queue.evaluate(WRITE_LANE, state, now=NOW)
    assert report["live_state_enforced"] is False
    assert report["decision"] == "allow"
