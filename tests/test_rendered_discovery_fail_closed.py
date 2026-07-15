from __future__ import annotations

from dataclasses import dataclass

from tools.openva.rendered_discovery import PlaywrightRenderer, RenderLimits


@dataclass(frozen=True)
class Response:
    status: int
    final_url: str
    body: bytes
    headers: dict[str, str]


def test_renderer_rejects_non_success_entry_document() -> None:
    outcome = PlaywrightRenderer(RenderLimits()).render(
        "https://example.com/trust",
        fetcher=lambda url: Response(404, url, b"not found", {"content-type": "text/html"}),
        authority_check=lambda url: url.startswith("https://example.com/"),
    )
    assert outcome.error == "initial_status:404"
    assert outcome.html == ""
