from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    # PyYAML uses YAML 1.1 boolean parsing, where the plain scalar key `on`
    # is parsed as True. GitHub Actions treats it as the trigger key.
    return workflow.get("on") or workflow.get(True) or {}


def test_validate_workflow_uses_read_only_permissions_and_expected_triggers():
    workflow = load_workflow("validate.yml")
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]


def test_validate_workflow_checks_generated_pack_and_indexes():
    text = (WORKFLOW_DIR / "validate.yml").read_text(encoding="utf-8")

    assert "python -m tools.openva.validate validate" in text
    assert "python -m tools.openva.validate build-indexes" in text
    assert "git diff --exit-code openva-pack.json indexes/" in text
    assert "pytest -q" in text


def test_catalog_guard_workflow_is_read_only_and_pr_scoped():
    workflow = load_workflow("catalog-pr-guard.yml")
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "pull_request" in triggers
    assert workflow["jobs"]["catalog-pr-guard"]["if"] == "startsWith(github.event.pull_request.title, 'Catalog:')"


def test_observation_dry_run_is_manual_only_and_read_only():
    workflow = load_workflow("observe-dry-run.yml")
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch"}


def test_source_health_report_is_read_only_scheduled_inventory():
    workflow = load_workflow("source-health-report.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "source-health-report.yml").read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert "python -m tools.openva.source_health build --output source-health-report.json" in text
    assert "actions/upload-artifact@v4" in text
    assert "peter-evans/create-pull-request" not in text


def test_no_workflow_requests_write_permissions_except_manual_pr_creator():
    allowed_write_workflows = {"catalog-agent-pr.yml"}

    for path in WORKFLOW_DIR.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        permissions = workflow.get("permissions", {})
        triggers = workflow_triggers(workflow)
        write_permissions = {
            permission: value for permission, value in permissions.items() if value == "write"
        }

        if not write_permissions:
            continue

        assert path.name in allowed_write_workflows, f"{path}: unexpected write permissions"
        assert set(triggers.keys()) == {"workflow_dispatch"}, f"{path}: write workflow must be manual-only"
        assert write_permissions == {
            "contents": "write",
            "pull-requests": "write",
        }, f"{path}: write permissions must be limited to PR creation"


def test_catalog_agent_pr_workflow_is_manual_pr_only():
    workflow = load_workflow("catalog-agent-pr.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "catalog-agent-pr.yml").read_text(encoding="utf-8")

    assert set(triggers.keys()) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert "peter-evans/create-pull-request" in text
    assert "branch_name must start with agent-" in text
    assert "pr_title must start with Catalog:" in text
    assert "This workflow creates a pull request only. It does not merge catalog changes." in text


def test_ci_policy_documents_required_checks_and_branch_protection():
    text = Path("docs/ci-and-branch-protection.md").read_text(encoding="utf-8")

    assert "validate / validate" in text
    assert "catalog-pr-guard / catalog-pr-guard" in text
    assert "source-health-report / source-health-report" in text
    assert "require pull requests before merging" in text
    assert "require the `validate / validate` status check" in text
    assert "git diff --exit-code openva-pack.json indexes/" in text
    assert "The report is an inventory and metadata-quality report only" in text


def test_docs_index_links_ci_policy():
    text = Path("docs/index.md").read_text(encoding="utf-8")

    assert "docs/ci-and-branch-protection.md" in text
