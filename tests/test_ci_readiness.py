from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
EXPECTED_PUBLIC_WORKFLOWS = {
    "candidate-promotion-pr.yml",
    "agent-automerge.yml",
    "agent-weighted-review.yml",
    "catalog-agent-pr.yml",
    "catalog-growth-discovery.yml",
    "catalog-maintenance-pr.yml",
    "catalog-maintenance.yml",
    "catalog-pr-guard.yml",
    "contribution-intake-agent.yml",
    "coverage-audit.yml",
    "observe-report.yml",
    "release-candidate.yml",
    "release-downloads.yml",
    "site-live-feed.yml",
    "site-pages.yml",
    "source-maintenance-report.yml",
    "source-repair-pr.yml",
    "source-refinement-queue.yml",
    "source-refinement-scan.yml",
    "validate.yml",
}


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    # PyYAML uses YAML 1.1 boolean parsing, where the plain scalar key `on`
    # is parsed as True. GitHub Actions treats it as the trigger key.
    return workflow.get("on") or workflow.get(True) or {}


def test_actions_tab_contains_only_purposeful_public_workflows():
    assert {path.name for path in WORKFLOW_DIR.glob("*.yml")} == EXPECTED_PUBLIC_WORKFLOWS


def test_workflows_use_node24_compatible_action_versions():
    stale_actions = [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
        "softprops/action-gh-release@v2",
    ]
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

    assert "python -m tools.openva.release_source_health check" in text
    assert "--report-only" in text
    assert "--enforce" in text
    assert "SOURCE_HEALTH_EXIT_CODE" in text
    assert "release-source-health-readiness.json" in text
    assert "release-source-health-summary.md" in text
    assert triggers["workflow_dispatch"]["inputs"]["source_health_policy"]["default"] == "report_only"


def test_catalog_guard_workflow_is_read_only_and_pr_scoped():
    workflow = load_workflow("catalog-pr-guard.yml")
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "pull_request" in triggers
    assert workflow["jobs"]["catalog-pr-guard"]["if"] == "startsWith(github.event.pull_request.title, 'Catalog:')"


def test_observation_report_is_single_read_only_observation_workflow():
    workflow = load_workflow("observe-report.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "observe-report.yml").read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert "python -m tools.openva.observe observe-all --dry-run --emit-yaml" in text
    assert "reports/observation-report.md" in text
    assert "reports/observation-report.json" in text
    assert "reports/observation-review-queue.csv" in text
    assert "actions/upload-artifact@v6" in text
    assert "peter-evans/create-pull-request" not in text


def test_no_workflow_requests_write_permissions_except_approved_handoffs():
    allowed_write_workflows = {
        "catalog-agent-pr.yml": {
            "triggers": {"workflow_dispatch"},
            "permissions": {"contents": "write", "pull-requests": "write"},
        },
        "catalog-maintenance-pr.yml": {
            "triggers": {"workflow_dispatch", "schedule"},
            "permissions": {"contents": "write", "pull-requests": "write"},
        },
        "candidate-promotion-pr.yml": {
            "triggers": {"workflow_dispatch", "schedule"},
            "permissions": {"contents": "write", "pull-requests": "write"},
        },
        "source-repair-pr.yml": {
            "triggers": {"workflow_dispatch"},
            "permissions": {"contents": "write", "pull-requests": "write"},
        },
        "catalog-growth-discovery.yml": {
            "triggers": {"workflow_dispatch", "schedule"},
            "permissions": {"contents": "read", "issues": "write"},
        },
        "contribution-intake-agent.yml": {
            "triggers": {"issues", "workflow_dispatch"},
            "permissions": {"contents": "write", "pull-requests": "write", "issues": "write"},
        },
        "release-downloads.yml": {
            "triggers": {"push"},
            "permissions": {"contents": "write"},
        },
        "site-live-feed.yml": {
            "triggers": {"workflow_dispatch", "schedule"},
            "permissions": {"contents": "read", "pages": "write", "id-token": "write"},
        },
        "site-pages.yml": {
            "triggers": {"push", "workflow_dispatch"},
            "permissions": {"contents": "read", "pages": "write", "id-token": "write"},
        },
        "agent-weighted-review.yml": {
            "triggers": {"pull_request"},
            "permissions": {"contents": "read", "pull-requests": "read", "issues": "write"},
        },
        "agent-automerge.yml": {
            "triggers": {"pull_request"},
            "permissions": {
                "contents": "write",
                "pull-requests": "write",
                "checks": "read",
                "statuses": "read",
            },
        },
    }

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
        allowed = allowed_write_workflows[path.name]
        assert set(triggers.keys()) == allowed["triggers"], f"{path}: unexpected write workflow triggers"
        assert permissions == allowed["permissions"], f"{path}: unexpected write workflow permissions"
        if path.name == "release-downloads.yml":
            assert triggers["push"] == {"tags": ["v*"]}, f"{path}: release downloads must be tag-only"
        if path.name == "site-pages.yml":
            assert triggers["push"] == {"branches": ["main"]}, f"{path}: site pages must deploy from main"
            assert "workflow_dispatch" in triggers, f"{path}: site pages must support manual deploy"
        if path.name == "site-live-feed.yml":
            assert triggers["schedule"][0]["cron"] == "0 3 * * 0", f"{path}: live feed cron must stay weekly Sunday 03:00 UTC"


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


def test_agent_automerge_has_strict_p0_source_repair_lane():
    workflow = load_workflow("agent-automerge.yml")
    text = (WORKFLOW_DIR / "agent-automerge.yml").read_text(encoding="utf-8")

    assert "p0-source-repair" in workflow["jobs"]
    assert "source-refinement" in workflow["jobs"]["p0-source-repair"]["if"]
    assert "automerge:p0-source-repair" in workflow["jobs"]["p0-source-repair"]["if"]
    assert "python -m tools.openva.source_repair_automerge extract-inputs" in text
    assert "python -m tools.openva.source_repair_automerge check" in text
    assert "--evidence-report \"$EVIDENCE_REPORT_PATH\"" in text
    assert "git diff --exit-code openva-pack.json indexes/ dist/" in text


def test_agent_weighted_review_is_advisory_and_adapter_aware():
    workflow = load_workflow("agent-weighted-review.yml")
    triggers = workflow_triggers(workflow)
    text = (WORKFLOW_DIR / "agent-weighted-review.yml").read_text(encoding="utf-8")
    automation_text = Path("tools/openva/automation_rules.py").read_text(encoding="utf-8")

    assert set(triggers.keys()) == {"pull_request"}
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read", "issues": "write"}
    assert "schema-conformance-agent" in workflow["jobs"]
    assert "source-accessibility-agent" in workflow["jobs"]
    assert "advisory-wording-agent" in workflow["jobs"]
    assert "provenance-completeness-agent" in workflow["jobs"]
    assert "python -m tools.openva.automation_rules schema-conformance" in text
    assert "validate_adapter_record" in automation_text
    assert "This workflow is advisory only. It does not merge, close, or mutate catalog files." in text
    assert "gh pr merge" not in text


def test_catalog_reset_workflow_has_been_removed_after_one_time_reset():
    assert not (WORKFLOW_DIR / "catalog-reset-pr.yml").exists()


def test_superseded_narrow_report_workflows_are_removed():
    removed = {
        "catalog-intake-handoff.yml",
        "cleanup-proposal-issue.yml",
        "cleanup-proposal-report.yml",
        "observe-dry-run.yml",
        "promotion-plan-report.yml",
        "source-discovery-report.yml",
        "source-health-report.yml",
        "source-verification-report.yml",
    }

    for name in removed:
        assert not (WORKFLOW_DIR / name).exists()


def test_report_workflows_upload_reviewer_friendly_artifacts():
    expected_paths = {
        "catalog-growth-discovery.yml": {
            "reports/catalog-growth-discovery-summary.md",
            "vendor-candidate-discovery-report.json",
            "reports/vendor-candidates.csv",
            "reports/source-discovery-candidates.csv",
            "reports/promotion-plan-actions.csv",
        },
        "coverage-audit.yml": {
            "reports/coverage-audit-summary.md",
            "reports/coverage-audit-report.json",
            "reports/coverage-audit-vendors.csv",
        },
        "observe-report.yml": {
            "reports/observation-report.md",
            "reports/observation-report.json",
            "reports/observation-review-queue.csv",
        },
        "source-maintenance-report.yml": {
            "summary.md",
            "source-health-report.json",
            "source-verification-report.json",
            "source-quality-refinement-queue.json",
            "source-quality-refinement-queue.csv",
            "source-quality-refinement-summary.md",
            "source-observation-ledger.json",
            "source-observation-ledger-summary.md",
            "latest-source-health.json",
            "public/source-health-snapshot.json",
            "source-discovery-report.json",
            "promotion-plan.json",
            "cleanup-proposal.json",
            "source-health.csv",
            "source-verification.csv",
            "source-discovery-candidates.csv",
            "promotion-plan-actions.csv",
        },
        "source-refinement-queue.yml": {
            "reports/source-refinement-queue.md",
            "reports/source-refinement-queue.json",
            "reports/source-refinement-queue.csv",
        },
        "source-refinement-scan.yml": {
            "confirmed-p0-repair-candidates.json",
            "confirmed-p0-summary.md",
            "source-repair-evidence.json",
            "source-repair-plan-validation.json",
        },
        "source-repair-pr.yml": {
            "source-repair-action-report.json",
            "source-repair-pr-body.md",
        },
        "release-candidate.yml": {
            "release-artifacts.json",
            "release-source-health-readiness.json",
            "release-source-health-summary.md",
        },
    }

    for workflow_name, paths in expected_paths.items():
        text = (WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")
        assert "actions/upload-artifact@v6" in text
        for path in paths:
            assert path in text


def test_source_maintenance_report_uploads_observation_ledger_artifact_only():
    text = (WORKFLOW_DIR / "source-maintenance-report.yml").read_text(encoding="utf-8")

    assert "python -m tools.openva.source_observation_ledger build" in text
    assert "--source-verification-report source-verification-report.json" in text
    assert '--run-id "${{ github.run_id }}"' in text
    assert "--output source-observation-ledger.json" in text
    assert "--summary-md source-observation-ledger-summary.md" in text
    assert "source-observation-ledger.json" in text
    assert "source-observation-ledger-summary.md" in text
    assert "observations/sources/" not in text


def test_source_maintenance_report_uploads_quality_refinement_queue_artifact_only():
    text = (WORKFLOW_DIR / "source-maintenance-report.yml").read_text(encoding="utf-8")

    assert "python -m tools.openva.source_quality_refinement build" in text
    assert "--source-verification-report source-verification-report.json" in text
    assert "--json-output source-quality-refinement-queue.json" in text
    assert "--csv-output source-quality-refinement-queue.csv" in text
    assert "--markdown-output source-quality-refinement-summary.md" in text
    assert "source-quality-refinement-queue.json" in text
    assert "source-quality-refinement-queue.csv" in text
    assert "source-quality-refinement-summary.md" in text
    assert "gh pr create" not in text
    assert "gh pr merge" not in text
    assert "agent-automerge" not in text


def test_source_maintenance_report_uploads_latest_health_index_artifact_only():
    text = (WORKFLOW_DIR / "source-maintenance-report.yml").read_text(encoding="utf-8")

    assert "python -m tools.openva.source_latest_health build" in text
    assert "--source-observation-ledger source-observation-ledger.json" in text
    assert "--output latest-source-health.json" in text
    assert "latest-source-health.json" in text
    assert "site_ui_generated" not in text
    assert "observations/sources/" not in text


def test_source_maintenance_report_uploads_public_health_snapshot_artifact_only():
    text = (WORKFLOW_DIR / "source-maintenance-report.yml").read_text(encoding="utf-8")

    assert "python -m tools.openva.source_health_public_snapshot build" in text
    assert "--latest-source-health latest-source-health.json" in text
    assert "--output public/source-health-snapshot.json" in text
    assert "public/source-health-snapshot.json" in text
    assert "gh pr create" not in text
    assert "gh pr merge" not in text
    assert "actions/deploy-pages" not in text
    assert "observations/sources/" not in text


def test_ci_policy_documents_required_checks_and_branch_protection():
    text = Path("docs/ci-and-branch-protection.md").read_text(encoding="utf-8")

    assert "validate / validate" in text
    assert "catalog-pr-guard / catalog-pr-guard" in text
    assert "source-maintenance-report / source-maintenance-report" in text
