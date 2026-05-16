from pathlib import Path


WORKFLOW = Path(".github/workflows/catalog-maintenance-pr.yml")


def test_catalog_maintenance_workflow_has_reviewed_plan_batch_limit():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "max_actions_per_plan" in text
    assert "REQUESTED_MAX_ACTIONS_PER_PLAN" in text
    assert "--max-actions-per-plan" in text
    assert "SELECTED_PLAN_ACTION_COUNT" in text
    assert "PROMOTION_PLAN_ACTION_COUNT" in text
    assert "MAX_ACTIONS_PER_PLAN" in text


def test_catalog_maintenance_generated_pr_documents_batch_scale_posture():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Processes one reviewed plan per workflow run." in text
    assert "Max actions per generated PR" in text
    assert "Oversized reviewed plans must be split before application." in text
