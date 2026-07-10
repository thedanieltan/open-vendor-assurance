from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_formal_release_candidate_workflow_is_retired():
    assert not (WORKFLOW_DIR / "release-candidate.yml").exists()


def test_continuous_publication_replaces_release_candidate_lane():
    workflow = load_workflow("site-pages.yml")
    triggers = workflow_triggers(workflow)

    assert triggers["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pages": "write",
        "id-token": "write",
    }
