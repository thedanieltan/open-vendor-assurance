from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/source-maintenance-report.yml")
RUNBOOK = Path("docs/source-trust/SOURCE_TRUST_OPERATIONS_RUNBOOK.md")


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_source_maintenance_workflow_exposes_scheduler_controls():
    workflow = load_workflow()
    triggers = workflow_triggers(workflow)
    inputs = triggers["workflow_dispatch"]["inputs"]
    text = WORKFLOW.read_text(encoding="utf-8")

    assert inputs["verification_scope"]["default"] == "scheduled_shard"
    assert inputs["verification_scope"]["options"] == [
        "scheduled_shard",
        "full",
        "custom_shard",
    ]
    assert inputs["source_shard_count"]["default"] == "4"
    assert "SHARD_INDEX=$(( ${{ github.run_number }} % SHARD_COUNT ))" in text
    assert "--shard-count" in text
    assert "--shard-index" in text
    assert "source_shard_index is required when verification_scope=custom_shard" in text
    assert "python -m tools.openva.source_verification verify" in text


def test_source_maintenance_workflow_remains_single_read_only_operating_workflow():
    workflow = load_workflow()
    triggers = workflow_triggers(workflow)
    text = WORKFLOW.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert "gh pr create" not in text
    assert "gh pr merge" not in text
    assert "peter-evans/create-pull-request" not in text


def test_source_trust_runbook_documents_partial_snapshot_semantics():
    text = RUNBOOK.read_text(encoding="utf-8")

    for phrase in [
        "Sharding is an internal scope selector, not a new workflow.",
        "scheduled_shard",
        "custom_shard",
        "scope.verified_source_paths",
        "scope.is_partial",
        "partial source-maintenance artifacts as maintenance snapshots",
    ]:
        assert phrase in text
