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
