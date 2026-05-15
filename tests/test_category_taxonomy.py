from pathlib import Path

import yaml

TAXONOMY = Path("config/category-taxonomy.yaml")
DOC = Path("docs/category-coverage-program.md")


def load_taxonomy() -> dict:
    return yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))


def test_category_taxonomy_exists_and_is_non_advisory():
    taxonomy = load_taxonomy()

    assert taxonomy["schema_version"] == "0.1.0"
    assert taxonomy["non_advisory"] is True
    assert "vendor_categories" in taxonomy
    assert "artifact_categories" in taxonomy
    assert "coverage_lanes" in taxonomy


def test_coverage_lanes_reference_defined_vendor_category_tags():
    taxonomy = load_taxonomy()
    defined_tags = set(taxonomy["vendor_categories"].keys())

    for lane_id, lane in taxonomy["coverage_lanes"].items():
        assert lane_id
        assert lane["target_materialized_vendors"] > 0
        assert lane["target_deep_vendors"] > 0
        assert lane["tier_1_min_core_artifacts"] >= 2
        assert lane["target_deep_vendors"] <= lane["target_materialized_vendors"]
        for tag in lane["vendor_category_tags"]:
            assert tag in defined_tags, f"{lane_id}: undefined vendor category tag {tag}"


def test_artifact_categories_reference_artifact_types_not_vendor_categories():
    taxonomy = load_taxonomy()

    for category_id, category in taxonomy["artifact_categories"].items():
        assert category_id
        assert category["maps_to_artifact_types"]
        assert all(isinstance(item, str) for item in category["maps_to_artifact_types"])


def test_category_coverage_program_uses_metadata_tags_not_standalone_entities():
    text = DOC.read_text(encoding="utf-8")

    assert "categories as controlled metadata tags" in text
    assert "not as standalone vendor entities" in text
    assert "config/category-taxonomy.yaml" in text
    assert "Coverage lanes are planning and reporting groupings" in text
    assert "They are not canonical data entities" in text


def test_category_coverage_program_preserves_non_advisory_boundary():
    text = DOC.read_text(encoding="utf-8")

    assert "vendor is compliant" in text
    assert "vendor is recommended" in text
    assert "vendor is low risk" in text
    assert "legal, regulatory, audit, procurement, or security requirement" in text
