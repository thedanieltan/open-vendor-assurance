from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
OPERATING_MODEL = Path("docs/operations/WORKFLOW_OPERATING_MODEL.md")
CONSOLIDATION_AUDIT = Path("docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md")
DISCOVERY_MESH_MODEL = Path("docs/operations/DISCOVERY_MESH_OPERATING_MODEL.md")
REVIEWER_DECISION_HANDOFF = Path("docs/operations/REVIEWER_DECISION_HANDOFF.md")

EXPECTED_PUBLIC_WORKFLOWS = {
    "candidate-promotion-pr.yml",
    "agent-automerge.yml",
    "agent-weighted-review.yml",
    "bot-chatops.yml",
    "bot-dashboard-issue.yml",
    "catalog-agent-pr.yml",
    "catalog-growth-discovery.yml",
    "discovery-mesh.yml",
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


def artifact_upload_steps(workflow_name: str) -> dict[str, set[str]]:
    workflow = load_workflow(workflow_name)
    steps = workflow["jobs"][workflow_name.removesuffix(".yml")]["steps"]
    artifacts: dict[str, set[str]] = {}
    for step in steps:
        if step.get("uses") != "actions/upload-artifact@v6":
            continue
        name = step.get("with", {}).get("name")
        raw_path = step.get("with", {}).get("path", "")
        artifacts[name] = {line.strip() for line in str(raw_path).splitlines() if line.strip()}
    return artifacts


def operating_model_text() -> str:
    return OPERATING_MODEL.read_text(encoding="utf-8") + "\n" + DISCOVERY_MESH_MODEL.read_text(encoding="utf-8")


def consolidation_audit_text() -> str:
    return CONSOLIDATION_AUDIT.read_text(encoding="utf-8") + "\n" + DISCOVERY_MESH_MODEL.read_text(encoding="utf-8")


def test_public_workflows_are_intentional_and_allowlisted():
    assert {path.name for path in WORKFLOW_DIR.glob("*.yml")} == EXPECTED_PUBLIC_WORKFLOWS


def test_workflow_operating_model_documents_core_loops_and_public_workflows():
    text = operating_model_text()

    for fragment in {
        "Lane A: Source debt cleanup",
        "Lane B: Catalog growth discovery and controlled promotion",
        "Lane C: Workflow loop refinement",
        "PR safety loop",
        "Source cleanup loop",
        "Catalog quality loop",
        "Catalog growth loop",
        "Release/site loop",
        "Bot operations visibility loop",
        "They must not become catalog truth generators",
    }:
        assert fragment in text

    for workflow_name in EXPECTED_PUBLIC_WORKFLOWS:
        assert f"`{workflow_name}`" in text


def test_workflow_consolidation_audit_classifies_current_legacy_posture():
    text = consolidation_audit_text()

    for workflow_name in EXPECTED_PUBLIC_WORKFLOWS:
        assert f"`{workflow_name}`" in text

    assert "`catalog-maintenance.yml` | `retire_candidate`" in text
    assert "`source-refinement-queue.yml` | `retire_candidate`" in text
    assert "`observe-report.yml` | `quarantined`" in text
    assert "`bot-chatops.yml` | `keep_core`" in text
    assert "Current result: no workflow is classified as `remove_now_if_safe` in this package." in text


def test_workflow_operating_model_uses_exact_legacy_workflow_metadata():
    text = OPERATING_MODEL.read_text(encoding="utf-8")

    assert "Varies by workflow" not in text
    assert "varies by workflow" not in text
    assert "| `catalog-maintenance.yml` | Legacy catalog maintenance report for validation, index rebuild, drift check, tests, and entity stub reporting. | `workflow_dispatch`, scheduled weekly (`17 2 * * 1`) | `contents: read`, `actions: read` | No | No | No | `catalog-maintenance-report` | Operators | Consolidation candidate |" in text
    assert "| `source-refinement-queue.yml` | Quarantined legacy source refinement queue generated from an observation report path. | `workflow_dispatch` only | `contents: read` | No | No | No | `openva-source-refinement-queue` | Legacy operators; replacement owner is `source-refinement-scan.yml` plus `source-maintenance-report.yml` | Quarantined |" in text
    assert "| `observe-report.yml` | Quarantined legacy observation report path for full public-source observation dry-run output and review queue export. | `workflow_dispatch` only | `contents: read` | No | No | No | `openva-observation-report` | Legacy operators; replacement owner is `source-maintenance-report.yml`, `catalog-growth-discovery.yml`, and bot dashboard reports | Quarantined |" in text


def test_observe_report_workflow_is_manual_only_after_wp26():
    workflow = load_workflow("observe-report.yml")
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}


def test_source_maintenance_report_uploads_reviewer_only_inbox_artifact():
    artifacts = artifact_upload_steps("source-maintenance-report.yml")

    assert "openva-source-maintenance-report" in artifacts
    assert artifacts["openva-source-reviewer-inbox"] == {"source-review-decision-sheet.csv"}
    assert "summary.md" in artifacts["openva-source-maintenance-report"]
    assert "source-verification-report.json" in artifacts["openva-source-maintenance-report"]
    assert "promotion-plan-actions.csv" in artifacts["openva-source-maintenance-report"]


def test_reviewer_decision_handoff_documents_controlled_manual_boundary():
    text = REVIEWER_DECISION_HANDOFF.read_text(encoding="utf-8")

    for fragment in {
        "openva-source-reviewer-inbox",
        "source-review-decision-sheet.csv",
        "source-review-triage-plan.json",
        "openva-source-maintenance-report",
        "validate-sheet",
        "export-reviewed-artifacts",
        "maintenance/reviewed/",
        "source-repair-pr.yml",
        "CI passes",
        "The original `source-review-triage-plan.json` is required for validation",
        "Do not validate a completed sheet against a different triage plan",
    }:
        assert fragment in text


def _pr_scope_guard_job() -> dict:
    workflow = load_workflow("validate.yml")
    assert "pr-scope-guard" in workflow["jobs"], "pr-scope-guard job must exist on validate.yml"
    return workflow["jobs"]["pr-scope-guard"]


def _pr_scope_guard_run_text() -> str:
    return "\n".join(str(step.get("run", "")) for step in _pr_scope_guard_job()["steps"])


def test_pr_scope_guard_job_is_pull_request_only():
    """The scope guard must only run on pull_request events; it reads PR-event payload
    (base/head SHAs and PR body) that does not exist on push."""
    assert _pr_scope_guard_job()["if"] == "github.event_name == 'pull_request'"


def test_pr_scope_guard_derives_shas_and_body_from_pull_request_event():
    """BASE_SHA/HEAD_SHA/PR_BODY must come from the pull_request event payload, so the
    guard evaluates the exact base->head diff and the current PR-body declaration."""
    env_blobs = []
    for step in _pr_scope_guard_job()["steps"]:
        env = step.get("env")
        if env:
            env_blobs.append({key: str(value) for key, value in env.items()})
    flattened = {key: value for blob in env_blobs for key, value in blob.items()}
    assert "github.event.pull_request.base.sha" in flattened.get("BASE_SHA", "")
    assert "github.event.pull_request.head.sha" in flattened.get("HEAD_SHA", "")
    assert "github.event.pull_request.body" in flattened.get("PR_BODY", "")


def test_pr_scope_guard_runs_from_trusted_base_worktree_not_head():
    """Trusted-base evaluation: the guard must add a worktree at the BASE SHA and run the
    guard module FROM that base copy, so a PR cannot weaken the policy that judges it. It
    must NOT evaluate the guard from the head revision."""
    run_text = _pr_scope_guard_run_text()
    assert 'git worktree add /tmp/base-guard "$BASE_SHA"' in run_text
    assert "cd /tmp/base-guard" in run_text
    assert "python -m tools.openva.pr_scope_guard" in run_text
    assert "--declaration-file" in run_text
    assert "--changed-paths-file" in run_text
    assert 'git diff --name-only "$BASE_SHA" "$HEAD_SHA"' in run_text


def test_pr_scope_guard_contains_self_bootstrap_skip_branch():
    """The job must skip (exit 0) when the BASE revision lacks the guard module, so the
    guard can be introduced without failing its own introducing PR. NOTE: this means the
    introducing PR's pr-scope-guard success may be bootstrap-only (skipped) and is NOT
    proof the diff passed the future policy — that policy applies only to later PRs whose
    base already contains the guard."""
    run_text = _pr_scope_guard_run_text()
    assert "/tmp/base-guard/tools/openva/pr_scope_guard.py" in run_text
    assert "self-bootstrap" in run_text
    assert "exit 0" in run_text
