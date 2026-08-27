from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "rendered-discovery-acceptance-controller.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_controller_has_exact_triggers_permissions_and_shared_concurrency() -> None:
    workflow = _workflow()
    triggers = workflow[True]

    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"] == {
        "workflows": ["discovery-mesh"],
        "types": ["completed"],
    }
    assert workflow["permissions"] == {
        "actions": "write",
        "contents": "read",
        "pull-requests": "write",
    }
    assert workflow["concurrency"] == {
        "group": "catalog-growth-promotion-bridge",
        "cancel-in-progress": False,
    }


def test_controller_is_exact_gated_and_returns_a_durable_run_receipt() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["dispatch-and-publish-receipt"]
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.event.workflow_run.name == 'discovery-mesh'" in job["if"]
    assert "github.event.workflow_run.event == 'push'" in job["if"]
    assert "github.event.workflow_run.conclusion == 'success'" in job["if"]
    assert "Trigger full-catalog rendered-discovery acceptance" in text
    assert "agent/full-catalog-rendered-acceptance-*" in text
    assert 'PR_AUTHOR" != "$GITHUB_REPOSITORY_OWNER' in text
    assert "X-GitHub-Api-Version: 2026-03-10" in text
    assert "return_run_details" not in text
    assert ".workflow_run_id // empty" in text
    assert "openva-full-catalog-dispatch source-smoke=" in text
    assert "openva-full-catalog-run-id=" in text
    assert "openva-full-catalog-dispatch-receipt" in text
    assert "default 32-shard matrix / no vendor limit" in text
    # This controller intentionally has no checkout. GitHub CLI PR commands must
    # therefore carry explicit repository context rather than relying on .git.
    assert 'gh pr comment "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --body-file "$BODY"' in text


def test_controller_does_not_write_catalog_state_or_create_pull_requests() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in text
    assert "contents: write" not in text
    assert "gh pr create" not in text
    assert "gh pr merge" not in text
    assert "candidate-promotion-pr.yml" not in text
    assert "writes_canonical_sources: false" in text
