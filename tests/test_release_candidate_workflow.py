from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/release-candidate.yml")


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_release_candidate_workflow_is_manual_only_and_read_only():
    workflow = load_workflow()
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["source_health_policy"]["default"] == "enforce"
    assert triggers["workflow_dispatch"]["inputs"]["source_health_policy"]["options"] == [
        "report_only",
        "enforce",
    ]


def test_release_candidate_workflow_wraps_existing_release_commands():
    text = WORKFLOW.read_text(encoding="utf-8")

    expected_commands = [
        'pip install -e "services/openva_match_service[dev]"',
        "python -m tools.openva.validate validate",
        "pytest -q",
        "python -m tools.openva.release_smoke",
        "gh run list",
        "gh run download",
        "python -m tools.openva.release_source_health check",
        "python -m tools.openva.release_artifacts build",
        "python -m tools.openva.release_artifacts check",
    ]
    for command in expected_commands:
        assert command in text
    assert "--enforce" in text
    assert "SOURCE_HEALTH_EXIT_CODE" in text
    assert "Enforce source health readiness result" in text


def test_release_candidate_downloads_latest_source_maintenance_artifact_before_readiness():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "--workflow source-maintenance-report.yml" in text
    assert "--name openva-source-maintenance-report" in text
    assert "source-verification-report.json" in text
    assert "source health artifact unavailable" in text
    assert text.index("Download latest source maintenance artifacts") < text.index("Build source health readiness")


def test_release_candidate_downloads_latest_source_refinement_scan_before_readiness():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Download latest source refinement scan artifacts" in text
    assert "--workflow source-refinement-scan.yml" in text
    assert "--name openva-confirmed-p0-source-refinement-scan" in text
    assert "source-refinement-artifacts/confirmed-p0-repair-candidates.json" in text
    assert "confirmed P0 scan artifact unavailable" in text
    assert text.index("Download latest source refinement scan artifacts") < text.index("Build source health readiness")


def test_release_candidate_workflow_uploads_manifest_and_source_health_readiness():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v6" in text
    assert "name: openva-release-candidate-artifacts" in text
    assert "release-artifacts.json" in text
    assert "release-source-health-readiness.json" in text
    assert "release-source-health-summary.md" in text
    assert text.index("Upload release candidate artifacts") < text.index("Enforce source health readiness result")
    assert text.index("Build source health readiness") < text.index("Upload release candidate artifacts")


def test_release_candidate_policy_docs_explain_default_enforcement():
    text = Path("docs/release-policy.md").read_text(encoding="utf-8")

    for phrase in [
        "Release candidates default to source-health enforcement.",
        "`report_only` remains available as an explicit diagnostic mode",
        "Confirmed P0 source-health failures block release candidates by default.",
        "Ambiguous access and source quality statuses remain warning-only",
        "Missing, unavailable, or invalid source-health artifacts also block release candidates",
    ]:
        assert phrase in text


def test_release_candidate_workflow_does_not_tag_or_publish():
    text = WORKFLOW.read_text(encoding="utf-8").lower()

    disallowed = [
        "git tag",
        "git push",
        "gh release create",
        "contents: write",
        "pull-requests: write",
    ]
    for phrase in disallowed:
        assert phrase not in text
