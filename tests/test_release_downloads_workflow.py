from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_formal_github_release_publisher_is_retired():
    assert not (WORKFLOW_DIR / "release-downloads.yml").exists()


def test_no_workflow_publishes_github_release_assets():
    for path in WORKFLOW_DIR.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "softprops/action-gh-release" not in text, path
        assert "gh release create" not in text, path


def test_site_pages_is_the_catalog_publication_lane():
    workflow = load_workflow("site-pages.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "site-pages.yml").read_text(encoding="utf-8")

    assert triggers["push"]["branches"] == ["main"]
    assert "python -m tools.openva.validate build-indexes" in text
    assert "actions/deploy-pages" in text
