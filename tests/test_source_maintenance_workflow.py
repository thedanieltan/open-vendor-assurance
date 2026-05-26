from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/source-maintenance-report.yml")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_source_maintenance_workflow_is_read_only_scheduled_and_manual():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert triggers["schedule"][0]["cron"] == "29 5 * * 3"


def test_source_maintenance_workflow_runs_full_non_mutating_pipeline():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m tools.openva.source_health build --output source-health-report.json" in text
    assert "python -m tools.openva.source_verification verify" in text
    assert "python -m tools.openva.source_discovery discover" in text
    assert "python -m tools.openva.source_repair_sweep build" in text
    assert "python -m tools.openva.promotion_planner plan" in text
    assert "python -m tools.openva.cleanup_proposals build" in text
    assert "--verification-report source-verification-report.json" in text
    assert "--discovery-report source-discovery-report.json" in text
    assert "--source-verification-report source-verification-report.json" in text
    assert "--source-discovery-report source-discovery-report.json" in text
    assert "summary.md" in text
    assert "source-health.csv" in text
    assert "source-verification.csv" in text
    assert "source-discovery-candidates.csv" in text
    assert "source-discovery-unavailable.csv" in text
    assert "source-repair-sweep-report.json" in text
    assert "source-repair-sweep-strict-candidates.csv" in text
    assert "source-repair-sweep-human-review.csv" in text
    assert "source-repair-sweep-no-replacement.csv" in text
    assert "promotion-plan-actions.csv" in text
    assert "cleanup-proposal.md" in text
    assert "actions/upload-artifact@v6" in text
    assert "--write" not in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "peter-evans/create-pull-request" not in text
