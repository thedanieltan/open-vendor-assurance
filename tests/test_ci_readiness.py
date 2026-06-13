from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
EXPECTED_PUBLIC_WORKFLOWS = {
    "candidate-promotion-pr.yml",
    "agent-automerge.yml",
    "agent-weighted-review.yml",
    "bot-chatops.yml",
    "bot-dashboard-issue.yml",
    "catalog-agent-pr.yml",
    "catalog-growth-discovery.yml",
    "catalog-maintenance-pr.yml",
    "catalog-maintenance.yml",
    "catalog-pr-guard.yml",
    "contribution-intake-agent.yml",
    "coverage-audit.yml",
    "observation-ledger-append-pr.yml",
    "observe-report.yml",
    "release-candidate.yml",
    "release-downloads.yml",
    "site-live-feed.yml",
    "site-pages.yml",
    "source-maintenance-report.yml",
    "source-repair-pr.yml",
    "source-repair-pr-cleanup.yml",
    "source-refinement-queue.yml",
    "source-refinement-scan.yml",
    "submitted-source-verification.yml",
    "validate.yml",
}


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_actions_tab_contains_only_purposeful_public_workflows():
    assert {path.name for path in WORKFLOW_DIR.glob("*.yml")} == EXPECTED_PUBLIC_WORKFLOWS


def test_workflows_use_node24_compatible_action_versions():
    stale_actions = ["actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4", "softprops/action-gh-release@v2"]
    for path in WORKFLOW_DIR.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for action in stale_actions:
            assert action not in text, f"{path}: stale Node 20 action reference {action}"


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


def test_release_candidate_builds_report_only_source_health_readiness():
    text = (WORKFLOW_DIR / "release-candidate.yml").read_text(encoding="utf-8")
    workflow = load_workflow("release-candidate.yml")
    triggers = workflow_triggers(workflow)
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert "Download latest source maintenance artifacts" in text
    assert "gh run list" in text
    assert "--workflow source-maintenance-report.yml" in text
    assert "gh run download" in text
    assert "--name openva-source-maintenance-report" in text
    assert "source health artifact unavailable" in text
    assert "Download latest source refinement scan artifacts" in text
    assert "--workflow source-refinement-scan.yml" in text
    assert "--name openva-confirmed-p0-source-refinement-scan" in text
    assert "source-refinement-artifacts/confirmed-p0-repair-candidates.json" in text
    assert "confirmed P0 scan artifact unavailable" in text
    assert "python -m tools.openva.release_source_health check" in text
    assert "--report-only" in text
    assert "--enforce" in text
    # WP35: source health is the producer; the aggregate release gate is the
    # authoritative final enforcer.
    assert "python -m tools.openva.release_gates check" in text
    assert "RELEASE_GATES_EXIT_CODE" in text
    assert "release-source-health-readiness.json" in text
    assert "release-source-health-summary.md" in text
    assert "release-gates.json" in text
    assert triggers["workflow_dispatch"]["inputs"]["source_health_policy"]["default"] == "enforce"


def test_catalog_guard_workflow_is_read_only_and_pr_scoped():
    workflow = load_workflow("catalog-pr-guard.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "catalog-pr-guard.yml").read_text(encoding="utf-8")
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "pull_request" in triggers
    assert workflow["jobs"]["catalog-pr-guard"]["if"] == "startsWith(github.event.pull_request.title, 'Catalog:')"
    assert 'pip install -e "services/openva_match_service[dev]"' in text


def test_observation_report_is_manual_only_read_only_observation_workflow():
    workflow = load_workflow("observe-report.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "observe-report.yml").read_text(encoding="utf-8")
    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch"}
    assert "python -m tools.openva.observe observe-all --dry-run --emit-yaml" in text
    assert "reports/observation-report.md" in text
    assert "reports/observation-report.json" in text
    assert "reports/observation-review-queue.csv" in text
    assert "actions/upload-artifact@v6" in text
    assert "peter-evans/create-pull-request" not in text


def test_bot_chatops_workflow_is_limited_issue_comment_label_mutation():
    workflow = load_workflow("bot-chatops.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "bot-chatops.yml").read_text(encoding="utf-8")
    assert set(triggers.keys()) == {"issue_comment"}
    assert triggers["issue_comment"] == {"types": ["created"]}
    assert workflow["permissions"] == {"contents": "read", "issues": "write", "pull-requests": "read"}
    assert "openva-hold" in text
    assert "addLabels" in text
    assert "removeLabel" in text
    assert "actions/workflows" not in text
    assert "pulls.create" not in text
    assert "git.createRef" not in text


def test_no_workflow_requests_write_permissions_except_approved_handoffs():
    allowed_write_workflows = {
        "catalog-agent-pr.yml": {"triggers": {"workflow_dispatch"}, "permissions": {"contents": "write", "pull-requests": "write"}},
        "catalog-maintenance-pr.yml": {"triggers": {"workflow_dispatch", "schedule"}, "permissions": {"contents": "write", "pull-requests": "write"}},
        "candidate-promotion-pr.yml": {"triggers": {"workflow_dispatch", "schedule"}, "permissions": {"contents": "write", "pull-requests": "write"}},
        "source-repair-pr.yml": {"triggers": {"workflow_dispatch"}, "permissions": {"contents": "write", "pull-requests": "write"}},
        "source-repair-pr-cleanup.yml": {"triggers": {"workflow_dispatch", "schedule"}, "permissions": {"contents": "read", "pull-requests": "write", "issues": "write"}},
        "observation-ledger-append-pr.yml": {"triggers": {"workflow_dispatch", "workflow_run"}, "permissions": {"contents": "write", "pull-requests": "write", "actions": "read"}},
        "catalog-growth-discovery.yml": {"triggers": {"workflow_dispatch", "schedule"}, "permissions": {"contents": "read", "issues": "write"}},
        "contribution-intake-agent.yml": {"triggers": {"issues", "workflow_dispatch"}, "permissions": {"contents": "write", "pull-requests": "write", "issues": "write"}},
        "submitted-source-verification.yml": {"triggers": {"issues", "workflow_dispatch"}, "permissions": {"contents": "read", "issues": "write"}},
        "release-downloads.yml": {"triggers": {"push"}, "permissions": {"contents": "write"}},
        "site-live-feed.yml": {"triggers": {"workflow_dispatch", "schedule"}, "permissions": {"contents": "read", "pages": "write", "id-token": "write"}},
        "site-pages.yml": {"triggers": {"push", "workflow_dispatch"}, "permissions": {"contents": "read", "actions": "read", "pages": "write", "id-token": "write"}},
        "agent-weighted-review.yml": {"triggers": {"pull_request"}, "permissions": {"contents": "read", "pull-requests": "read", "issues": "write"}},
        "bot-dashboard-issue.yml": {"triggers": {"workflow_dispatch", "schedule"}, "permissions": {"contents": "read", "issues": "write"}},
        "bot-chatops.yml": {"triggers": {"issue_comment"}, "permissions": {"contents": "read", "issues": "write", "pull-requests": "read"}},
        "agent-automerge.yml": {"triggers": {"pull_request"}, "permissions": {"contents": "write", "pull-requests": "write", "checks": "read", "statuses": "read"}},
    }
    for path in WORKFLOW_DIR.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        permissions = workflow.get("permissions", {})
        triggers = workflow_triggers(workflow)
        write_permissions = {permission: value for permission, value in permissions.items() if value == "write"}
        if not write_permissions:
            continue
        assert path.name in allowed_write_workflows, f"{path}: unexpected write permissions"
        allowed = allowed_write_workflows[path.name]
        assert set(triggers.keys()) == allowed["triggers"], f"{path}: unexpected write workflow triggers"
        assert permissions == allowed["permissions"], f"{path}: unexpected write workflow permissions"
        if path.name == "bot-chatops.yml":
            assert "contents" in permissions and permissions["contents"] == "read"
            assert "pull-requests" in permissions and permissions["pull-requests"] == "read"
            assert permissions["issues"] == "write"


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


def test_source_repair_pr_workflow_is_manual_human_reviewed_only():
    workflow = load_workflow("source-repair-pr.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "source-repair-pr.yml").read_text(encoding="utf-8")
    assert set(triggers.keys()) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert "validation_report_path must be under maintenance/reviewed/" in text
    assert "evidence_report_path must be under maintenance/reviewed/" in text
    assert "pr_branch must start with agent-" in text
    assert "pr_title must start with Catalog: repair" in text
    assert "python -m tools.openva.source_repair_actions apply" in text
    assert "gh pr create" in text
    assert "gh pr merge" not in text


def test_source_refinement_scan_runs_weekly_and_selects_latest_maintenance_runs():
    workflow = load_workflow("source-refinement-scan.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "source-refinement-scan.yml").read_text(encoding="utf-8")
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert triggers["schedule"][0]["cron"] == "0 8 * * 3"
    assert "gh run list" in text
    assert "--workflow source-maintenance-report.yml" in text
    assert "python -m tools.openva.github_actions_artifacts select-latest-source-maintenance-runs" in text
    assert "insufficient source maintenance history" in text
