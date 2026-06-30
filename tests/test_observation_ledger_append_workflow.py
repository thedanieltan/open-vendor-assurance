"""WP35.5 append-PR workflow structure pins."""

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/observation-ledger-append-pr.yml")


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_permissions_and_triggers():
    workflow = load()
    assert workflow["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "read",
    }
    assert set(triggers(workflow).keys()) == {"workflow_run", "workflow_dispatch"}


def test_triggers_on_source_maintenance_run_and_manual_exact_id():
    workflow = load()
    text = WORKFLOW.read_text(encoding="utf-8")
    trig = triggers(workflow)
    assert trig["workflow_run"]["workflows"] == ["source-maintenance-report"]
    # Manual dispatch must require an EXACT run id, never "latest".
    assert trig["workflow_dispatch"]["inputs"]["source_run_id"]["required"] is True
    assert "github.event.workflow_run.id" in text
    assert "inputs.source_run_id" in text
    assert "--limit 1" not in text  # never resolve an arbitrary latest run


def test_only_proceeds_on_successful_upstream_run():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.workflow_run.conclusion == 'success'" in text


def test_applies_both_observation_labels():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--add-label \"observation-ledger\"" in text
    assert "--add-label \"automerge:observation\"" in text


def test_latest_index_can_create_pr_without_new_event_rows():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "new_row_count == '0'" in text
    assert "new_row_count != '0'" in text
    assert "No committed observation continuity diff." in text
    assert "steps.diff.outputs.has_changes == 'true'" in text


def test_diff_scope_guard_and_no_direct_merge():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "maintenance/source-observations/events" in text
    assert "maintenance/source-observations/latest-observations.json" in text
    # The append workflow never merges; merge is the agent-automerge job's role.
    assert "gh pr merge" not in text


def test_uses_plan_and_append_clis():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m tools.openva.observation_automerge plan" in text
    assert "python -m tools.openva.observation_ledger append" in text
    assert "python -m tools.openva.observation_ledger install-latest" in text
