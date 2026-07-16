from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva import discovery_mesh_config as config


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "discovery-ledger-append-pr.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_discovery_ledger_listener_observes_discovery_mesh_without_new_workflow() -> None:
    workflow = _workflow()
    workflow_run = workflow[True]["workflow_run"]

    assert workflow_run["workflows"] == ["catalog-growth-discovery", "discovery-mesh"]
    assert workflow_run["types"] == ["completed"]
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    }


def test_discovery_ledger_append_remains_confined_to_legacy_successful_runs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.event.workflow_run.name == 'catalog-growth-discovery'" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "discovery ledger append only accepts catalog-growth-discovery artifacts" in text


def test_rendered_smoke_report_is_unconditional_for_completed_push_runs() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["discovery-mesh-smoke-report"]
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.event.workflow_run.name == 'discovery-mesh'" in job["if"]
    assert "github.event.workflow_run.event == 'push'" in job["if"]
    assert "actions/runs/${RUN_ID}/jobs?per_page=100" in text
    assert "openva-discovery-mesh-aggregate" in text
    assert "rendered-discovery-differential.json" in text
    assert "Workflow conclusion" in text
    assert "Enforce hosted-smoke acceptance" in text


def test_hosted_smoke_contract_is_versioned_and_catalog_remains_uncapped() -> None:
    assert config.HOSTED_SMOKE_CONTRACT_VERSION == "0.1.0"
    assert config.CATALOG_VENDOR_LIMIT is None
    assert config.runtime_bounds("push") == config.DEPLOYMENT_SMOKE_BOUNDS
    assert config.runtime_bounds("schedule") == config.PRODUCTION_BOUNDS
