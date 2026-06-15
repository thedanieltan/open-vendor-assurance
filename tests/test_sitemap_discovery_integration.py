"""Tier A: sitemap discovery wired into the live discovery controller.

Proves: scheduled discovery (queue with the mode enabled) -> bounded sitemap
inspection -> normalized discovery event (valid under the existing ledger) ->
unified candidate path. And the acceptance invariant: a sitemap-discovered
locator cannot, by itself, satisfy materialization gates.
"""

import pytest

from tools.openva.candidate_promotion_actions import validate_materialization_thresholds
from tools.openva.catalog_growth_discovery_queue import (
    SITEMAP_DISCOVERY_MODE,
    run_sitemap_source_discovery,
    sitemap_discovery_enabled,
)
from tools.openva.discovery_ledger import validate_event
from tools.openva.sitemap_discovery import FetchResult

VENDOR = {"vendor_id": "vendor", "official_domains": ["vendor.example"]}
RUN = {"discovery_run_id": "run-1", "discovered_at": "2026-06-15T00:00:00Z"}


def _sitemap_body(*urls: str) -> bytes:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'.encode()


def _fetcher(mapping):
    def fetch(url):
        spec = mapping.get(url)
        if spec is None:
            return FetchResult(status=404, final_url=url, body=b"")
        return FetchResult(status=200, final_url=url, body=spec)

    return fetch


def _queue(modes):
    return {"discovery_modes": modes, "limits": {"max_vendors_per_discovery_run": 5}}


def test_enabled_mode_runs_sitemap_inspection_and_emits_normalized_candidate_events():
    queue = _queue([SITEMAP_DISCOVERY_MODE])
    assert sitemap_discovery_enabled(queue)
    fetcher = _fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/trust", "https://vendor.example/security/dpa",
    )})
    events = run_sitemap_source_discovery(queue, [VENDOR], fetcher, **RUN)

    assert events, "the enabled mode must actually produce candidate events"
    urls = {e["candidate_url"] for e in events}
    assert "https://vendor.example/trust" in urls  # unified candidate path
    for event in events:
        assert validate_event(event) == []  # normalized: valid under the ledger
        assert event["origin"] == "sitemap"
        assert event["classification"] == "unverified_candidate"
        assert "promotion_weight:none" in event["reason_codes"]


def test_disabled_mode_runs_nothing():
    assert run_sitemap_source_discovery(_queue(["seed_file_vendor_discovery"]), [VENDOR], _fetcher({}), **RUN) == []


def test_sitemap_locator_alone_cannot_satisfy_materialization():
    # A sitemap candidate is a locator with no retrieval evidence. Feeding it as
    # a materialization action fails closed (no agreeing independent retrievals).
    queue = _queue([SITEMAP_DISCOVERY_MODE])
    fetcher = _fetcher({"https://vendor.example/sitemap.xml": _sitemap_body("https://vendor.example/trust")})
    events = run_sitemap_source_discovery(queue, [VENDOR], fetcher, **RUN)
    locator = events[0]["candidate_url"]

    action = {
        "vendor": {"candidate_vendor_id": "vendor", "official_domain_candidate": "vendor.example"},
        "source": {
            "candidate_url": locator,
            "evidence": {  # locator only: no matched_terms, no agreeing independent retrievals
                "final_url": locator,
                "name_supported_by_official_domain_metadata": True,
                "source_host_authority": "vendor_controlled",
                "adversarial_review": "clean",
                "evidence_fresh": True,
            },
        },
    }
    with pytest.raises(ValueError) as exc:
        validate_materialization_thresholds(action)
    assert "retrieval_attempts" in str(exc.value)
