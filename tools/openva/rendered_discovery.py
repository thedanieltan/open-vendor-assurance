"""Selective JavaScript rendering behind OpenVA's SSRF-safe fetch boundary.

Chromium never receives direct network access. Every browser request is intercepted
and fulfilled by a caller-supplied bounded fetcher. The production caller supplies
OpenVA's DNS-pinned ``SafeFetcher``; tests can use deterministic in-memory responses.
Rendered output remains discovery evidence only and never mutates canonical state.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urljoin, urlparse

HIGH_VALUE_PATH_TERMS = (
    "privacy",
    "legal",
    "security",
    "trust",
    "compliance",
    "subprocessor",
    "data-processing",
    "dpa",
    "certification",
)
FRAMEWORK_MARKERS = (
    "__next_data__",
    "__nuxt__",
    "data-reactroot",
    "ng-version",
    "data-v-app",
    "webpackjsonp",
    "vite",
)
SPA_ROOT_IDS = {"root", "app", "__next", "__nuxt", "___gatsby"}
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
_SAFE_RESPONSE_HEADERS = {
    "content-type",
    "content-language",
    "cache-control",
    "etag",
    "last-modified",
    "access-control-allow-origin",
    "access-control-allow-headers",
    "access-control-allow-methods",
}


class BrowserFetchResult(Protocol):
    status: int
    final_url: str
    body: bytes
    headers: Mapping[str, str]


BrowserFetcher = Callable[[str], BrowserFetchResult]
AuthorityCheck = Callable[[str], bool]


@dataclass(frozen=True)
class RenderLimits:
    """Per-page and per-vendor resource bounds; never a catalog breadth cap."""

    max_pages_per_vendor: int = 8
    max_requests_per_page: int = 80
    max_bytes_per_page: int = 8_000_000
    max_response_bytes: int = 2_000_000
    max_rendered_html_bytes: int = 1_000_000
    navigation_timeout_ms: int = 12_000
    settle_time_ms: int = 750


@dataclass(frozen=True)
class JavascriptDependency:
    eligible: bool
    score: int
    reasons: tuple[str, ...]
    script_count: int
    external_script_count: int
    visible_text_characters: int
    anchor_count: int


@dataclass(frozen=True)
class RenderedLink:
    url: str
    anchor_text: str
    surrounding_text: str
    rel: str


@dataclass(frozen=True)
class RenderOutcome:
    requested_url: str
    final_url: str
    html: str
    request_count: int
    fulfilled_count: int
    blocked_count: int
    bytes_fulfilled: int
    fetched_urls: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None


class _ShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.script_count = 0
        self.external_script_count = 0
        self.anchor_count = 0
        self.root_markers: set[str] = set()
        self.noscript_parts: list[str] = []
        self.visible_parts: list[str] = []
        self._hidden_depth = 0
        self._noscript_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if low in {"script", "style", "template", "svg"}:
            self._hidden_depth += 1
        if low == "script":
            self.script_count += 1
            if values.get("src"):
                self.external_script_count += 1
        elif low == "a" and values.get("href"):
            self.anchor_count += 1
        elif low == "noscript":
            self._noscript_depth += 1
        element_id = values.get("id", "").strip().lower()
        if element_id in SPA_ROOT_IDS:
            self.root_markers.add(element_id)

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in {"script", "style", "template", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1
        if low == "noscript" and self._noscript_depth:
            self._noscript_depth -= 1

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._noscript_depth:
            self.noscript_parts.append(text)
        elif not self._hidden_depth:
            self.visible_parts.append(text)


class _RenderedLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[RenderedLink] = []
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.text_parts: list[str] = []
        self._href: str | None = None
        self._rel = ""
        self._anchor_parts: list[str] = []
        self._in_title = False
        self._heading_depth = 0
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if low in {"script", "style", "template", "svg"}:
            self._hidden_depth += 1
        if low == "a" and values.get("href"):
            self._href = values["href"]
            self._rel = values.get("rel", "")
            self._anchor_parts = []
        elif low == "title":
            self._in_title = True
        elif low in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low == "a" and self._href:
            anchor = _normalize(" ".join(self._anchor_parts))
            context = _normalize(" ".join(self.text_parts[-20:]))[-1_000:]
            self.links.append(
                RenderedLink(
                    url=urljoin(self.base_url, self._href),
                    anchor_text=anchor,
                    surrounding_text=context,
                    rel=self._rel,
                )
            )
            self._href = None
            self._rel = ""
            self._anchor_parts = []
        elif low == "title":
            self._in_title = False
        elif low in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._heading_depth:
            self._heading_depth -= 1
        if low in {"script", "style", "template", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        text = _normalize(data)
        if not text:
            return
        self.text_parts.append(text)
        if self._href:
            self._anchor_parts.append(text)
        if self._in_title:
            self.title_parts.append(text)
        if self._heading_depth:
            self.heading_parts.append(text)

    @property
    def title(self) -> str:
        return _normalize(" ".join(self.title_parts))[:500]

    @property
    def headings(self) -> str:
        return _normalize(" ".join(self.heading_parts))[:2_000]

    @property
    def text(self) -> str:
        return _normalize(" ".join(self.text_parts))[:20_000]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def detect_javascript_dependency(
    *,
    url: str,
    html: str,
    static_candidate_count: int = 0,
) -> JavascriptDependency:
    """Select likely JS shells; ordinary JavaScript-enhanced pages remain static-only."""

    parser = _ShellParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return JavascriptDependency(False, 0, ("html_parse_failed",), 0, 0, 0, 0)

    raw = html.casefold()
    visible_chars = len(_normalize(" ".join(parser.visible_parts)))
    reasons: list[str] = []
    score = 0
    noscript = _normalize(" ".join(parser.noscript_parts)).casefold()
    if "javascript" in noscript and any(
        term in noscript for term in ("enable", "required", "need")
    ):
        reasons.append("noscript_requires_javascript")
        score += 5
    if parser.root_markers and parser.script_count:
        reasons.append("spa_root_with_scripts")
        score += 3
    if any(marker in raw for marker in FRAMEWORK_MARKERS):
        reasons.append("framework_marker")
        score += 2
    if parser.script_count >= 2 and visible_chars < 300:
        reasons.append("script_heavy_low_text_shell")
        score += 3
    path = urlparse(url).path.casefold()
    if (
        static_candidate_count == 0
        and parser.script_count
        and any(term in path for term in HIGH_VALUE_PATH_TERMS)
    ):
        reasons.append("high_value_path_without_static_candidates")
        score += 3
    if static_candidate_count == 0 and parser.anchor_count == 0 and parser.script_count >= 3:
        reasons.append("no_static_links")
        score += 2

    return JavascriptDependency(
        eligible=score >= 4,
        score=score,
        reasons=tuple(reasons),
        script_count=parser.script_count,
        external_script_count=parser.external_script_count,
        visible_text_characters=visible_chars,
        anchor_count=parser.anchor_count,
    )


def extract_rendered_links(
    html: str, *, base_url: str
) -> tuple[list[RenderedLink], dict[str, str]]:
    parser = _RenderedLinkParser(base_url)
    parser.feed(html)
    parser.close()
    unique: dict[tuple[str, str], RenderedLink] = {}
    for link in parser.links:
        unique[(link.url, link.anchor_text)] = link
    return list(unique.values()), {
        "title": parser.title,
        "headings": parser.headings,
        "text": parser.text,
    }


class PlaywrightRenderer:
    """Render with Chromium while routing every request through a safe fetcher."""

    def __init__(self, limits: RenderLimits | None = None) -> None:
        self.limits = limits or RenderLimits()

    def render(
        self,
        url: str,
        *,
        fetcher: BrowserFetcher,
        authority_check: AuthorityCheck,
    ) -> RenderOutcome:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return RenderOutcome(url, url, "", 0, 0, 0, 0, error="playwright_unavailable")

        counters: dict[str, Any] = {
            "requests": 0,
            "fulfilled": 0,
            "blocked": 0,
            "bytes": 0,
            "urls": [],
            "budget_exceeded": False,
        }

        def handle(route: Any) -> None:
            request = route.request
            counters["requests"] += 1
            request_url = request.url
            if request.method != "GET" or request.resource_type in _BLOCKED_RESOURCE_TYPES:
                counters["blocked"] += 1
                route.abort("blockedbyclient")
                return
            if counters["requests"] > self.limits.max_requests_per_page:
                counters["blocked"] += 1
                counters["budget_exceeded"] = True
                route.abort("blockedbyclient")
                return
            if not authority_check(request_url):
                counters["blocked"] += 1
                route.abort("accessdenied")
                return
            try:
                result = fetcher(request_url)
            except Exception:
                counters["blocked"] += 1
                route.abort("failed")
                return
            body = bytes(result.body)
            if len(body) > self.limits.max_response_bytes:
                counters["blocked"] += 1
                route.abort("blockedbyresponse")
                return
            if counters["bytes"] + len(body) > self.limits.max_bytes_per_page:
                counters["blocked"] += 1
                counters["budget_exceeded"] = True
                route.abort("blockedbyresponse")
                return
            headers = {
                str(key).lower(): str(value)
                for key, value in dict(result.headers or {}).items()
                if str(key).lower() in _SAFE_RESPONSE_HEADERS
            }
            counters["bytes"] += len(body)
            counters["fulfilled"] += 1
            counters["urls"].append(str(result.final_url or request_url))
            route.fulfill(status=int(result.status), headers=headers, body=body)

        final_url = url
        html = ""
        error: str | None = None
        if not authority_check(url):
            return RenderOutcome(url, url, "", 0, 0, 1, 0, error="off_authority")
        try:
            initial = fetcher(url)
            if int(initial.status) != 200:
                return RenderOutcome(
                    url,
                    str(initial.final_url or url),
                    "",
                    1,
                    0,
                    1,
                    0,
                    error=f"initial_status:{int(initial.status)}",
                )
            initial_body = bytes(initial.body)
            if len(initial_body) > self.limits.max_response_bytes:
                return RenderOutcome(url, url, "", 1, 0, 1, 0, error="response_too_large")
            counters["requests"] = 1
            counters["fulfilled"] = 1
            counters["bytes"] = len(initial_body)
            final_url = str(initial.final_url or url)
            counters["urls"].append(final_url)
            initial_html = initial_body.decode("utf-8", "replace")
            base_tag = f'<base href="{final_url}">'
            if re.search(r"<head(?:\s[^>]*)?>", initial_html, flags=re.IGNORECASE):
                initial_html = re.sub(
                    r"(<head(?:\s[^>]*)?>)",
                    r"\1" + base_tag,
                    initial_html,
                    count=1,
                    flags=re.IGNORECASE,
                )
            else:
                initial_html = base_tag + initial_html
        except Exception as exc:
            return RenderOutcome(
                url, url, "", 1, 0, 1, 0, error=f"initial_fetch_error:{type(exc).__name__}"
            )
        try:
            with sync_playwright() as playwright:
                launch_args = [
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--no-first-run",
                ]
                executable = (
                    os.environ.get("OPENVA_CHROMIUM_EXECUTABLE") or shutil.which("chromium")
                )
                launch_options: dict[str, Any] = {"headless": True, "args": launch_args}
                if executable:
                    launch_options["executable_path"] = executable
                browser = playwright.chromium.launch(**launch_options)
                context = browser.new_context(
                    accept_downloads=False,
                    java_script_enabled=True,
                    offline=True,
                    service_workers="block",
                )
                context.route("**/*", handle)
                page = context.new_page()
                page.set_content(
                    initial_html,
                    wait_until="domcontentloaded",
                    timeout=self.limits.navigation_timeout_ms,
                )
                page.wait_for_timeout(self.limits.settle_time_ms)
                html = page.content()
                if len(html.encode("utf-8")) > self.limits.max_rendered_html_bytes:
                    html = ""
                    error = "rendered_html_too_large"
                context.close()
                browser.close()
        except PlaywrightTimeoutError:
            error = "render_timeout"
        except PlaywrightError as exc:
            error = f"render_error:{type(exc).__name__}"
        except Exception as exc:
            error = f"render_error:{type(exc).__name__}"

        if counters["budget_exceeded"] and error is None:
            error = "render_budget_exceeded"
        return RenderOutcome(
            requested_url=url,
            final_url=final_url,
            html=html,
            request_count=int(counters["requests"]),
            fulfilled_count=int(counters["fulfilled"]),
            blocked_count=int(counters["blocked"]),
            bytes_fulfilled=int(counters["bytes"]),
            fetched_urls=tuple(dict.fromkeys(counters["urls"])),
            error=error,
        )
