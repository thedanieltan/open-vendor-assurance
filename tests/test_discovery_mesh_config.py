from tools.openva import discovery_mesh_config as config


def test_discovery_mesh_has_no_catalog_vendor_cap() -> None:
    assert config.CATALOG_VENDOR_LIMIT is None
    assert config.DEFAULT_SHARD_COUNT >= 16
    assert config.FULL_CATALOG_SHARDED is True


def test_discovery_mesh_per_vendor_bounds_are_not_catalog_caps() -> None:
    assert config.MAX_PAGES_PER_VENDOR >= 5_000
    assert config.MAX_TOTAL_REQUESTS_PER_VENDOR >= config.MAX_PAGES_PER_VENDOR
    assert config.MAX_LOCATOR_CANDIDATES_PER_VENDOR >= 10_000
    assert config.CANDIDATE_PROMOTION_ACTION_CAP is None


def test_hosted_rendered_discovery_smoke_contract_is_versioned() -> None:
    assert config.HOSTED_SMOKE_CONTRACT_VERSION == "0.1.1"
    assert config.runtime_bounds("push") == config.DEPLOYMENT_SMOKE_BOUNDS
    assert config.runtime_bounds("schedule") == config.PRODUCTION_BOUNDS
