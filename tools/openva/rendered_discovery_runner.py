"""Discovery-mesh shard runner with selective rendered-DOM fallback.

The ordinary bounded HTML graph remains the primary lane. Only likely JavaScript
shells with no useful static locator evidence are rendered. Chromium receives no
direct network access: all requests are fulfilled by OpenVA's SSRF-safe fetcher.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from tools.openva.discovery_mesh import (
    CrawlLimits,
    canonical_url,
    classify_locator,
    source_locator_signal,
    url_is_public_safe,
)
from tools.openva.discovery_mesh_runner import run_source_shard, selected_vendor_paths
from tools.openva.rendered_discovery import (
    HIGH_VALUE_PATH_TERMS,
    PlaywrightRenderer,
    RenderLimits,
    RenderOutcome,
    detect_javascript_dependency,
    extract_rendered_links,
)
from tools.openva.safe_fetch import SafeFetchError, build_safe_fetcher
from tools.openva.source_authority import is_on_official_domain
from tools.openva.source_discovery import (
    DEFAULT_SOURCE_TYPES,
    canonical_source_types_for_vendor,
    load_yaml,
    not_due_unavailable_source_types,
    parse_source_types,
    safe_discovery_fetcher,
    verify_sitemap_locators,
)
from tools.openva.source_verification import MAX_SAMPLE_BYTES, FetchResult, ROOT

SCHEMA_VERSION = "0.1.0"
POLICY_VERSION = "rendered-discovery.v1"


def _missing_source_types(
    vendor_id: str,
    requested: tuple[str, ...],
    root: Path,
) -> tuple[str, ...]:
    present = canonical_source_types_for_vendor(vendor_id, root)
    deferred = not_due_unavailable_source_types(vendor_id, root)
    return tuple(source_type for source_type in requested if source_type not in present | deferred)


def _candidate_render_urls(frontier: dict[str, Any], limits: RenderLimits) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    for row in frontier.get("discovery_memory", []) or []:
        if row.get("http_status") != 200 or row.get("error"):
            continue
        url = str(row.get("final_url") or row.get("url") or "")
        if not url or not url_is_public_safe(url):
            continue
        candidate_count = int(row.get("candidate_count") or 0)
        if candidate_count:
            continue
        path = urlparse(url).path.casefold()
        priority = 0
        if str(row.get("provider") or "") == "official_entrypoint":
            priority += 5
        if any(term in path for term in HIGH_VALUE_PATH_TERMS):
            priority += 4
        priority += max(0, 2 - int(row.get("depth") or 0))
        ranked.append((-priority, int(row.get("depth") or 0), url))
    selected = sorted(set(ranked))[: limits.max_pages_per_vendor * 4]
    return [url for _priority, _depth, url in selected]


def _rendered_fetch_result(outcome: RenderOutcome) -> FetchResult:
    body = outcome.html.encode("utf-8")
    return FetchResult(
        requested_url=outcome.requested_url,
        final_url=outcome.final_url,
        http_status=200 if outcome.html and outcome.error is None else None,
        content_type="text/html; charset=utf-8; rendered=playwright",
        content_length=len(body),
        etag=None,
        last_modified=None,
        body_sample=body[:MAX_SAMPLE_BYTES],
        error=outcome.error,
    )


def _safe_browser_fetcher(
    official_domains: list[str],
    *,
    fetch_timeout: float,
    limits: RenderLimits,
) -> Callable[[str], Any]:
    if not official_domains:
        raise ValueError("browser fetcher requires at least one official domain")
    fetcher = build_safe_fetcher(
        official_domains,
        max_redirects=5,
        timeout_seconds=fetch_timeout,
        max_compressed_bytes=limits.max_response_bytes,
        max_decompressed_bytes=limits.max_response_bytes,
        accept_encoding="identity",
    )
    return fetcher.fetch


def augment_vendor_with_rendered_discovery(
    *,
    vendor: dict[str, Any],
    frontier: dict[str, Any],
    static_fetcher: Callable[[str], FetchResult],
    browser_fetcher: Callable[[str], Any],
    source_types: tuple[str, ...],
    discovered_at: str,
    limits: RenderLimits | None = None,
    renderer: PlaywrightRenderer | None = None,
) -> dict[str, Any]:
    """Return rendered signals, verification output, cache, and differential metrics."""

    limits = limits or RenderLimits()
    renderer = renderer or PlaywrightRenderer(limits)
    vendor_id = str(vendor["vendor_id"])
    official_domains = [str(value) for value in vendor.get("official_domains", []) or [] if value]
    existing_signals = {
        str(row.get("signal_id") or ""): dict(row)
        for row in frontier.get("source_locator_signals", []) or []
        if row.get("signal_id")
    }
    queue = deque(_candidate_render_urls(frontier, limits))
    queued = set(queue)
    rendered: dict[str, FetchResult] = {}
    rendered_signals: dict[str, dict[str, Any]] = {}
    metrics: dict[str, Any] = {
        "policy_version": POLICY_VERSION,
        "pages_considered": len(queue),
        "javascript_fallback_eligible_pages": 0,
        "rendered_pages": 0,
        "render_failures": 0,
        "browser_requests": 0,
        "browser_fulfilled_requests": 0,
        "browser_blocked_requests": 0,
        "browser_bytes_fulfilled": 0,
        "rendered_locator_signal_count": 0,
        "rendered_verified_candidate_count": 0,
        "reason_counts": {},
    }

    while queue and metrics["rendered_pages"] < limits.max_pages_per_vendor:
        url = queue.popleft()
        try:
            static = static_fetcher(url)
        except Exception:
            metrics["render_failures"] += 1
            continue
        if static.http_status != 200 or not static.body_sample:
            continue
        html = static.body_sample.decode("utf-8", "replace")
        static_count = sum(
            1
            for row in frontier.get("source_locator_signals", []) or []
            if str(row.get("discovered_from") or "") in {url, static.final_url}
        )
        assessment = detect_javascript_dependency(
            url=static.final_url or url,
            html=html,
            static_candidate_count=static_count,
        )
        if not assessment.eligible:
            continue
        metrics["javascript_fallback_eligible_pages"] += 1
        for reason in assessment.reasons:
            counts = metrics["reason_counts"]
            counts[reason] = int(counts.get(reason, 0)) + 1

        outcome = renderer.render(
            static.final_url or url,
            fetcher=browser_fetcher,
            authority_check=lambda candidate: is_on_official_domain(candidate, official_domains),
        )
        metrics["rendered_pages"] += 1
        metrics["browser_requests"] += outcome.request_count
        metrics["browser_fulfilled_requests"] += outcome.fulfilled_count
        metrics["browser_blocked_requests"] += outcome.blocked_count
        metrics["browser_bytes_fulfilled"] += outcome.bytes_fulfilled
        if outcome.error or not outcome.html:
            metrics["render_failures"] += 1
            continue

        rendered_result = _rendered_fetch_result(outcome)
        rendered[canonical_url(outcome.final_url)] = rendered_result
        links, page = extract_rendered_links(outcome.html, base_url=outcome.final_url)
        self_classifications = classify_locator(
            url=outcome.final_url,
            surrounding_text=page["text"],
            page_title=page["title"],
            page_headings=page["headings"],
        )
        link_rows = [(outcome.final_url, "", page["text"], self_classifications)]
        link_rows.extend(
            (
                link.url,
                link.anchor_text,
                link.surrounding_text,
                classify_locator(
                    url=link.url,
                    anchor_text=link.anchor_text,
                    surrounding_text=link.surrounding_text,
                    page_title=page["title"],
                    page_headings=page["headings"],
                ),
            )
            for link in links
        )
        for candidate_url, anchor, context, classifications in link_rows:
            try:
                absolute = canonical_url(candidate_url)
            except ValueError:
                continue
            if not url_is_public_safe(absolute) or not classifications:
                continue
            on_official_domain = is_on_official_domain(absolute, official_domains)
            authority_state = (
                "official_domain" if on_official_domain else "first_party_attested_delegate"
            )
            for classification in classifications:
                source_type = str(classification["source_type"])
                if source_type not in source_types:
                    continue
                signal = source_locator_signal(
                    vendor_id=vendor_id,
                    url=absolute,
                    source_type=source_type,
                    score=int(classification["score"]) + (7 if on_official_domain else 2),
                    matched_terms=list(classification["matched_terms"]),
                    evidence_fields={
                        **dict(classification["evidence_fields"]),
                        "rendered_dom": ["playwright_intercepted_safe_fetch"],
                    },
                    provider="rendered_dom",
                    discovered_from=outcome.final_url,
                    authority_state=authority_state,
                    discovered_at=discovered_at,
                )
                prior = existing_signals.get(signal["signal_id"]) or rendered_signals.get(
                    signal["signal_id"]
                )
                if prior is None or int(signal["score"]) > int(prior["score"]):
                    rendered_signals[signal["signal_id"]] = signal
            path = urlparse(absolute).path.casefold()
            if (
                on_official_domain
                and absolute not in queued
                and absolute not in rendered
                and any(term in path for term in HIGH_VALUE_PATH_TERMS)
            ):
                queue.append(absolute)
                queued.add(absolute)

    official_rendered_urls = [
        str(row["candidate_url"])
        for row in rendered_signals.values()
        if row.get("authority_state") == "official_domain"
        and row.get("source_type_candidate") in source_types
    ]

    def render_aware_fetcher(url: str) -> FetchResult:
        try:
            key = canonical_url(url)
        except ValueError:
            return static_fetcher(url)
        return rendered.get(key) or static_fetcher(url)

    verified = verify_sitemap_locators(
        vendor,
        official_rendered_urls,
        fetcher=render_aware_fetcher,
        source_types=source_types,
        discovered_at=discovered_at,
        discovery_run_id=f"rendered-{vendor_id}-{discovered_at}",
        max_locators=max(1, len(official_rendered_urls)),
    )
    for candidate in verified.get("candidates", []) or []:
        candidate["discovery_method"] = "rendered_dom_locator_verification"
        evidence = candidate.get("evidence")
        if isinstance(evidence, dict):
            evidence["render_transport"] = "playwright_intercepted_safe_fetch"
    metrics["rendered_locator_signal_count"] = len(rendered_signals)
    metrics["rendered_verified_candidate_count"] = len(verified.get("candidates", []) or [])
    return {
        "signals": sorted(
            rendered_signals.values(),
            key=lambda row: (
                -int(row["score"]),
                str(row["source_type_candidate"]),
                str(row["candidate_url"]),
            ),
        ),
        "verification": verified,
        "metrics": metrics,
        "rendered_fetch_results": rendered,
    }


def _merge_unique(rows: list[dict[str, Any]], additions: list[dict[str, Any]], key: str) -> None:
    seen = {str(row.get(key) or "") for row in rows}
    for row in additions:
        identity = str(row.get(key) or "")
        if identity and identity not in seen:
            rows.append(row)
            seen.add(identity)


def run_rendered_source_shard(
    *,
    root: Path = ROOT,
    shard_index: int = 0,
    shard_count: int = 1,
    vendor_limit: int | None = None,
    source_types: tuple[str, ...] = DEFAULT_SOURCE_TYPES,
    fetch_timeout: float = 10.0,
    crawl_limits: CrawlLimits | None = None,
    render_limits: RenderLimits | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    crawl_limits = crawl_limits or CrawlLimits()
    render_limits = render_limits or RenderLimits()
    report = run_source_shard(
        root=root,
        shard_index=shard_index,
        shard_count=shard_count,
        vendor_limit=vendor_limit,
        source_types=source_types,
        fetch_timeout=fetch_timeout,
        limits=crawl_limits,
        max_locators_per_vendor=crawl_limits.max_locator_candidates,
        generated_at=generated_at,
    )
    vendors_by_id = {
        str(vendor["vendor_id"]): vendor
        for path in selected_vendor_paths(
            root=root,
            shard_index=shard_index,
            shard_count=shard_count,
            vendor_limit=vendor_limit,
        )
        for vendor in [load_yaml(path)]
    }
    results_by_id = {
        str(row.get("vendor_id") or ""): row for row in report.get("vendors", []) or []
    }
    totals: dict[str, int] = {
        "javascript_fallback_eligible_pages": 0,
        "rendered_pages": 0,
        "render_failures": 0,
        "browser_requests": 0,
        "browser_fulfilled_requests": 0,
        "browser_blocked_requests": 0,
        "browser_bytes_fulfilled": 0,
        "rendered_locator_signal_count": 0,
        "rendered_verified_candidate_count": 0,
    }
    for frontier in report.get("source_frontier_reports", []) or []:
        vendor_id = str(frontier.get("vendor_id") or "")
        vendor = vendors_by_id.get(vendor_id)
        vendor_result = results_by_id.get(vendor_id)
        if not vendor or not vendor_result:
            continue
        missing_types = _missing_source_types(vendor_id, source_types, root)
        if not missing_types:
            continue
        static_fetcher = safe_discovery_fetcher(vendor, fetch_timeout)
        try:
            browser_fetcher = _safe_browser_fetcher(
                [str(value) for value in vendor.get("official_domains", []) or [] if value],
                fetch_timeout=fetch_timeout,
                limits=render_limits,
            )
        except (SafeFetchError, ValueError):
            continue
        rendered = augment_vendor_with_rendered_discovery(
            vendor=vendor,
            frontier=frontier,
            static_fetcher=static_fetcher,
            browser_fetcher=browser_fetcher,
            source_types=missing_types,
            discovered_at=generated_at,
            limits=render_limits,
        )
        _merge_unique(
            frontier.setdefault("source_locator_signals", []),
            rendered["signals"],
            "signal_id",
        )
        frontier["summary"]["locator_signal_count"] = len(frontier["source_locator_signals"])
        frontier["rendered_discovery"] = rendered["metrics"]
        verified = rendered["verification"]
        _merge_unique(
            vendor_result.setdefault("candidates", []),
            list(verified.get("candidates", []) or []),
            "candidate_source_id",
        )
        _merge_unique(
            vendor_result.setdefault("observations", []),
            list(verified.get("observations", []) or []),
            "candidate_url",
        )
        _merge_unique(
            vendor_result.setdefault("discovery_events", []),
            list(verified.get("discovery_events", []) or []),
            "discovery_event_id",
        )
        vendor_result["mesh_summary"] = frontier.get("summary") or {}
        vendor_result["delegated_locator_signals"] = [
            row
            for row in frontier.get("source_locator_signals", []) or []
            if row.get("authority_state") == "first_party_attested_delegate"
        ]
        for key in totals:
            totals[key] += int(rendered["metrics"].get(key) or 0)

    report["policy_version"] = POLICY_VERSION
    report.setdefault("posture", {}).update(
        {
            "javascript_rendering_fallback": True,
            "browser_direct_network_access": False,
            "browser_requests_use_safe_fetch_boundary": True,
            "rendered_signals_are_catalog_facts": False,
        }
    )
    report.setdefault("summary", {}).update(totals)
    report["summary"]["candidate_sources_written_or_reported"] = sum(
        len(row.get("candidates", []) or []) for row in report.get("vendors", []) or []
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-rendered-discovery-runner")
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--vendor-limit", type=int)
    parser.add_argument("--source-types")
    parser.add_argument("--fetch-timeout", type=float, default=10.0)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--max-total-requests", type=int, default=750)
    parser.add_argument("--max-links-per-page", type=int, default=750)
    parser.add_argument("--max-locators-per-vendor", type=int, default=2_000)
    parser.add_argument("--max-render-pages-per-vendor", type=int, default=8)
    parser.add_argument("--max-render-requests-per-page", type=int, default=80)
    parser.add_argument("--max-render-bytes-per-page", type=int, default=8_000_000)
    parser.add_argument("--render-timeout-ms", type=int, default=12_000)
    parser.add_argument("--render-settle-ms", type=int, default=750)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_rendered_source_shard(
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        vendor_limit=args.vendor_limit,
        source_types=parse_source_types(args.source_types),
        fetch_timeout=args.fetch_timeout,
        crawl_limits=CrawlLimits(
            max_pages=args.max_pages,
            max_total_requests=args.max_total_requests,
            max_links_per_page=args.max_links_per_page,
            max_locator_candidates=args.max_locators_per_vendor,
        ),
        render_limits=RenderLimits(
            max_pages_per_vendor=args.max_render_pages_per_vendor,
            max_requests_per_page=args.max_render_requests_per_page,
            max_bytes_per_page=args.max_render_bytes_per_page,
            navigation_timeout_ms=args.render_timeout_ms,
            settle_time_ms=args.render_settle_ms,
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
