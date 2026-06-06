from pathlib import Path


WORKFLOW = Path(".github/workflows/catalog-growth-discovery.yml")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_catalog_growth_discovery_emits_strict_growth_shortlist_artifacts():
    text = workflow_text()

    assert "- name: Build strict growth shortlist" in text
    assert "python -m tools.openva.strict_growth_shortlist build \\" in text
    assert "--eligibility-report catalog-growth-eligibility-report.json" in text
    assert "--backlog-report catalog-growth-backlog-report.json" in text
    assert "--output-json strict-growth-shortlist.json" in text
    assert "--output-csv reports/strict-growth-shortlist.csv" in text
    assert "--output-md reports/strict-growth-shortlist-summary.md" in text

    assert "reports/strict-growth-shortlist-summary.md" in text
    assert "reports/strict-growth-shortlist.csv" in text
    assert "strict-growth-shortlist.json" in text


def test_catalog_growth_discovery_issue_includes_shortlist_diagnostics():
    text = workflow_text()

    assert "Strict-growth shortlist count" in text
    assert "Shortlisted vendors" in text
    assert "Excluded candidates by reason" in text
    assert "excluded_by_reason" in text
