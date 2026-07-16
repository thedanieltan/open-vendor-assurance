"""Operational configuration for the discovery mesh worker.

Catalog breadth is intentionally uncapped. Resource bounds below are per vendor,
not limits on the number of vendors OpenVA may discover or maintain.
"""

from __future__ import annotations

import os
from typing import Any

HOSTED_SMOKE_CONTRACT_VERSION = "0.1.2"
CATALOG_VENDOR_LIMIT: int | None = None
DEFAULT_SHARD_COUNT = 32
MAX_DEPTH_PER_VENDOR = 2
MAX_DELEGATED_HOSTS_PER_VENDOR = 500
MAX_RELATIONSHIP_PAGES_PER_VENDOR = 500

PRODUCTION_BOUNDS: dict[str, Any] = {
    "max_pages_per_vendor": 5_000,
    "max_total_requests_per_vendor": 7_500,
    "max_links_per_page": 2_000,
    "max_locator_candidates_per_vendor": 10_000,
    "fetch_timeout_seconds": 10.0,
    "render_max_pages_per_vendor": 8,
    "render_max_requests_per_page": 80,
    "render_max_bytes_per_page": 8_000_000,
    "render_max_response_bytes": 2_000_000,
    "render_max_html_bytes": 1_000_000,
    "render_timeout_ms": 12_000,
    "render_settle_ms": 750,
}

DEPLOYMENT_SMOKE_BOUNDS: dict[str, Any] = {
    "max_pages_per_vendor": 10,
    "max_total_requests_per_vendor": 15,
    "max_links_per_page": 200,
    "max_locator_candidates_per_vendor": 100,
    "fetch_timeout_seconds": 3.0,
    "render_max_pages_per_vendor": 2,
    "render_max_requests_per_page": 30,
    "render_max_bytes_per_page": 4_000_000,
    "render_max_response_bytes": 2_000_000,
    "render_max_html_bytes": 1_000_000,
    "render_timeout_ms": 8_000,
    "render_settle_ms": 500,
}


def runtime_bounds(event_name: str | None = None) -> dict[str, Any]:
    """Return deployment-smoke bounds only for a push-triggered hosted probe."""

    resolved_event = event_name if event_name is not None else os.environ.get("GITHUB_EVENT_NAME", "")
    selected = DEPLOYMENT_SMOKE_BOUNDS if resolved_event == "push" else PRODUCTION_BOUNDS
    return dict(selected)


_RUNTIME_BOUNDS = runtime_bounds()
MAX_PAGES_PER_VENDOR = int(_RUNTIME_BOUNDS["max_pages_per_vendor"])
MAX_TOTAL_REQUESTS_PER_VENDOR = int(_RUNTIME_BOUNDS["max_total_requests_per_vendor"])
MAX_LINKS_PER_PAGE = int(_RUNTIME_BOUNDS["max_links_per_page"])
MAX_LOCATOR_CANDIDATES_PER_VENDOR = int(
    _RUNTIME_BOUNDS["max_locator_candidates_per_vendor"]
)
FETCH_TIMEOUT_SECONDS = float(_RUNTIME_BOUNDS["fetch_timeout_seconds"])

JAVASCRIPT_RENDERING_FALLBACK = True
RENDER_MAX_PAGES_PER_VENDOR = int(_RUNTIME_BOUNDS["render_max_pages_per_vendor"])
RENDER_MAX_REQUESTS_PER_PAGE = int(_RUNTIME_BOUNDS["render_max_requests_per_page"])
RENDER_MAX_BYTES_PER_PAGE = int(_RUNTIME_BOUNDS["render_max_bytes_per_page"])
RENDER_MAX_RESPONSE_BYTES = int(_RUNTIME_BOUNDS["render_max_response_bytes"])
RENDER_MAX_HTML_BYTES = int(_RUNTIME_BOUNDS["render_max_html_bytes"])
RENDER_TIMEOUT_MS = int(_RUNTIME_BOUNDS["render_timeout_ms"])
RENDER_SETTLE_MS = int(_RUNTIME_BOUNDS["render_settle_ms"])

BREADTH_SHARE = 0.45
DEPTH_SHARE = 0.40
MAINTENANCE_SHARE = 0.15
CANDIDATE_PROMOTION_ACTION_CAP: int | None = None
INTAKE_AUTOMERGE = True
CANONICAL_MUTATION_WORKFLOW = "candidate-promotion-pr.yml"

FULL_CATALOG_SHARDED = True
SIGNALS_ARE_CATALOG_FACTS = False
CANONICAL_MUTATION_AUTHORITY_UNCHANGED = True
NON_ADVISORY = True
