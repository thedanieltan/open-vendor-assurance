from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.openva.rendered_discovery import (
    PlaywrightRenderer,
    RenderLimits,
    detect_javascript_dependency,
    extract_rendered_links,
)


@dataclass(frozen=True)
class Response:
    status: int
    final_url: str
    body: bytes
    headers: dict[str, str]


def test_static_content_is_not_selected_for_browser_rendering() -> None:
    assessment = detect_javascript_dependency(
        url="https://example.com/privacy",
        html="<html><body><h1>Privacy Policy</h1><a href='/dpa'>DPA</a></body></html>",
        static_candidate_count=1,
    )
    assert assessment.eligible is False
    assert assessment.score < 4


def test_javascript_shell_is_selected() -> None:
    assessment = detect_javascript_dependency(
        url="https://example.com/trust",
        html=(
            "<html><body><div id='root'></div>"
            "<noscript>You need to enable JavaScript to run this app.</noscript>"
            "<script src='/app.js'></script></body></html>"
        ),
    )
    assert assessment.eligible is True
    assert "noscript_requires_javascript" in assessment.reasons
    assert "spa_root_with_scripts" in assessment.reasons


def test_rendered_link_parser_extracts_dynamic_links() -> None:
    links, page = extract_rendered_links(
        "<html><head><title>Trust</title></head><body>"
        "<h1>Security</h1><a href='/legal/dpa'>Data Processing Addendum</a>"
        "</body></html>",
        base_url="https://example.com/trust",
    )
    assert links[0].url == "https://example.com/legal/dpa"
    assert links[0].anchor_text == "Data Processing Addendum"
    assert page["title"] == "Trust"
    assert page["headings"] == "Security"


def test_playwright_renderer_executes_javascript_through_intercepted_fetcher() -> None:
    pytest.importorskip("playwright.sync_api")
    responses = {
        "https://example.com/trust": Response(
            200,
            "https://example.com/trust",
            (
                "<html><body><div id='root'></div>"
                "<script src='/app.js'></script></body></html>"
            ).encode(),
            {"content-type": "text/html; charset=utf-8"},
        ),
        "https://example.com/app.js": Response(
            200,
            "https://example.com/app.js",
            (
                "document.getElementById('root').innerHTML = "
                "\"<a href='/legal/dpa'>Data Processing Addendum</a>\";"
            ).encode(),
            {"content-type": "application/javascript"},
        ),
    }

    def fetch(url: str) -> Response:
        return responses[url]

    outcome = PlaywrightRenderer(
        RenderLimits(navigation_timeout_ms=5_000, settle_time_ms=100)
    ).render(
        "https://example.com/trust",
        fetcher=fetch,
        authority_check=lambda url: url.startswith("https://example.com/"),
    )

    assert outcome.error is None
    assert outcome.fulfilled_count == 2
    assert outcome.request_count == 2
    assert "Data Processing Addendum" in outcome.html
    links, _ = extract_rendered_links(outcome.html, base_url=outcome.final_url)
    assert [link.url for link in links] == ["https://example.com/legal/dpa"]


def test_renderer_blocks_off_authority_requests() -> None:
    pytest.importorskip("playwright.sync_api")
    responses = {
        "https://example.com/trust": Response(
            200,
            "https://example.com/trust",
            (
                "<html><body><script src='https://evil.example/app.js'>"
                "</script></body></html>"
            ).encode(),
            {"content-type": "text/html"},
        )
    }

    outcome = PlaywrightRenderer(
        RenderLimits(navigation_timeout_ms=5_000, settle_time_ms=100)
    ).render(
        "https://example.com/trust",
        fetcher=lambda url: responses[url],
        authority_check=lambda url: url.startswith("https://example.com/"),
    )

    assert outcome.fulfilled_count == 1
    assert outcome.blocked_count == 1
