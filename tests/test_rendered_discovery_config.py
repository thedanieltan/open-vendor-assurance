from __future__ import annotations

from tools.openva import discovery_mesh_config as config


def test_rendered_discovery_has_per_vendor_and_per_page_safety_bounds() -> None:
    assert config.JAVASCRIPT_RENDERING_FALLBACK is True
    assert config.RENDER_MAX_PAGES_PER_VENDOR > 0
    assert config.RENDER_MAX_REQUESTS_PER_PAGE > 0
    assert config.RENDER_MAX_BYTES_PER_PAGE >= config.RENDER_MAX_RESPONSE_BYTES
    assert config.RENDER_MAX_HTML_BYTES <= config.RENDER_MAX_BYTES_PER_PAGE
    assert config.RENDER_TIMEOUT_MS > config.RENDER_SETTLE_MS > 0
    assert config.CATALOG_VENDOR_LIMIT is None


def test_push_smoke_uses_separate_small_runtime_bounds() -> None:
    smoke = config.runtime_bounds("push")
    production = config.runtime_bounds("schedule")

    assert smoke == config.DEPLOYMENT_SMOKE_BOUNDS
    assert production == config.PRODUCTION_BOUNDS
    assert smoke["max_pages_per_vendor"] < production["max_pages_per_vendor"]
    assert smoke["max_total_requests_per_vendor"] < production["max_total_requests_per_vendor"]
    assert smoke["fetch_timeout_seconds"] < production["fetch_timeout_seconds"]
    assert smoke["render_max_pages_per_vendor"] < production["render_max_pages_per_vendor"]


def test_manual_and_scheduled_execution_keep_production_bounds() -> None:
    assert config.runtime_bounds("workflow_dispatch") == config.PRODUCTION_BOUNDS
    assert config.runtime_bounds("schedule") == config.PRODUCTION_BOUNDS
    assert config.CATALOG_VENDOR_LIMIT is None
