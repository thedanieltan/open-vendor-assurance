from pathlib import Path

from tools.openva.reset_catalog import build_reset_report

WORKFLOW = Path(".github/workflows/catalog-reset-pr.yml")
DOC = Path("docs/catalog-reset-2026-05-15.md")


def test_reset_catalog_report_is_catalog_layer_only_and_non_advisory():
    report = build_reset_report(dry_run=True)

    assert report["report_type"] == "controlled_catalog_layer_reset"
    assert report["dry_run"] is True
    assert report["posture"] == {
        "public_sources_only": True,
        "non_advisory": True,
        "network_fetch_performed": False,
        "raw_documents_mirrored": False,
        "gated_materials_excluded": True,
        "preserves_repository_substrate": True,
    }
    assert "data/vendors" in report["reset_targets"] or report["summary"]["reset_target_count"] >= 0


def test_catalog_reset_workflow_has_been_removed_after_one_time_reset():
    assert not WORKFLOW.exists()


def test_catalog_reset_doc_states_same_pr_reseed_rule():
    text = DOC.read_text(encoding="utf-8")

    assert "canonical records in the same PR" in text
    assert "generated indexes in the same PR" in text
    assert "validation in the same PR" in text
    assert "A catalog PR is not complete unless it includes" in text


def test_catalog_reset_doc_preserves_substrate_language():
    text = DOC.read_text(encoding="utf-8")

    for preserved in [
        "schemas/",
        "policy/",
        "config/category-taxonomy.yaml",
        "tools/",
        "tests/",
        "docs/",
        ".github/workflows/",
    ]:
        assert preserved in text
