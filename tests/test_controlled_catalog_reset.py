from pathlib import Path

DOC = Path("docs/catalog-reset-2026-05-15.md")


def test_controlled_catalog_reset_documents_reason_and_scope():
    text = DOC.read_text(encoding="utf-8")

    assert "Controlled Catalog Reset" in text
    assert "vendor_count: 62" in text
    assert "artifact_count: 62" in text
    assert "vendors_with_dpa: 11" in text
    assert "vendors_with_subprocessors_list: 3" in text
    assert "vendors_with_at_least_three_core_artifacts: 0" in text
    assert "not a reset of the repository substrate" in text


def test_controlled_catalog_reset_requires_same_pr_materialization():
    text = DOC.read_text(encoding="utf-8")

    assert "batch manifest first, materialization later" in text
    assert "canonical records in the same PR" in text
    assert "generated indexes in the same PR" in text
    assert "validation in the same PR" in text
    assert "A catalog PR is not complete unless it includes" in text
    assert "data/vendors/{vendor_id}/vendor.yaml" in text
    assert "openva-pack.json" in text


def test_controlled_catalog_reset_preserves_substrate_but_allows_catalog_rebuild():
    text = DOC.read_text(encoding="utf-8")

    assert "schemas/" in text
    assert "policy/" in text
    assert "config/category-taxonomy.yaml" in text
    assert "tools/" in text
    assert "tests/" in text
    assert "data/vendors/" in text
    assert "catalog-batches/ stale or unmaterialized manifests" in text


def test_controlled_catalog_reset_preserves_source_boundaries():
    text = DOC.read_text(encoding="utf-8")

    assert "Public-source-only boundary" in text
    assert "Native-language boundary" in text
    assert "Non-advisory boundary" in text
    assert "customer-specific agreements" in text
    assert "authenticated trust-center documents" in text
    assert "vendor is compliant" in text
    assert "vendor is recommended" in text


def test_controlled_catalog_reset_sets_reseed_targets():
    text = DOC.read_text(encoding="utf-8")

    assert "150 materialized vendors" in text
    assert "250 materialized vendors" in text
    assert "top 25 tier-1 vendors with at least 4 core artifact types" in text
    assert "top 50 vendors with at least 3 core artifact types" in text
    assert "materially improved DPA coverage" in text
    assert "materially improved subprocessor-list coverage" in text
