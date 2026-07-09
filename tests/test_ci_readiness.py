from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
EXPECTED_PUBLIC_WORKFLOWS = {
    "autonomous-catalog-growth.yml",
    "candidate-intake-pr.yml",
    "candidate-promotion-pr.yml",
    "agent-automerge.yml",
    "agent-weighted-review.yml",
    "bot-chatops.yml",
    "bot-dashboard-issue.yml",
    "catalog-agent-pr.yml",
    "catalog-growth-discovery.yml",
    "catalog-growth-promotion-bridge.yml",
    "discovery-ledger-append-pr.yml",
    "machine-provisional-materialization.yml",
    "catalog-maintenance-pr.yml",
    "catalog-maintenance.yml",
    "catalog-pr-guard.yml",
    "contribution-intake-agent.yml",
    "coverage-audit.yml",
    "observation-ledger-append-pr.yml",
    "observe-report.yml",
    "release-candidate.yml",
    "release-image.yml",
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
    "validate-pr-metadata.yml",
    "web-bot-auth-smoke.yml",
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


def test_validate_pull_request_types_cover_code_change_events():
    """validate.yml's pull_request trigger lists explicit code-change event types. PR-body
    `Work-Package:` re-validation is delegated to validate-pr-metadata.yml (asserted in
    test_pr_metadata_workflow_reruns_scope_guard_on_pr_body_edit), so the heavy validation
    matrix need not rerun on every metadata edit — and an edit cannot mask a prior failing
    validate check, because validate.yml's jobs are not skipped on `edited`."""
    workflow = load_workflow("validate.yml")
    triggers = workflow_triggers(workflow)
    pull_request_types = set(triggers["pull_request"]["types"])
    assert "ready_for_review" in pull_request_types
    assert {"opened", "synchronize", "reopened"} <= pull_request_types


def test_pr_metadata_workflow_reruns_scope_guard_on_pr_body_edit():
    """Stale-green prevention after `edited` is delegated off validate.yml. The dedicated
    validate-pr-metadata.yml workflow runs ONLY on `edited` and runs ONLY the pr-scope-guard
    job, which reads the current PR body. A PR that changes its `Work-Package:` line after a
    green run therefore still reruns the guard against the new declaration and cannot keep a
    stale-green scope-guard result — at one short job instead of the whole matrix."""
    workflow = load_workflow("validate-pr-metadata.yml")
    triggers = workflow_triggers(workflow)
    assert set(triggers.keys()) == {"pull_request"}
    assert triggers["pull_request"]["types"] == ["edited"]
    assert set(workflow["jobs"]) == {"pr-scope-guard"}
    run_text = "\n".join(
        str(step.get("run", "")) for step in workflow["jobs"]["pr-scope-guard"]["steps"]
    )
    assert "python -m tools.openva.pr_scope_guard" in run_text
    assert 'git worktree add /tmp/base-guard "$BASE_SHA"' in run_text
    assert workflow["permissions"] == {"contents": "read"}


def test_validate_push_trigger_on_main_is_preserved_with_explicit_pr_types():
    """Adding explicit pull_request `types` must not disturb push validation on main."""
    workflow = load_workflow("validate.yml")
    triggers = workflow_triggers(workflow)
    assert triggers["push"]["branches"] == ["main"]
    assert set(triggers.keys()) == {"pull_request", "push"}


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
