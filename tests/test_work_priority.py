"""WP40C global work priority tests: integrity/maintenance outrank growth."""

from __future__ import annotations

from tools.openva import work_priority as wp


def test_priority_order_matches_policy():
    assert wp.priority_order() == [
        "observation_continuity",
        "release_repository_safety",
        "rollback",
        "quarantine",
        "source_repair",
        "quorum_promotion",
        "machine_provisional_growth",
        "discovery",
        "optional_reports",
    ]


def test_maintenance_outranks_growth():
    assert wp.rank("rollback") < wp.rank("machine_provisional_growth")
    assert wp.rank("quarantine") < wp.rank("machine_provisional_growth")
    assert wp.rank("source_repair") < wp.rank("machine_provisional_growth")
    assert wp.rank("quorum_promotion") < wp.rank("discovery")


def test_select_next_returns_highest_priority():
    assert wp.select_next(["machine_provisional_growth", "rollback", "discovery"]) == "rollback"
    assert wp.select_next(["discovery", "machine_provisional_growth"]) == "machine_provisional_growth"
    assert wp.select_next([]) is None


def test_order_eligible_is_deterministic():
    assert wp.order_eligible(["discovery", "quarantine", "source_repair"]) == [
        "quarantine",
        "source_repair",
        "discovery",
    ]


def test_reserved_capacity_holds_growth_when_integrity_pending():
    decision = wp.capacity_decision(
        "machine_provisional_growth",
        total_pr_budget=3,
        open_prs_total=2,
        pending_integrity_work=True,
    )
    assert decision["decision"] == "defer"
    assert decision["reason"] == "reserved_capacity_held_for_integrity_work"


def test_integrity_work_is_not_blocked_by_reserve():
    decision = wp.capacity_decision(
        "rollback",
        total_pr_budget=3,
        open_prs_total=2,
        pending_integrity_work=True,
    )
    assert decision["decision"] == "allow"


def test_growth_allowed_when_enough_free_budget():
    decision = wp.capacity_decision(
        "machine_provisional_growth",
        total_pr_budget=3,
        open_prs_total=0,
        pending_integrity_work=True,
    )
    assert decision["decision"] == "allow"


def test_no_budget_defers_everything():
    decision = wp.capacity_decision(
        "rollback", total_pr_budget=1, open_prs_total=1, pending_integrity_work=False
    )
    assert decision["decision"] == "defer"
    assert decision["reason"] == "no_free_pr_budget"


def test_lane_mapping_resolves_known_lanes():
    assert wp.lane_work_class("catalog_growth_promotion") == "machine_provisional_growth"
    assert wp.lane_work_class("source_rollback") == "rollback"
    assert wp.lane_work_class("unknown_lane") is None
