from pathlib import Path


CONSOLIDATION_AUDIT = Path("docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md")
RETIREMENT_EVIDENCE = Path("docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md")

RETIRE_CANDIDATE_WORKFLOWS = {
    "catalog-maintenance.yml",
    "source-refinement-queue.yml",
    "observe-report.yml",
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
    assert "Keep as `retire_candidate`" in text
    assert "entity stub report is not proven to be fully folded into `coverage-audit.yml`" in text
    assert "`docs/source-refinement-workflow.md` must be reviewed and migrated before removal" in text
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


def test_consolidation_audit_links_retirement_evidence_without_remove_now_classification():
    audit = CONSOLIDATION_AUDIT.read_text(encoding="utf-8")
    evidence = RETIREMENT_EVIDENCE.read_text(encoding="utf-8")

    assert "WORKFLOW_RETIREMENT_EVIDENCE.md" in audit
    assert "Current result: no workflow is classified as `remove_now_if_safe` in this package." in audit
    assert "Current result" in evidence
    assert "No workflow is removed by this package." in evidence


def test_no_retire_candidate_is_marked_remove_now_if_safe():
    audit = CONSOLIDATION_AUDIT.read_text(encoding="utf-8")

    for workflow_name in RETIRE_CANDIDATE_WORKFLOWS:
        table_row_prefix = f"| `{workflow_name}` | `retire_candidate` |"
        assert table_row_prefix in audit
        assert f"| `{workflow_name}` | `remove_now_if_safe` |" not in audit
