from pathlib import Path

WORKFLOW = Path(".github/workflows/catalog-maintenance-pr.yml")


def test_catalog_maintenance_pr_body_is_compact_and_artifact_backed():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Prepare compact PR body" in text
    assert "cat cleanup-proposal.md >> catalog-maintenance-pr-body.md" not in text
    assert "Full cleanup proposal is available in the workflow artifact" in text
    assert "cleanup-proposal.md" in text
    assert "maintenance-action-report.json" in text
    assert "catalog-maintenance-pr-body.md" in text
    assert "--body-file catalog-maintenance-pr-body.md" in text
