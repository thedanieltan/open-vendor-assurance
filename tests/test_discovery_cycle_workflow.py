from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/discovery-cycle.yml")


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def triggers() -> dict:
    workflow = load()
    return workflow.get("on") or workflow.get(True) or {}


def test_cycle_is_event_driven_not_another_schedule() -> None:
    trig = triggers()
    assert set(trig) == {"workflow_run", "workflow_dispatch"}
    assert trig["workflow_run"]["workflows"] == ["discovery-mesh"]
    assert trig["workflow_run"]["types"] == ["completed"]
    assert "schedule" not in trig


def test_automatic_path_accepts_only_successful_production_discovery_mesh() -> None:
    guard = str(load()["jobs"]["discovery-cycle"]["if"])
    assert "github.event.workflow_run.name == 'discovery-mesh'" in guard
    assert "github.event.workflow_run.conclusion == 'success'" in guard
    assert "github.event.workflow_run.event == 'schedule'" in guard
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in guard


def test_source_artifact_is_attempt_bound_and_downloaded_by_exact_id() -> None:
    body = text()
    assert "attempt,conclusion,event,headBranch,headSha,number,startedAt,workflowName" in body
    assert 'created_at >= $started' in body
    assert 'name == "openva-discovery-mesh-aggregate"' in body
    assert "expected exactly one current-attempt Discovery Mesh aggregate artifact" in body
    assert 'actions/artifacts/${ARTIFACT_ID}/zip' in body
    assert "gh run download" not in body


def test_cycle_uses_fresh_mesh_breadth_and_rotating_workset() -> None:
    body = text()
    assert "vendor-breadth-candidates.json" in body
    assert "python -m tools.openva.discovery_cycle select-workset" in body
    assert '--cycle-number "$CYCLE_NUMBER"' in body
    assert "python -m tools.openva.vendor_candidate_discovery discover" not in body


def test_network_source_discovery_occurs_once_then_enters_unified_ingress() -> None:
    body = text()
    assert body.count("python -m tools.openva.source_discovery discover-vendor-candidates") == 1
    assert "python -m tools.openva.discovery_cycle_ingress ingest" in body
    assert "python -m tools.openva.candidate_intake_guard" in body
    assert "python -m tools.openva.candidate_activation verify-intake" in body


def test_cycle_writes_only_noncanonical_candidate_staging() -> None:
    body = text()
    assert "git add maintenance/candidates" in body
    assert "maintenance/candidates/*.json" in body
    assert "git add data" not in body
    assert "data/vendors" not in body
    assert "candidate-promotion-pr.yml" in body


def test_candidate_intake_pr_uses_governed_labels_and_triggering_token() -> None:
    body = text()
    assert "OPENVA_AUTOMERGE_TOKEN is required" in body
    assert "--add-label candidate-intake --add-label automerge:candidate-intake" in body
    assert "agent-candidate-intake-discovery-cycle-" in body
    assert "Candidate intake: stage discovered candidate records" in body


def test_raw_cycle_evidence_is_artifact_bound() -> None:
    body = text()
    assert "python -m tools.openva.discovery_cycle build-bundle" in body
    assert "reports/discovery-cycle-bundle.json" in body
    assert "actions/upload-artifact@v6" in body
    assert "retention-days: 30" in body
