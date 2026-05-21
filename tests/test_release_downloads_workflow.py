from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/release-downloads.yml")


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_release_downloads_workflow_runs_only_on_version_tags():
    workflow = load_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers.keys()) == {"push"}
    assert triggers["push"] == {"tags": ["v*"]}
    assert "branches" not in triggers["push"]


def test_release_downloads_workflow_documents_write_permission_exception():
    workflow = load_workflow()
    text = WORKFLOW.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "write"}
    assert "only release asset publishing lane" in text
    assert "attach generated non-technical download assets" in text


def test_release_downloads_workflow_builds_and_uploads_expected_assets():
    text = WORKFLOW.read_text(encoding="utf-8")

    expected = [
        "python -m tools.openva.validate validate",
        'pip install -e "services/openva_match_service[dev]"',
        "pytest -q",
        "python -m tools.openva.validate build-indexes",
        "git diff --exit-code openva-pack.json indexes/ dist/",
        "python -m tools.openva.release_downloads build --out release-downloads",
        "python -m tools.openva.release_downloads manifest --out release-downloads",
        "softprops/action-gh-release@v3",
        "release-artifacts.json",
        "release-downloads/openva-csv.zip",
        "release-downloads/openva-sample-inventory.csv",
        "release-downloads/openva-inventory-template.csv",
        "release-downloads/openva-release-downloads-manifest.json",
    ]
    for item in expected:
        assert item in text
