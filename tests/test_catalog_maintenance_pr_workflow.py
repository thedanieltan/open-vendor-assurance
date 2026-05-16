from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/catalog-maintenance-pr.yml")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_catalog_maintenance_pr_workflow_is_manual_pr_creator():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)

    assert set(triggers.keys()) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "write", "pull-requests": "write"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["promotion_plan_path"]["required"] is True
    assert inputs["promotion_plan_path"]["default"] == "maintenance/reviewed/promotion-plan.json"
    assert inputs["pr_branch"]["required"] is False
    assert inputs["pr_title"]["required"] is False


def test_catalog_maintenance_pr_workflow_consumes_reviewed_plan_without_live_network_steps():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "PROMOTION_PLAN_PATH:" in text
    assert "promotion_plan_path must be under maintenance/reviewed/" in text
    assert "python -m tools.openva.maintenance_actions apply" in text
    assert "--promotion-plan \"$PROMOTION_PLAN_PATH\"" in text
    assert "python -m tools.openva.cleanup_proposals build" in text
    assert "python -m tools.openva.validate validate" in text
    assert "git switch -c \"$PR_BRANCH\"" in text
    assert "git push --force-with-lease origin \"$PR_BRANCH\"" in text
    assert "gh pr list --state open --head \"$PR_BRANCH\"" in text
    assert "gh pr create" in text
    assert "gh pr edit" in text
    assert "data" in text
    assert "indexes" in text
    assert "openva-pack.json" in text
    assert "peter-evans/create-pull-request@v7" not in text
    assert "python -m tools.openva.source_verification verify" not in text
    assert "python -m tools.openva.source_discovery discover" not in text
    assert "python -m tools.openva.promotion_planner plan" not in text
    assert "source-verification-report.json" not in text
    assert "source-discovery-report.json" not in text
    assert "gh pr merge" not in text
    assert "merge_pull_request" not in text
