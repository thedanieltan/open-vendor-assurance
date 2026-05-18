from pathlib import Path

import yaml

from tools.openva.coverage_audit import CORE_ARTIFACT_TYPES, build_coverage_audit

WORKFLOW = Path(".github/workflows/coverage-audit.yml")
DOC = Path("docs/breadth-depth-operating-model.md")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_coverage_audit_report_is_inventory_only_and_non_advisory():
    report = build_coverage_audit()

    assert report["report_type"] == "breadth_depth_coverage_audit"
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "public_sources_only": True,
        "non_advisory": True,
        "coverage_scores_are_catalog_completeness_only": True,
    }
    assert report["summary"]["vendor_count"] >= 0
    assert report["summary"]["artifact_count"] >= 0


def test_coverage_audit_tracks_core_artifact_depth():
    report = build_coverage_audit()

    assert tuple(report["targets"]["core_artifact_types"]) == CORE_ARTIFACT_TYPES
    assert "vendors_missing_dpa" in report["gaps"]
    assert "vendors_missing_subprocessors_list" in report["gaps"]
    assert "vendors_below_three_core_artifacts" in report["gaps"]
    assert isinstance(report["vendors"], list)

    for vendor in report["vendors"]:
        assert "depth_score" in vendor
        assert "depth_tier" in vendor
        assert "core_artifacts_present" in vendor
        assert "core_artifacts_missing" in vendor


def test_coverage_audit_workflow_is_read_only_scheduled_and_manual():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)
    text = WORKFLOW.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert "python -m tools.openva.coverage_audit build --output reports/coverage-audit-report.json" in text
    assert "reports/coverage-audit-summary.md" in text
    assert "reports/coverage-audit-report.json" in text
    assert "reports/coverage-audit-vendors.csv" in text
    assert "actions/upload-artifact@v4" in text
    assert "peter-evans/create-pull-request" not in text
    assert "contents: write" not in text


def test_breadth_depth_operating_model_preserves_non_advisory_boundary():
    text = DOC.read_text(encoding="utf-8")

    assert "minimum materialized vendors: 150" in text
    assert "near-term materialized vendors: 250" in text
    assert "tier-1 vendors: at least 4 core artifact types" in text
    assert "vendor is compliant" in text
    assert "vendor is recommended" in text
    assert "Public-source-only rule remains controlling" in text
    assert "Do not add:" in text
