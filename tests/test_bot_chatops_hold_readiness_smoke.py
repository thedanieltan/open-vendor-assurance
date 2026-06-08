from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.bot_chatops import build_decision
from tools.openva.bot_chatops_execute import HOLD_LABEL, execute_command

BOT_CHATOPS = Path("docs/operations/contracts/bot-chatops.yaml")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
WORKFLOW_DIR = Path(".github/workflows")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def command(full_command: str) -> dict:
    return next(entry for entry in load_yaml(BOT_CHATOPS)["commands"] if entry["full_command"] == full_command)


def authority_lane(lane_id: str) -> dict:
    return next(entry for entry in load_yaml(BOT_AUTHORITY)["lanes"] if entry["id"] == lane_id)


def test_hold_unhold_are_local_audit_only():
    for full_command in ("/openva hold", "/openva unhold"):
        entry = command(full_command)
        execution = entry["execution"]

        assert execution["mode"] == "local_audit_only"
        assert execution["hold_label"] == HOLD_LABEL == "openva-hold"
        assert execution["may_mutate_labels"] is False
        assert execution["may_dispatch_workflows"] is False
        assert execution["may_mutate_catalog"] is False
        assert execution["may_post_comment"] is False


def test_hold_unhold_need_dedicated_label_only_lane_before_live_activation():
    for full_command in ("/openva hold", "/openva unhold"):
        entry = command(full_command)
        lane = authority_lane(entry["lane_id"])

        assert entry["lane_id"] == "support_agent_pr"
        assert lane["may_write_branches"] is True
        assert lane["may_open_prs"] is True
        assert lane["may_write_catalog_truth"] is True


def test_maintainer_parser_accepts_only_expected_current_commands():
    assert build_decision("/openva hold", "maintainer")["decision"] == "accepted_executable"
    assert build_decision("/openva unhold", "maintainer")["decision"] == "accepted_executable"
    assert build_decision("/openva explain-strict-growth", "maintainer")["decision"] == "accepted_executable"
    assert build_decision("/openva promote-reviewed-plan", "maintainer")["decision"] == "accepted_report_only"


def test_bad_hold_inputs_and_non_maintainers_are_denied():
    for sample in ("/openva hold #123", "/openva hold all", "/openva hold urgent", "/openva hold\n/openva promote-reviewed-plan"):
        assert build_decision(sample, "maintainer")["decision"] == "denied"

    for role in ("viewer", "unknown", "contributor"):
        decision = build_decision("/openva hold", role)
        assert decision["decision"] == "denied"
        assert "actor_not_authorized" in decision["reasons"]


def test_execution_does_not_apply_live_label_without_queue_state():
    report = execute_command("/openva hold", "maintainer")

    assert report["decision"] == "denied"
    assert report["executed"] is False
    assert report["execution_report"] is None
    assert report["queue_decision"]["decision"] == "deny"
    assert "queue_state_required" in report["queue_decision"]["reasons"]


def test_no_live_bot_chatops_workflow_exists_yet():
    assert not (WORKFLOW_DIR / "bot-chatops.yml").exists()
