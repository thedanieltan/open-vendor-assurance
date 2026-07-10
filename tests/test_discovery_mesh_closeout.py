from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLOSEOUT = ROOT / "docs" / "operations" / "DISCOVERY_MESH_CLOSEOUT.md"
OPERATING_MODEL = ROOT / "docs" / "operations" / "DISCOVERY_MESH_OPERATING_MODEL.md"


def test_closeout_distinguishes_implementation_from_live_acceptance() -> None:
    text = CLOSEOUT.read_text(encoding="utf-8")

    assert "Implementation is complete when the final closeout pull request merges" in text
    assert "Production acceptance remains pending" in text
    assert "first successful full-catalog `discovery-mesh.yml` run" in text
    assert "actual workflow run ID" in text
    assert "must not be prefilled or inferred" in text


def test_closeout_keeps_catalog_and_provider_projection_uncapped() -> None:
    text = CLOSEOUT.read_text(encoding="utf-8")

    assert "No catalog vendor-count ceiling exists" in text
    assert "catalog_vendor_count_cap: null" in text
    assert "retain an uncapped catalog and uncapped provider candidate projection" in text


def test_live_acceptance_covers_noop_breadth_only_and_source_plan_paths() -> None:
    text = CLOSEOUT.read_text(encoding="utf-8")

    assert "A true no-op run creates no candidate-intake pull request" in text
    assert "A breadth-only intake merge does not dispatch canonical mutation" in text
    assert "stages only candidate records referenced by the exact reviewed plan" in text
    assert "candidate-promotion-pr.yml" in text
    assert "Replaying identical provider signals does not inflate demand" in text


def test_operating_model_records_health_gating_and_exact_intake_boundary() -> None:
    text = OPERATING_MODEL.read_text(encoding="utf-8")

    assert "Production health and intake decision" in text
    assert "true no-op runs upload evidence and exit without creating a pull request" in text
    assert "Exact candidate-intake boundary" in text
    assert "candidate-source YAML records explicitly referenced by that exact plan" in text
    assert "Run-specific identity signals" in text
    assert "breadth projections" in text
    assert "does not score vendors" in text


def test_closeout_preserves_non_advisory_product_boundary() -> None:
    text = CLOSEOUT.read_text(encoding="utf-8")

    assert "does not assess vendor risk" in text
    assert "determine contractual parties" in text
    assert "recommend procurement action" in text
    assert "legal, audit, security, KYC, or AML conclusions" in text
