from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/cleanup-proposal-issue.yml")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_cleanup_proposal_issue_workflow_has_limited_issue_write_permission():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert triggers["schedule"][0]["cron"] == "23 7 * * 3"


def test_cleanup_proposal_issue_workflow_updates_issue_without_catalog_or_pr_writes():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m tools.openva.source_verification verify" in text
    assert "python -m tools.openva.source_discovery discover" in text
    assert "python -m tools.openva.promotion_planner plan" in text
    assert "python -m tools.openva.cleanup_proposals build" in text
    assert "gh issue create" in text
    assert "gh issue edit" in text
    assert "actions/upload-artifact@v4" in text
    assert "--write" not in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "peter-evans/create-pull-request" not in text
    assert "gh pr create" not in text
