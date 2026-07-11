from __future__ import annotations

from tools.openva import autonomous_growth_controller as growth


def candidate(
    candidate_id: str,
    *,
    created_at: str,
    eligibility_state: str = "eligible",
    demand_signals: list[str] | dict[str, bool] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "created_at": created_at,
        "eligibility_state": eligibility_state,
        "demand_signals": demand_signals or [],
    }


def test_phase_9_demand_signal_weights_are_stable() -> None:
    assert growth.DEMAND_SIGNAL_WEIGHTS == {
        "repeated_user_agent_misses": 100,
        "frequently_requested_vendor": 80,
        "frequently_missing_source_type": 60,
        "repeated_ambiguous_identity": 50,
        "rediscovered_candidate_url": 40,
        "high_use_broken_gated_unavailable_url": 30,
    }


def test_demand_signal_summary_accepts_aliases_and_preserves_unknowns() -> None:
    summary = growth.demand_signal_summary(
        candidate(
            "cand-1",
            created_at="2026-07-06T00:00:00Z",
            demand_signals=[
                "repeated-user-misses",
                "frequent_vendor_request",
                "unexpected_future_signal",
            ],
        )
    )

    assert summary["priority"] == 180
    assert summary["known_signals"] == (
        "repeated_user_agent_misses",
        "frequently_requested_vendor",
    )
    assert summary["unknown_signals"] == ("unexpected_future_signal",)
    assert summary["not_advice"] is True


def test_demand_prioritises_already_eligible_candidate_over_older_candidate() -> None:
    older = candidate("cand-old", created_at="2026-07-01T00:00:00Z")
    newer_with_demand = candidate(
        "cand-new-demand",
        created_at="2026-07-05T00:00:00Z",
        demand_signals=["frequently_requested_vendor"],
    )

    selected = growth.select_one_candidate([older, newer_with_demand])

    assert selected == newer_with_demand


def test_demand_does_not_make_ineligible_candidate_selectable() -> None:
    ineligible_with_demand = candidate(
        "cand-ineligible-demand",
        created_at="2026-07-01T00:00:00Z",
        eligibility_state="deferred_insufficient_evidence",
        demand_signals=[
            "repeated_user_agent_misses",
            "frequently_requested_vendor",
            "frequently_missing_source_type",
        ],
    )
    eligible_without_demand = candidate("cand-eligible", created_at="2026-07-05T00:00:00Z")

    selected = growth.select_one_candidate([ineligible_with_demand, eligible_without_demand])

    assert selected == eligible_without_demand


def test_candidate_selection_tie_breaker_remains_oldest_first() -> None:
    newer = candidate(
        "cand-newer",
        created_at="2026-07-05T00:00:00Z",
        demand_signals=["rediscovered_candidate_url"],
    )
    older = candidate(
        "cand-older",
        created_at="2026-07-01T00:00:00Z",
        demand_signals=["rediscovered_candidate_url"],
    )

    selected = growth.select_one_candidate([newer, older])

    assert selected == older


def test_no_eligible_candidate_returns_none_even_with_demand() -> None:
    selected = growth.select_one_candidate(
        [
            candidate(
                "cand-ambiguous",
                created_at="2026-07-01T00:00:00Z",
                eligibility_state="deferred_cross_authority",
                demand_signals=["repeated_user_agent_misses"],
            ),
            candidate(
                "cand-unsafe",
                created_at="2026-07-02T00:00:00Z",
                eligibility_state="rejected_unsafe_url",
                demand_signals=["frequently_requested_vendor"],
            ),
        ]
    )

    assert selected is None


def test_growth_decision_reports_demand_signals_as_explanation_only(monkeypatch) -> None:
    # Current live-state contract: authority comes from state_source provenance
    # (state_is_authoritative), and the lane requires fresh evidence — the old
    # state_authoritative flag and missing evidence block deferred every cycle.
    queue_state = {
        "lane": growth.GROWTH_LANE,
        "state_source": "github_live",
        "status": "idle",
        "active_prs": [],
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "pause": {"active": False},
        "evidence": {"generated_at": "2026-07-06T00:00:00Z"},
        "cooldown_until": None,
        "hold_until": None,
    }
    selected = candidate(
        "cand-demand",
        created_at="2026-07-01T00:00:00Z",
        demand_signals=["repeated_user_agent_misses", "rediscovered_candidate_url"],
    )

    class Binding:
        eligible = True
        reasons: tuple[str, ...] = ()

        def binding(self) -> dict[str, str]:
            return {
                "candidate_id": "cand-demand",
                "candidate_path": "maintenance/candidates/cand-demand.json",
                "content_digest": "sha256:" + "a" * 64,
                "selected_vendor": "vendor",
                "candidate_origin": "coverage_gap",
            }

    monkeypatch.setattr(growth.vendor_resolution, "evaluate_persisted_candidate", lambda *_args, **_kwargs: Binding())

    decision = growth.decide_cycle(queue_state, [selected], now=growth.bot_queue.parse_time("2026-07-06T00:00:00Z"))

    assert decision["proceed"] is True
    assert decision["reason"] == "growth_cycle_authorised"
    assert decision["selected_candidate_id"] == "cand-demand"
    assert decision["selected_candidate_demand_priority"] == 140
    assert decision["selected_candidate_demand_signals"] == [
        "repeated_user_agent_misses",
        "rediscovered_candidate_url",
    ]
    assert decision["selected_candidate"]["candidate_id"] == "cand-demand"
    assert decision["not_advice"] is True
