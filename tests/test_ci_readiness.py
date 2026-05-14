from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def test_validate_workflow_uses_read_only_permissions_and_expected_triggers():
    workflow = load_workflow("validate.yml")

    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request" in workflow["on"]
    assert workflow["on"]["push"]["branches"] == ["main"]


def test_validate_workflow_checks_generated_pack_and_indexes():
    text = (WORKFLOW_DIR / "validate.yml").read_text(encoding="utf-8")

    assert "python -m tools.openva.validate validate" in text
    assert "python -m tools.openva.validate build-indexes" in text
    assert "git diff --exit-code openva-pack.json indexes/" in text
    assert "pytest -q" in text


def test_catalog_guard_workflow_is_read_only_and_pr_scoped():
    workflow = load_workflow("catalog-pr-guard.yml")

    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "pull_request" in workflow["on"]
    assert workflow["jobs"]["catalog-pr-guard"]["if"] == "startsWith(github.event.pull_request.title, 'Catalog:')"


def test_observation_dry_run_is_manual_only_and_read_only():
    workflow = load_workflow("observe-dry-run.yml")

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"].keys()) == {"workflow_dispatch"}


def test_no_workflow_requests_write_permissions():
    for path in WORKFLOW_DIR.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        permissions = workflow.get("permissions", {})
        for permission, value in permissions.items():
            assert value != "write", f"{path}: {permission} requests write permission"


def test_ci_policy_documents_required_checks_and_branch_protection():
    text = Path("docs/ci-and-branch-protection.md").read_text(encoding="utf-8")

    assert "validate / validate" in text
    assert "catalog-pr-guard / catalog-pr-guard" in text
    assert "require pull requests before merging" in text
    assert "require the `validate / validate` status check" in text
    assert "git diff --exit-code openva-pack.json indexes/" in text


def test_docs_index_links_ci_policy():
    text = Path("docs/index.md").read_text(encoding="utf-8")

    assert "docs/ci-and-branch-protection.md" in text
