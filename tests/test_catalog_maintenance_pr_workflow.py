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
    assert inputs["pr_branch"]["required"] is False
    assert inputs["pr_title"]["required"] is False


def test_catalog_maintenance_pr_workflow_validates_inputs_and_creates_catalog_pr():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "env:" in text
    assert "PR_BRANCH:" in text
    assert "PR_TITLE:" in text
    assert "pr_branch must start with agent-" in text
    assert "pr_title must start with Catalog:" in text
    assert "branch:" in text
    assert "title:" in text
    assert "commit-message:" in text
    assert "python -m tools.openva.source_verification verify" in text
    assert "python -m tools.openva.source_discovery discover" in text
    assert "python -m tools.openva.promotion_planner plan" in text
    assert "python -m tools.openva.maintenance_actions apply" in text
    assert "python -m tools.openva.validate validate" in text
    assert "peter-evans/create-pull-request@v7" in text
    assert "delete-branch: false" in text
    assert "data" in text
    assert "indexes" in text
    assert "openva-pack.json" in text
    assert "gh pr merge" not in text
    assert "merge_pull_request" not in text
