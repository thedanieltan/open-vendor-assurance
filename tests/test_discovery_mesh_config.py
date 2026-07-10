from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "discovery-mesh.yaml"


def test_discovery_mesh_has_no_catalog_vendor_cap() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    assert config["catalog"]["vendor_limit"] is None
    assert config["catalog"]["shard_count"] >= 16
    assert config["posture"]["full_catalog_sharded"] is True


def test_discovery_mesh_per_vendor_bounds_are_not_catalog_caps() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    bounds = config["per_vendor"]

    assert bounds["max_pages"] >= 5_000
    assert bounds["max_total_requests"] >= bounds["max_pages"]
    assert bounds["max_locator_candidates"] >= 10_000
    assert config["execution"]["candidate_promotion_action_cap"] is None
