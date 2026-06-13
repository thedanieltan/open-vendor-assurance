"""WP37 authority-level taxonomy + quorum-promotion lane contract tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva import bot_quorum as q

BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")


def contract() -> dict:
    return yaml.safe_load(BOT_AUTHORITY.read_text(encoding="utf-8"))


def lanes_by_id() -> dict:
    return {lane["id"]: lane for lane in contract()["lanes"]}


def levels_by_number() -> dict:
    return {entry["level"]: entry for entry in contract()["authority_levels"]}


def test_authority_levels_0_through_5_are_declared():
    levels = levels_by_number()
    assert set(levels) == {0, 1, 2, 3, 4, 5}
    for entry in levels.values():
        assert entry["name"]
        assert entry["description"]
        assert isinstance(entry["may_write_catalog_truth"], bool)
        assert isinstance(entry["may_record_decision"], bool)
        assert isinstance(entry["may_merge"], bool)


def test_level_capabilities_separate_decision_from_merge():
    levels = levels_by_number()
    # Report-only holds nothing.
    assert levels[0] == {**levels[0], "may_write_catalog_truth": False, "may_record_decision": False, "may_merge": False}
    # Reviewers cannot write, decide, or merge.
    assert not levels[2]["may_record_decision"] and not levels[2]["may_merge"]
    # Deciding records decisions but cannot merge.
    assert levels[3]["may_record_decision"] and not levels[3]["may_merge"]
    # Merge authority merges but does not decide.
    assert levels[4]["may_merge"] and not levels[4]["may_record_decision"]


def test_every_lane_declares_an_authority_level_in_range():
    for lane in contract()["lanes"]:
        assert lane["authority_level"] in {0, 1, 2, 3, 4, 5}, lane["id"]


def test_no_single_lane_both_decides_and_merges():
    # Separation of duty at the lane level: a lane may not both write catalog
    # truth (decide) and merge. No single bot holds discovery + decision + merge.
    assert contract()["default_posture"]["no_single_bot_holds_discovery_decision_and_merge"] is True
    for lane in contract()["lanes"]:
        assert not (lane["may_write_catalog_truth"] and lane["may_merge_prs"]), lane["id"]


def test_report_only_lanes_neither_decide_nor_merge():
    for lane in contract()["lanes"]:
        if lane["authority_level"] == 0:
            assert lane["may_write_catalog_truth"] is False, lane["id"]
            assert lane["may_merge_prs"] is False, lane["id"]


def test_quorum_promotion_lane_is_declared_and_status_only():
    lane = lanes_by_id()["catalog_growth_quorum_promotion"]
    assert lane["authority_level"] == 3
    assert lane["may_write_catalog_truth"] is True
    assert lane["may_merge_prs"] is False
    assert lane["may_enable_auto_merge"] is False
    assert set(lane["allowed_labels"]) == {"quorum-promotion", "automerge:quorum-promotion"}
    assert "candidate-promotion-pr.yml" in lane["workflows"]
    assert "agent-automerge.yml" in lane["workflows"]
    assert "data/vendors/**" in lane["allowed_paths"]
    assert "maintenance/machine-decisions/**" in lane["allowed_paths"]


def test_reviewer_and_deciding_levels_match_quorum_module():
    levels = levels_by_number()
    assert q.REVIEWER_LEVEL == 2 and levels[2]["name"] == "independent_reviewer"
    assert q.DECIDING_LEVEL == 3 and levels[3]["name"] == "deciding"
