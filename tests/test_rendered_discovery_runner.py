from __future__ import annotations

from tools.openva import rendered_discovery_runner as runner
from tools.openva.rendered_discovery import RenderOutcome
from tools.openva.source_verification import FetchResult


def fetched(url: str, body: str) -> FetchResult:
    return FetchResult(url, url, 200, "text/html", len(body), None, None, body.encode(), None)


class FakeRenderer:
    def render(self, url, *, fetcher, authority_check):
        assert authority_check(url)
        return RenderOutcome(
            requested_url=url,
            final_url=url,
            html=(
                "<html><head><title>Trust Center</title></head><body>"
                "<a href='/legal/dpa'>Data Processing Addendum</a></body></html>"
            ),
            request_count=2,
            fulfilled_count=2,
            blocked_count=0,
            bytes_fulfilled=200,
        )


def test_augment_vendor_recovers_js_only_locator(monkeypatch) -> None:
    vendor = {"vendor_id": "example", "official_domains": ["example.com"]}
    shell = (
        "<html><body><div id='root'></div>"
        "<noscript>You need to enable JavaScript.</noscript>"
        "<script src='/app.js'></script></body></html>"
    )
    frontier = {
        "source_locator_signals": [],
        "discovery_memory": [
            {
                "url": "https://example.com/trust",
                "final_url": "https://example.com/trust",
                "http_status": 200,
                "candidate_count": 0,
                "provider": "official_entrypoint",
                "depth": 0,
                "error": None,
            }
        ],
    }
    mapping = {
        "https://example.com/trust": fetched("https://example.com/trust", shell),
        "https://example.com/legal/dpa": fetched(
            "https://example.com/legal/dpa", "<h1>Data Processing Addendum</h1>"
        ),
    }

    def verify(vendor, urls, **kwargs):
        assert "https://example.com/legal/dpa" in urls
        return {
            "candidates": [{"candidate_source_id": "example-dpa", "evidence": {}}],
            "observations": [],
            "discovery_events": [],
        }

    monkeypatch.setattr(runner, "verify_sitemap_locators", verify)
    result = runner.augment_vendor_with_rendered_discovery(
        vendor=vendor,
        frontier=frontier,
        static_fetcher=lambda url: mapping[url],
        browser_fetcher=lambda url: None,
        source_types=("dpa", "trust_center"),
        discovered_at="2026-07-16T00:00:00Z",
        renderer=FakeRenderer(),
    )
    assert result["metrics"]["javascript_fallback_eligible_pages"] == 1
    assert result["metrics"]["rendered_verified_candidate_count"] == 1
    assert any(row["source_type_candidate"] == "dpa" for row in result["signals"])
    assert result["verification"]["candidates"][0]["discovery_method"] == (
        "rendered_dom_locator_verification"
    )
