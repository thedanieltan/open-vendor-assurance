from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
OPERATING_MODEL = Path("docs/operations/WORKFLOW_OPERATING_MODEL.md")
CONSOLIDATION_AUDIT = Path("docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md")
DISCOVERY_MESH_MODEL = Path("docs/operations/DISCOVERY_MESH_OPERATING_MODEL.md")
DISCOVERY_MESH_INTAKE_RECOVERY = Path("docs/operations/DISCOVERY_MESH_INTAKE_RECOVERY.md")
REVIEWER_DECISION_HANDOFF = Path("docs/operations/REVIEWER_DECISION_HANDOFF.md")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")

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
    "rendered-discovery-acceptance-controller.yml",
    "discovery-ledger-append-pr.yml",
    "discovery-mesh.yml",
    "discovery-mesh-intake-recovery.yml",
    "machine-provisional-materialization.yml",
    "catalog-maintenance-pr.yml",
    "catalog-maintenance.yml",
    "catalog-pr-guard.yml",
    "contribution-intake-agent.yml",
    "coverage-audit.yml",
    "observation-ledger-append-pr.yml",
    "observe-report.yml",
    "release-image.yml",
    "site-live-feed.yml",
    "site-pages.yml",
    "source-maintenance-report.yml",
    "source-repair-pr.yml",
    "source-repair-pr-cleanup.yml",
    "source-refinement-queue.yml",
    "source-refinement-scan.yml",
    "submitted-source-verification.yml",
    "validate-pr-metadata.yml",
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
        artifacts[name] = {
            line.strip() for line in str(raw_path).splitlines() if line.strip()
        }
    return artifacts


def operating_model_text() -> str:
    return (
        OPERATING_MODEL.read_text(encoding="utf-8")
        + "\n"
        + DISCOVERY_MESH_MODEL.read_text(encoding="utf-8")
        + "\n"
        + DISCOVERY_MESH_INTAKE_RECOVERY.read_text(encoding="utf-8")
    )


def consolidation_audit_text() -> str:
    return (
        CONSOLIDATION_AUDIT.read_text(encoding="utf-8")
        + "\n"
        + DISCOVERY_MESH_MODEL.read_text(encoding="utf-8")
        + "\n"
        + DISCOVERY_MESH_INTAKE_RECOVERY.read_text(encoding="utf-8")
    )


def inventory_workflow_names() -> set[str]:
    contract = yaml.safe_load(WORKFLOW_INVENTORY.read_text(encoding="utf-8"))
    return {entry["name"] for entry in contract["public_workflows"]}


def test_public_workflows_are_intentional_and_allowlisted():
    actual = {path.name for path in WORKFLOW_DIR.glob("*.yml")}
    assert actual == EXPECTED_PUBLIC_WORKFLOWS
    assert inventory_workflow_names() == actual
    assert "release-candidate.yml" not in actual
    assert "release-downloads.yml" not in actual


def test_workflow_operating_model_documents_core_loops():
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
        "Discovery Mesh intake recovery",
        "The recovery workflow is the sole post-aggregate intake transaction owner",
    }:
        assert fragment in text

    for workflow_name in {
        "validate.yml",
        "agent-automerge.yml",
        "source-maintenance-report.yml",
        "discovery-mesh.yml",
        "discovery-mesh-intake-recovery.yml",
        "candidate-promotion-pr.yml",
        "site-pages.yml",
    }:
        assert f"`{workflow_name}`" in text


def test_workflow_consolidation_audit_classifies_current_legacy_posture():
    text = consolidation_audit_text()

    for workflow_name in {
        "catalog-maintenance.yml",
        "source-refinement-queue.yml",
        "observe-report.yml",
        "bot-chatops.yml",
    }:
        assert f"`{workflow_name}`" in text

    assert "`catalog-maintenance.yml` | `retire_candidate`" in text
    assert "`source-refinement-queue.yml` | `retire_candidate`" in text
    assert "`observe-report.yml` | `quarantined`" in text
    assert "`bot-chatops.yml` | `keep_core`" in text
    assert (
        "Current result: no workflow is classified as `remove_now_if_safe` "
        "in this package."
    ) in text


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
    assert artifacts["openva-source-reviewer-inbox"] == {
        "source-review-decision-sheet.csv"
    }
    assert "summary.md" in artifacts["openva-source-maintenance-report"]
    assert "source-verification-report.json" in artifacts[
        "openva-source-maintenance-report"
    ]
    assert "promotion-plan-actions.csv" in artifacts[
        "openva-source-maintenance-report"
    ]


def test_discovery_mesh_delegates_full_catalog_intake_after_artifact_publication():
    discovery = (WORKFLOW_DIR / "discovery-mesh.yml").read_text(encoding="utf-8")
    recovery = (WORKFLOW_DIR / "discovery-mesh-intake-recovery.yml").read_text(
        encoding="utf-8"
    )

    assert "Record partitioned intake handoff" in discovery
    assert "discovery-mesh-intake-recovery.yml" in discovery
    assert "Prepare exact intake branch" not in discovery
    assert "Open candidate-intake PR and enable native auto-merge" not in discovery
    assert "workflows: [discovery-mesh]" in recovery
    assert "run-id: ${{ steps.source.outputs.run_id }}" in recovery
    assert "tools.openva.discovery_mesh_intake prepare" in recovery


def test_discovery_mesh_recovery_preserves_scope_authority_and_uncapped_growth():
    recovery = (WORKFLOW_DIR / "discovery-mesh-intake-recovery.yml").read_text(
        encoding="utf-8"
    )

    declaration = "Work-Package: WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01"
    assert recovery.count(declaration) == 2
    assert "Catalog vendor count cap: none" in recovery
    assert "Total candidate action cap: none" in recovery
    assert "candidate-promotion-pr.yml" in recovery
    assert "Canonical vendor/source mutation: false" in recovery
    assert 'gh pr list --state all --head "$BRANCH"' in recovery
    assert "workflow-owned branch exists with unexpected commit" in recovery
