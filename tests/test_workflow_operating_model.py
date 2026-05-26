from pathlib import Path

import yaml


WORKFLOW_DIR = Path(".github/workflows")
OPERATING_MODEL = Path("docs/operations/WORKFLOW_OPERATING_MODEL.md")
CONSOLIDATION_AUDIT = Path("docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md")
REVIEWER_DECISION_HANDOFF = Path("docs/operations/REVIEWER_DECISION_HANDOFF.md")

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
    "source-repair-pr-cleanup.yml",
    "source-refinement-queue.yml",
    "source-refinement-scan.yml",
    "validate.yml",
}

CORE_LOOP_HEADINGS = {
    "PR safety loop",
    "Source cleanup loop",
    "Catalog quality loop",
    "Catalog growth loop",
    "Release/site loop",
}

REVIEWER_INBOX_ALLOWED_PATHS = {"source-review-decision-sheet.csv"}
REVIEWER_INBOX_FORBIDDEN_PATHS = {
    "summary.md",
    "source-review-decision-sheet-summary.md",
    "source-health-report.json",
    "source-verification-report.json",
    "source-quality-refinement-queue.json",
    "source-observation-ledger.json",
    "latest-source-health.json",
    "public/source-health-snapshot.json",
    "source-discovery-report.json",
    "source-repair-sweep-report.json",
    "source-repair-batch-plan.json",
    "source-review-triage-plan.json",
    "promotion-plan.json",
    "cleanup-proposal.json",
    "source-verification.csv",
    "source-repair-sweep-human-review.csv",
    "source-repair-sweep-no-replacement.csv",
    "source-review-triage-plan.csv",
    "promotion-plan-actions.csv",
}


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def artifact_upload_steps(workflow_name: str) -> dict[str, set[str]]:
    workflow = load_workflow(workflow_name)
    steps = workflow["jobs"][workflow_name.removesuffix(".yml")]["steps"]
    artifacts: dict[str, set[str]] = {}
    for step in steps:
        if step.get("uses") != "actions/upload-artifact@v6":
            continue
        with_block = step.get("with", {})
        name = with_block.get("name")
        raw_path = with_block.get("path", "")
        paths = {line.strip() for line in str(raw_path).splitlines() if line.strip()}
        artifacts[name] = paths
    return artifacts


def test_public_workflows_are_intentional_and_allowlisted():
    assert {path.name for path in WORKFLOW_DIR.glob("*.yml")} == EXPECTED_PUBLIC_WORKFLOWS


def test_workflow_operating_model_documents_every_core_loop():
    text = OPERATING_MODEL.read_text(encoding="utf-8")

    assert "Lane A: Source debt cleanup" in text
    assert "Lane B: Catalog growth discovery and controlled promotion" in text
    assert "Lane C: Workflow loop refinement" in text
    for heading in CORE_LOOP_HEADINGS:
        assert heading in text

    assert "`source-maintenance-report.yml` is the source cleanup and reporting entry point" in text
    assert "`catalog-growth-discovery.yml` is the catalog expansion proposal entry point" in text
    assert "`candidate-promotion-pr.yml` is the controlled write path for reviewed promotions" in text
    assert "`coverage-audit.yml` is the catalog quality entry point" in text
    assert "They must not become catalog truth generators" in text


def test_workflow_operating_model_lists_every_public_workflow():
    text = OPERATING_MODEL.read_text(encoding="utf-8")

    for workflow_name in EXPECTED_PUBLIC_WORKFLOWS:
        assert f"`{workflow_name}`" in text


def test_workflow_consolidation_audit_classifies_every_public_workflow():
    text = CONSOLIDATION_AUDIT.read_text(encoding="utf-8")

    for workflow_name in EXPECTED_PUBLIC_WORKFLOWS:
        assert f"`{workflow_name}`" in text

    assert "`catalog-maintenance.yml` | `retire_candidate`" in text
    assert "`source-refinement-queue.yml` | `retire_candidate`" in text
    assert "`observe-report.yml` | `retire_candidate`" in text
    assert "Future Action A: reviewed decision validation handoff" in text
    assert "Future Action B: reviewed no-replacement truth-state application" in text
    assert "Future Action C: workflow retirement" in text
    assert "Future Action D: source operations scheduler" in text
    assert "Future Action E: catalog growth gating dashboard" in text


def test_workflow_operating_model_uses_exact_retire_candidate_metadata():
    text = OPERATING_MODEL.read_text(encoding="utf-8")

    assert "Varies by workflow" not in text
    assert "varies by workflow" not in text
    assert "| `catalog-maintenance.yml` | Legacy catalog maintenance report for validation, index rebuild, drift check, tests, and entity stub reporting. | `workflow_dispatch`, scheduled weekly (`17 2 * * 1`) | `contents: read`, `actions: read` | No | No | No | `catalog-maintenance-report` | Operators | Consolidation candidate |" in text
    assert "| `source-refinement-queue.yml` | Legacy source refinement queue generated from an observation report path. | `workflow_dispatch` only | `contents: read` | No | No | No | `openva-source-refinement-queue` | Operators | Consolidation candidate |" in text
    assert "| `observe-report.yml` | Observation report path for full public-source observation dry-run output and review queue export. | `workflow_dispatch`, scheduled weekly (`0 2 * * 1`) | `contents: read` | No | No | No | `openva-observation-report` | Operators | Consolidation candidate |" in text


def test_source_maintenance_report_uploads_reviewer_only_inbox_artifact():
    artifacts = artifact_upload_steps("source-maintenance-report.yml")

    assert "openva-source-maintenance-report" in artifacts
    assert "openva-source-reviewer-inbox" in artifacts
    assert artifacts["openva-source-reviewer-inbox"] == REVIEWER_INBOX_ALLOWED_PATHS


def test_reviewer_only_inbox_contains_no_machine_or_secondary_reviewer_files():
    reviewer_paths = artifact_upload_steps("source-maintenance-report.yml")["openva-source-reviewer-inbox"]

    assert reviewer_paths == {"source-review-decision-sheet.csv"}
    assert not (reviewer_paths & REVIEWER_INBOX_FORBIDDEN_PATHS)
    assert not any(path.endswith(".json") for path in reviewer_paths)
    assert not any(path.endswith(".md") for path in reviewer_paths)
    assert len([path for path in reviewer_paths if path.endswith(".csv")]) == 1


def test_full_source_maintenance_artifact_remains_available_for_operators_and_machines():
    operator_paths = artifact_upload_steps("source-maintenance-report.yml")["openva-source-maintenance-report"]

    assert "source-review-decision-sheet.csv" in operator_paths
    assert "summary.md" in operator_paths
    assert "source-verification-report.json" in operator_paths
    assert "source-verification.csv" in operator_paths
    assert "promotion-plan-actions.csv" in operator_paths


def test_reviewer_decision_handoff_documents_controlled_manual_boundary():
    text = REVIEWER_DECISION_HANDOFF.read_text(encoding="utf-8")

    required_fragments = {
        "openva-source-reviewer-inbox",
        "source-review-decision-sheet.csv",
        "source-review-triage-plan.json",
        "openva-source-maintenance-report",
        "validate-sheet",
        "export-reviewed-artifacts",
        "maintenance/reviewed/",
        "source-repair-pr.yml",
        "untrusted input",
        "does not mutate `data/vendors/**`",
        "Do not apply automerge labels",
        "CI passes",
    }
    for fragment in required_fragments:
        assert fragment in text


def test_reviewer_decision_handoff_requires_matching_original_triage_plan():
    text = REVIEWER_DECISION_HANDOFF.read_text(encoding="utf-8")

    assert "The original `source-review-triage-plan.json` is required for validation" in text
    assert "Do not validate a completed sheet against a different triage plan" in text
    assert "same `source-maintenance-report.yml` run" in text


def test_workflow_operating_model_defines_reviewed_decision_boundary_before_source_repair():
    text = OPERATING_MODEL.read_text(encoding="utf-8")

    assert "## Reviewed decision handoff boundary" in text
    assert "source_review_decisions validate-sheet" in text
    assert "zero invalid rows only" in text
    assert "source_review_decisions export-reviewed-artifacts" in text
    assert "reviewed-artifacts PR under maintenance/reviewed/" in text
    assert "source-repair-pr.yml may be run manually from committed reviewed repair evidence" in text
    assert "must not run from an uncommitted reviewer sheet" in text


def test_consolidation_audit_keeps_future_action_a_manual_without_new_workflow():
    text = CONSOLIDATION_AUDIT.read_text(encoding="utf-8")

    assert "Current status: handoff hardening is documented" in text
    assert "Do not add a scheduled workflow for this path" in text
    assert "Do not automatically mutate catalog records from reviewer sheets" in text
    assert "Do not run `source-repair-pr.yml` from uncommitted reviewer input" in text
    assert "source_review_decisions validate-sheet" in text
    assert "source_review_decisions export-reviewed-artifacts" in text
