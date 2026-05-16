from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/promotion-plan-report.yml")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_promotion_plan_workflow_is_read_only_scheduled_and_manual():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert triggers["schedule"][0]["cron"] == "53 4 * * 2"


def test_promotion_plan_workflow_uploads_artifact_without_writes_or_pr_creation():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m tools.openva.promotion_planner plan" in text
    assert "actions/upload-artifact@v4" in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "peter-evans/create-pull-request" not in text
