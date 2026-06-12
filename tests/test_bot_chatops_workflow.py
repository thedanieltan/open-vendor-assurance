from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/bot-chatops.yml")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_CHATOPS = Path("docs/operations/contracts/bot-chatops.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_bot_chatops_workflow_is_issue_comment_only_with_minimal_permissions():
    workflow = load_yaml(WORKFLOW)

    assert set(workflow_triggers(workflow)) == {"issue_comment"}
    assert workflow_triggers(workflow)["issue_comment"] == {"types": ["created"]}
    assert workflow["permissions"] == {
        "contents": "read",
        "issues": "write",
        "pull-requests": "read",
    }
    assert "workflow_dispatch" not in workflow_text()
    assert "schedule" not in workflow_text()


def test_bot_chatops_workflow_is_maintainer_gated_and_hold_only():
    text = workflow_text()

    assert "allowedAssociations" in text
    assert "'OWNER'" in text
    assert "'MEMBER'" in text
    assert "'COLLABORATOR'" in text
    assert "command !== '/openva hold' && command !== '/openva unhold'" in text
    assert "const HOLD_LABEL = 'openva-hold'" in text
    assert "body !== command" in text


def test_bot_chatops_workflow_mutates_only_hold_label_and_audit_comment():
    text = workflow_text()

    assert "github.rest.issues.addLabels" in text
    assert "github.rest.issues.removeLabel" in text
    assert "github.rest.issues.createComment" in text
    assert "labels: [HOLD_LABEL]" in text
    assert "name: HOLD_LABEL" in text
    assert "github.rest.pulls.create" not in text
    assert "github.rest.pulls.merge" not in text
    assert "github.rest.git.createRef" not in text
    assert "actions/workflows" not in text
    assert "workflow_dispatches" not in text
    assert "enable-auto-merge" not in text


def test_bot_chatops_contracts_use_dedicated_hold_lane():
    authority = load_yaml(BOT_AUTHORITY)
    chatops = load_yaml(BOT_CHATOPS)
    queue = load_yaml(BOT_QUEUE_POLICY)
    inventory = load_yaml(WORKFLOW_INVENTORY)

    authority_lane = next(lane for lane in authority["lanes"] if lane["id"] == "bot_chatops_hold")
    queue_lane = next(lane for lane in queue["lanes"] if lane["lane_id"] == "bot_chatops_hold")
    inventory_entry = next(
        entry for entry in inventory["public_workflows"] if entry["name"] == "bot-chatops.yml"
    )
    hold_commands = {
        command["full_command"]: command
        for command in chatops["commands"]
        if command["full_command"] in {"/openva hold", "/openva unhold"}
    }

    assert authority_lane["workflows"] == ["bot-chatops.yml"]
    assert authority_lane["may_label_prs"] is True
    assert authority_lane["may_write_branches"] is False
    assert authority_lane["may_open_prs"] is False
    assert authority_lane["may_merge_prs"] is False
    assert authority_lane["may_enable_auto_merge"] is False
    assert authority_lane["may_write_catalog_truth"] is False
    assert queue_lane["schedule_window"] == "issue_comment_only"
    assert queue_lane["max_open_prs"] == 0
    assert inventory_entry["status"] == "active"
    assert inventory_entry["category"] == "bot_chatops"
    assert inventory_entry["authority_lane"] == "bot_chatops_hold"
    assert inventory_entry["trigger"] == "issue_comment"
    assert inventory_entry["triggers"] == ["issue_comment"]
    assert inventory_entry["creates_prs"] is False
    assert inventory_entry["merges_prs"] is False

    for command in hold_commands.values():
        assert command["lane_id"] == "bot_chatops_hold"
        assert command["queue_lane_id"] == "bot_chatops_hold"
        assert command["execution"]["hold_label"] == "openva-hold"
        assert command["execution"]["may_mutate_labels"] is True
        assert command["execution"]["may_post_comment"] is True
        assert command["execution"]["may_dispatch_workflows"] is False
        assert command["execution"]["may_mutate_catalog"] is False
