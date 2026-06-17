"""Contract pins for the catalog-growth-promotion-bridge workflow (WP zero-install PR2).

These assert the structural guarantees of the discovery -> strict-growth promotion
handoff: it only runs after a successful main-branch discovery run, it dispatches the
single existing mutation workflow and nothing else, it never writes catalog state or
opens a PR, and it is registered consistently across the operating-model contracts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.discovery_promotion_bridge import DISPATCH_MODE, MUTATION_WORKFLOW

WORKFLOW = Path(".github/workflows/catalog-growth-promotion-bridge.yml")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")
WORKFLOW_RETIREMENT = Path("docs/operations/contracts/workflow-retirement.yaml")
OPERATING_MODEL = Path("docs/operations/WORKFLOW_OPERATING_MODEL.md")

NAME = "catalog-growth-promotion-bridge.yml"


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def inventory_entry() -> dict:
    entries = yaml.safe_load(WORKFLOW_INVENTORY.read_text(encoding="utf-8"))["public_workflows"]
    return next(entry for entry in entries if entry["name"] == NAME)


def retirement_entry() -> dict:
    entries = yaml.safe_load(WORKFLOW_RETIREMENT.read_text(encoding="utf-8"))["workflows"]
    return next(entry for entry in entries if entry["name"] == NAME)


def test_permissions_are_minimal_and_have_no_content_write():
    workflow = load()
    # Minimum required: actions:write (dispatch), and read-only everything else.
    assert workflow["permissions"] == {
        "actions": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    # The bridge must never be able to write repository content.
    assert workflow["permissions"]["contents"] == "read"


def test_triggers_on_discovery_completion_and_manual_exact_id():
    workflow = load()
    trig = triggers(workflow)
    body = text()
    assert set(trig.keys()) == {"workflow_run", "workflow_dispatch"}
    assert trig["workflow_run"]["workflows"] == ["catalog-growth-discovery"]
    assert trig["workflow_run"]["types"] == ["completed"]
    # Manual dispatch must require an EXACT run id, never resolve a "latest" run.
    assert trig["workflow_dispatch"]["inputs"]["discovery_run_id"]["required"] is True
    assert "github.event.workflow_run.id" in body
    assert "--limit 1" not in body
    assert "--limit 1" not in body


def test_only_proceeds_on_successful_upstream_discovery():
    body = text()
    assert "github.event.workflow_run.conclusion == 'success'" in body
    # Failed/cancelled discovery is rejected at the authority check too.
    assert '"$CONCLUSION" != "success"' in body


def test_rejects_non_main_and_foreign_discovery_runs():
    body = text()
    assert '"$HEAD_BRANCH" != "main"' in body
    assert '"$WORKFLOW_NAME" != "$DISCOVERY_WORKFLOW"' in body


def test_reads_strict_growth_plan_from_discovery_artifact():
    body = text()
    assert "--name openva-catalog-growth-discovery-artifacts" in body
    assert "strict-growth-promotion-plan.json" in body


def test_uses_decision_module_gate():
    body = text()
    assert "python -m tools.openva.discovery_promotion_bridge decide" in body
    assert "--hold-active" in body
    assert "--open-growth-pr-count" in body


def test_computes_hold_and_open_growth_pr_state():
    body = text()
    assert "openva-bot-paused" in body
    assert "--label catalog-growth" in body


def test_dispatches_only_the_existing_mutation_workflow():
    body = text()
    workflow = load()
    env = workflow["jobs"]["catalog-growth-promotion-bridge"]["env"]
    assert env["MUTATION_WORKFLOW"] == MUTATION_WORKFLOW == "candidate-promotion-pr.yml"
    # Exactly one workflow-dispatch call, and it targets the single mutation workflow.
    assert body.count("gh workflow run") == 1
    assert 'gh workflow run "$MUTATION_WORKFLOW"' in body
    assert "promotion_plan_mode=$MODE" in body
    # The dispatched mode is the safe regenerate-current-evidence strict-growth mode.
    assert DISPATCH_MODE == "strict-growth-latest"


def test_dispatch_is_gated_on_decision():
    workflow = load()
    steps = workflow["jobs"]["catalog-growth-promotion-bridge"]["steps"]
    dispatch_step = next(s for s in steps if s.get("name", "").startswith("Dispatch existing"))
    assert dispatch_step["if"] == "steps.decide.outputs.dispatch == 'true'"


def test_bridge_never_writes_catalog_or_opens_or_merges_prs():
    body = text()
    assert "gh pr create" not in body
    assert "gh pr merge" not in body
    assert "git commit" not in body
    assert "git push" not in body
    # No catalogue write paths are touched.
    assert "data/vendors" not in body
    assert "indexes/" not in body
    assert "maintenance/candidates" not in body
    # candidate intake stays inert; the bridge must not touch its flag.
    assert "execution_wired" not in body


def test_records_source_run_provenance():
    body = text()
    assert "bridged from discovery run $RUN_ID" in body
    assert "GITHUB_STEP_SUMMARY" in body


def test_uses_node24_compatible_actions():
    body = text()
    assert "actions/checkout@v5" in body
    assert "actions/setup-python@v6" in body
    assert "actions/upload-artifact@v6" in body
    for stale in ("actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4"):
        assert stale not in body


def test_concurrency_serializes_without_cancelling_in_progress():
    workflow = load()
    assert workflow["concurrency"]["group"] == "catalog-growth-promotion-bridge"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_registered_in_workflow_inventory_as_dispatch_only():
    entry = inventory_entry()
    assert entry["loop"] == "catalog_growth"
    assert entry["status"] == "core"
    assert set(entry["triggers"]) == {"workflow_run", "workflow_dispatch"}
    assert entry["permissions"] == {
        "actions": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    assert entry["creates_prs"] is False
    assert entry["merges_prs"] is False
    assert entry["writes_repository_state"] is False


def test_registered_in_workflow_retirement_as_active_core():
    entry = retirement_entry()
    assert entry["current_status"] == "active"
    assert entry["inventory_status"] == "core"
    assert entry["retirement_candidate"] is False
    assert entry["retirement_ready"] is False
    assert entry["must_not_retire_yet"] is True


def test_operating_model_documents_the_bridge_handoff():
    body = OPERATING_MODEL.read_text(encoding="utf-8")
    assert "catalog-growth-promotion-bridge.yml" in body
