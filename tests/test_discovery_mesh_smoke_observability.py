from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
REPORTER = ROOT / ".github" / "workflows" / "discovery-ledger-append-pr.yml"
BRIDGE = ROOT / ".github" / "workflows" / "catalog-growth-promotion-bridge.yml"


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_discovery_ledger_listener_observes_discovery_mesh_without_new_workflow() -> None:
    workflow = _workflow(REPORTER)
    workflow_run = workflow[True]["workflow_run"]

    assert workflow_run["workflows"] == ["catalog-growth-discovery", "discovery-mesh"]
    assert workflow_run["types"] == ["completed"]
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    }


def test_discovery_ledger_append_remains_confined_to_legacy_successful_runs() -> None:
    text = REPORTER.read_text(encoding="utf-8")

    assert "github.event.workflow_run.name == 'catalog-growth-discovery'" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "discovery ledger append only accepts catalog-growth-discovery artifacts" in text


def test_rendered_smoke_report_is_unconditional_for_completed_push_runs() -> None:
    workflow = _workflow(REPORTER)
    job = workflow["jobs"]["discovery-mesh-smoke-report"]
    text = REPORTER.read_text(encoding="utf-8")

    assert "github.event.workflow_run.name == 'discovery-mesh'" in job["if"]
    assert "github.event.workflow_run.event == 'push'" in job["if"]
    assert "actions/runs/${RUN_ID}/jobs?per_page=100" in text
    assert "openva-discovery-mesh-aggregate" in text
    assert "rendered-discovery-differential.json" in text
    assert "Workflow conclusion" in text
    assert "Enforce hosted-smoke acceptance" in text


def test_full_catalog_dispatch_uses_existing_actions_write_bridge() -> None:
    workflow = _workflow(BRIDGE)
    workflow_run = workflow[True]["workflow_run"]
    job = workflow["jobs"]["dispatch-full-catalog-rendered-acceptance"]
    text = BRIDGE.read_text(encoding="utf-8")

    assert workflow_run["workflows"] == ["catalog-growth-discovery", "discovery-mesh"]
    assert workflow["permissions"] == {
        "actions": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    assert "github.event.workflow_run.name == 'discovery-mesh'" in job["if"]
    assert "github.event.workflow_run.event == 'push'" in job["if"]
    assert "github.event.workflow_run.conclusion == 'success'" in job["if"]
    assert "Trigger full-catalog rendered-discovery acceptance" in text
    assert "agent/full-catalog-rendered-acceptance-*" in text
    assert 'PR_AUTHOR" != "$GITHUB_REPOSITORY_OWNER' in text
    assert "gh run list" in text
    assert "--event workflow_dispatch" in text
    assert "gh workflow run discovery-mesh.yml --ref main" in text


def test_original_catalog_growth_bridge_rejects_discovery_mesh_events() -> None:
    workflow = _workflow(BRIDGE)
    job = workflow["jobs"]["catalog-growth-promotion-bridge"]

    assert "github.event.workflow_run.name == 'catalog-growth-discovery'" in job["if"]
    assert "github.event.workflow_run.conclusion == 'success'" in job["if"]
