from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/cleanup-proposal-report.yml")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_cleanup_proposal_workflow_is_read_only_scheduled_and_manual():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert triggers["schedule"][0]["cron"] == "11 6 * * 3"


def test_cleanup_proposal_workflow_builds_reports_without_mutation_or_pr_creation():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m tools.openva.source_verification verify" in text
    assert "python -m tools.openva.source_discovery discover" in text
    assert "python -m tools.openva.promotion_planner plan" in text
    assert "python -m tools.openva.cleanup_proposals build" in text
    assert "cleanup-proposal.md" in text
    assert "actions/upload-artifact@v4" in text
    assert "--write" not in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "peter-evans/create-pull-request" not in text
