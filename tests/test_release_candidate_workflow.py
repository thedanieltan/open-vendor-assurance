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

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch"}


def test_release_candidate_workflow_wraps_existing_release_commands():
    text = WORKFLOW.read_text(encoding="utf-8")

    expected_commands = [
        "python -m tools.openva.validate validate",
        "pytest -q",
        "python -m tools.openva.release_smoke",
        "python -m tools.openva.release_artifacts build",
        "python -m tools.openva.release_artifacts check",
    ]
    for command in expected_commands:
        assert command in text


def test_release_candidate_workflow_uploads_manifest_only():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v4" in text
    assert "name: openva-release-candidate-artifacts" in text
    assert "path: release-artifacts.json" in text


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
