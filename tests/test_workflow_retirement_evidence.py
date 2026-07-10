from pathlib import Path

import yaml


CONSOLIDATION_AUDIT = Path("docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md")
RETIREMENT_EVIDENCE = Path("docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md")
WORKFLOW_DIR = Path(".github/workflows")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")
WORKFLOW_RETIREMENT = Path("docs/operations/contracts/workflow-retirement.yaml")
WORKFLOW_RETIREMENT_PLAN = Path("docs/operations/WORKFLOW_RETIREMENT_PLAN.md")

RETIRE_CANDIDATE_WORKFLOWS = {
    "catalog-maintenance.yml",
    "source-refinement-queue.yml",
    "observe-report.yml",
}

EXPECTED_AUDIT_CLASSIFICATIONS = {
    "catalog-maintenance.yml": "retire_candidate",
    "source-refinement-queue.yml": "retire_candidate",
    "observe-report.yml": "quarantined",
}

REQUIRED_SECTIONS = {
    "### Current purpose",
    "### Current trigger",
    "### Current permissions",
    "### Artifacts produced",
    "### Current documented consumers",
    "### Tests that depend on it",
    "### Replacement workflow",
    "### Replacement artifact equivalence",
    "### Stale-reference status",
    "### Recommendation",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def inventory_entry(name: str) -> dict:
    return next(entry for entry in load_yaml(WORKFLOW_INVENTORY)["public_workflows"] if entry["name"] == name)


def retirement_entry(name: str) -> dict:
    return next(entry for entry in load_yaml(WORKFLOW_RETIREMENT)["workflows"] if entry["name"] == name)


def test_workflow_retirement_evidence_lists_every_retire_candidate():
    text = RETIREMENT_EVIDENCE.read_text(encoding="utf-8")

    for workflow_name in RETIRE_CANDIDATE_WORKFLOWS:
        assert f"`{workflow_name}`" in text
        assert f"## Candidate: `{workflow_name}`" in text

    for required_section in REQUIRED_SECTIONS:
        assert required_section in text


def test_retirement_evidence_keeps_candidates_until_replacements_are_proven():
    text = RETIREMENT_EVIDENCE.read_text(encoding="utf-8")

    assert "No workflow is removed by this package." in text
    assert "WP22 quarantines `source-refinement-queue.yml`" in text
    assert "WP26 quarantines `observe-report.yml`" in text
    assert "Keep as `retire_candidate`" in text
    assert "Keep as `quarantined`" in text
    assert "entity stub report is not proven to be fully folded into `coverage-audit.yml`" in text
    assert "`docs/source-refinement-workflow.md` is now marked legacy/quarantined" in text
    assert "`README.md` and `docs/observation-reporting.md` must be reviewed before removal" in text


def test_retirement_evidence_names_replacements_and_stale_reference_gaps():
    text = RETIREMENT_EVIDENCE.read_text(encoding="utf-8")

    assert "`validate.yml` replaces validation, index build, generated drift, and test checks." in text
    assert "`coverage-audit.yml` replaces much of the catalog quality reporting posture." in text
    assert "`source-maintenance-report.yml` now produces source quality refinement artifacts" in text
    assert "`source-refinement-scan.yml` handles confirmed P0 refinement" in text
    assert "`source-observation-ledger.json`" in text
    assert "`latest-source-health.json`" in text
    assert "`public/source-health-snapshot.json`" in text
    assert "`catalog-growth-discovery.yml` proposes catalog-growth candidates" in text


def test_consolidation_audit_links_retirement_evidence_without_remove_now_classification():
    audit = CONSOLIDATION_AUDIT.read_text(encoding="utf-8")
    evidence = RETIREMENT_EVIDENCE.read_text(encoding="utf-8")

    assert "WORKFLOW_RETIREMENT_EVIDENCE.md" in audit
    assert "`source-refinement-queue.yml` is quarantined by contract" in audit
    assert "`observe-report.yml` is quarantined by WP26" in audit
    assert "Current result: no workflow is classified as `remove_now_if_safe` in this package." in audit
    assert "Current result" in evidence
    assert "No workflow is removed by this package." in evidence


def test_no_retire_candidate_is_marked_remove_now_if_safe():
    audit = CONSOLIDATION_AUDIT.read_text(encoding="utf-8")

    for workflow_name, classification in EXPECTED_AUDIT_CLASSIFICATIONS.items():
        table_row_prefix = f"| `{workflow_name}` | `{classification}` |"
        assert table_row_prefix in audit
        assert f"| `{workflow_name}` | `remove_now_if_safe` |" not in audit


def test_observe_report_workflow_is_present_manual_only_and_read_only():
    workflow_path = WORKFLOW_DIR / "observe-report.yml"
    assert workflow_path.exists()

    workflow = load_yaml(workflow_path)
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"workflow_dispatch"}
    assert "schedule" not in triggers
    assert workflow["permissions"] == {"contents": "read"}


def test_observe_report_inventory_is_quarantined_manual_only():
    entry = inventory_entry("observe-report.yml")

    assert entry["loop"] == "legacy_report"
    assert entry["status"] == "quarantined"
    assert entry["triggers"] == ["workflow_dispatch"]
    assert entry["permissions"] == {"contents": "read"}
    assert entry["writes_repository_state"] is False
    assert entry["creates_prs"] is False
    assert entry["merges_prs"] is False


def test_observe_report_retirement_contract_is_quarantined_not_deletion_ready():
    entry = retirement_entry("observe-report.yml")

    assert entry["current_status"] == "quarantined"
    assert entry["inventory_status"] == "quarantined"
    assert entry["operating_loop"] == "legacy_report"
    assert "source-maintenance-report.yml" in entry["replacement_owner"]
    assert "catalog-growth-discovery.yml" in entry["replacement_owner"]
    assert entry["retirement_candidate"] is True
    assert entry["retirement_ready"] is False
    assert entry["must_not_retire_yet"] is True
    assert entry["allowed_triggers_until_retired"] == ["workflow_dispatch"]
    assert entry["write_permissions_allowed_until_retired"] is False
    assert entry["retirement_blockers"] == ["legacy observation report references remain"]
    assert entry["required_retirement_evidence"] == ["consumer migration evidence"]


def test_wp26_quarantined_observe_report_is_manual_only_without_requiring_prior_quarantines_to_change():
    entry = retirement_entry("observe-report.yml")
    workflow = load_yaml(WORKFLOW_DIR / "observe-report.yml")
    triggers = workflow_triggers(workflow)

    assert entry["current_status"] == "quarantined"
    assert set(triggers) == {"workflow_dispatch"}
    assert inventory_entry("observe-report.yml")["triggers"] == ["workflow_dispatch"]
    assert retirement_entry("observe-report.yml")["allowed_triggers_until_retired"] == ["workflow_dispatch"]


def test_workflow_retirement_plan_mentions_wp26_observe_quarantine():
    text = WORKFLOW_RETIREMENT_PLAN.read_text(encoding="utf-8")

    assert "observe-report.yml` is quarantined by WP26" in text
    assert "manual-only" in text
    assert "not destructive retirement" in text
