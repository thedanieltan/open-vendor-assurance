from pathlib import Path

import yaml

from tools.openva.source_health import build_source_health_report

WORKFLOW = Path(".github/workflows/source-health-report.yml")

PUBLIC_ACCESS_CLASSES = {
    "public_web",
    "public_pdf",
    "public_doc_portal",
    "public_landing_gated_docs",
}


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_source_health_report_workflow_is_read_only_scheduled_and_manual():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert triggers["schedule"][0]["cron"] == "17 3 * * 1"


def test_source_health_report_workflow_uploads_artifact_without_writes_or_pr_creation():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m tools.openva.source_health build --output source-health-report.json" in text
    assert "actions/upload-artifact@v4" in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "peter-evans/create-pull-request" not in text


def test_source_health_report_is_inventory_only_and_non_advisory():
    report = build_source_health_report()

    assert report["report_type"] == "source_health_inventory"
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "public_sources_only": True,
        "non_advisory": True,
    }
    assert report["summary"]["vendor_count"] >= 0
    assert report["summary"]["source_count"] >= 0
    assert isinstance(report["sources"], list)


def test_source_health_report_preserves_public_metadata_contract():
    report = build_source_health_report()

    for source in report["sources"]:
        assert source["source_url"].startswith(("http://", "https://"))
        assert source["access_class"] in PUBLIC_ACCESS_CLASSES
        assert source["rights_class"] == "metadata_only"
