"""Tier A: bounded sitemap/robots discovery — security and bounds matrix.

The acceptance invariant: a sitemap entry can create a candidate but can never,
by itself, satisfy identity, authority, materialization, or promotion gates.
"""

import gzip

import pytest
from tools.openva import sitemap_discovery as sd
from tools.openva.sitemap_discovery import (
    Bounds,
    FetchResult,
    SitemapDiscoveryError,
    decode_sitemap_bytes,
    discover_sitemap_candidates,
    parse_sitemap_xml,
)

DOMAINS = ["vendor.example"]
RUN = {"discovery_run_id": "run-1", "discovered_at": "2026-06-15T00:00:00Z", "vendor_id": "vendor"}
BOUNDS = Bounds(relevance_terms=("trust", "security", "privacy", "dpa", "subprocessor"))


def _urlset(*urls: str) -> bytes:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'.encode()


def _index(*sitemaps: str) -> bytes:
    locs = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in sitemaps)
    return f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</sitemapindex>'.encode()


def fetcher(mapping: dict, *, redirects: dict | None = None):
    redirects = redirects or {}

    def fetch(url: str) -> FetchResult:
        spec = mapping.get(url)
        if spec is None:
            return FetchResult(status=404, final_url=url, body=b"")
        return FetchResult(
            status=spec.get("status", 200),
            final_url=spec.get("final_url", url),
            body=spec.get("body", b""),
            content_encoding=spec.get("content_encoding"),
            redirects=spec.get("redirects", 0),
        )

    return fetch


def run(mapping, *, bounds=BOUNDS):
    return discover_sitemap_candidates(DOMAINS, fetcher(mapping), bounds=bounds, **RUN)


def test_sitemap_creates_zero_weight_candidate():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset(
        "https://vendor.example/trust", "https://vendor.example/security/dpa", "https://vendor.example/blog/post",
    )}})
    urls = {c["url"] for c in out.candidates}
    assert "https://vendor.example/trust" in urls
    assert "https://vendor.example/security/dpa" in urls
    assert "https://vendor.example/blog/post" not in urls
    event = next(e for e in out.events if e["candidate_url"] == "https://vendor.example/trust")
    assert event["origin"] == "sitemap"
    assert event["classification"] == "unverified_candidate"
    assert "authority_state:unverified_candidate" in event["reason_codes"]
    assert "content_state:not_fetched" in event["reason_codes"]
    assert "promotion_weight:none" in event["reason_codes"]
    assert event["not_advice"] is True


def test_xxe_payload_is_rejected():
    xxe = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset><url><loc>&x;</loc></url></urlset>'
    with pytest.raises(SitemapDiscoveryError, match="xml_dtd_or_entity_forbidden"):
        parse_sitemap_xml(xxe)
    out = run({"https://vendor.example/sitemap.xml": {"body": xxe}})
    assert any(r["reason"] == "xml_dtd_or_entity_forbidden" for r in out.rejected)
    assert out.candidates == []


def test_malformed_xml_is_rejected():
    out = run({"https://vendor.example/sitemap.xml": {"body": b"<urlset><url><loc>oops"}})
    assert any("malformed_sitemap_xml" in r["reason"] for r in out.rejected)


def test_gzip_decompression_bomb_is_bounded():
    payload = gzip.compress(b"A" * 100_000)
    tiny = Bounds(max_decompressed_bytes=1000, relevance_terms=("trust",))
    with pytest.raises(SitemapDiscoveryError, match="decompressed_sitemap_too_large"):
        decode_sitemap_bytes(FetchResult(200, "https://vendor.example/s.xml.gz", payload, "gzip"), tiny)


def test_compressed_byte_limit_is_enforced_before_decompression():
    payload = gzip.compress(b"A" * 10_000)
    tiny = Bounds(max_compressed_bytes=10, relevance_terms=("trust",))
    with pytest.raises(SitemapDiscoveryError, match="compressed_sitemap_too_large"):
        decode_sitemap_bytes(FetchResult(200, "https://vendor.example/s.xml.gz", payload, "gzip"), tiny)


def test_xml_gz_handling():
    body = gzip.compress(_urlset("https://vendor.example/trust"))
    out = run({"https://vendor.example/sitemap.xml": {"body": body, "final_url": "https://vendor.example/sitemap.xml.gz"}})
    assert any(c["url"] == "https://vendor.example/trust" for c in out.candidates)


def test_cyclic_sitemap_index_terminates():
    a = "https://vendor.example/sitemap.xml"
    b = "https://vendor.example/b.xml"
    out = run({a: {"body": _index(b)}, b: {"body": _index(a)}})
    assert out.candidates == []


def test_max_index_depth_enforced():
    a = "https://vendor.example/sitemap.xml"
    b = "https://vendor.example/b.xml"
    c = "https://vendor.example/c.xml"
    d = "https://vendor.example/d.xml"
    bounds = Bounds(max_sitemap_index_depth=1, relevance_terms=("trust",))
    out = run({a: {"body": _index(b)}, b: {"body": _index(c)}, c: {"body": _index(d)},
               d: {"body": _urlset("https://vendor.example/trust")}}, bounds=bounds)
    assert any(r["reason"] == "sitemap_index_depth_exceeded" for r in out.rejected)


def test_max_sitemap_files_enforced():
    children = [f"https://vendor.example/s{i}.xml" for i in range(5)]
    mapping = {"https://vendor.example/sitemap.xml": {"body": _index(*children)}}
    for child in children:
        mapping[child] = {"body": _urlset(f"https://vendor.example/trust{children.index(child)}")}
    bounds = Bounds(max_sitemap_files=2, relevance_terms=("trust",))
    out = run(mapping, bounds=bounds)
    assert any(r["reason"] == "sitemap_file_count_exceeded" for r in out.rejected)


def test_max_candidate_count_capped():
    urls = [f"https://vendor.example/trust/{i}" for i in range(50)]
    bounds = Bounds(max_candidate_urls=5, relevance_terms=("trust",))
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset(*urls)}}, bounds=bounds)
    assert len(out.candidates) == 5


def test_off_authority_sitemap_rejected():
    out = run({"https://vendor.example/sitemap.xml": {"body": _index("https://evil.test/s.xml")}})
    assert any(r["reason"] == "off_authority_sitemap" for r in out.rejected)


def test_off_authority_candidate_url_rejected():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset(
        "https://vendor.example/trust", "https://evil.test/trust",
    )}})
    assert any(r["reason"] == "off_authority_candidate_url" for r in out.rejected)
    assert all("evil.test" not in c["url"] for c in out.candidates)


def test_unsafe_candidate_url_rejected():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset("http://127.0.0.1/trust")}})
    assert any(r["reason"] in ("unsafe_candidate_url", "off_authority_candidate_url") for r in out.rejected)


def test_sitemap_redirect_off_authority_rejected():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset("https://vendor.example/trust"),
                                                       "final_url": "https://evil.test/sitemap.xml"}})
    assert any("off_authority" in r["reason"] for r in out.rejected)


def test_redirect_overflow_rejected():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset("https://vendor.example/trust"), "redirects": 99}})
    assert any(r["reason"] == "sitemap_redirect_overflow" for r in out.rejected)


def test_www_apex_is_same_authority():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset("https://www.vendor.example/trust")}})
    assert any(c["url"] == "https://www.vendor.example/trust" for c in out.candidates)


def test_duplicate_url_normalization_deduplicates():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset(
        "https://vendor.example/trust", "https://vendor.example/trust/", "https://VENDOR.example/trust",
    )}})
    trust = [c for c in out.candidates if c["url"].endswith("/trust")]
    assert len(trust) == 1


def test_deterministic_ordering():
    urls = ["https://vendor.example/trust/c", "https://vendor.example/trust/a", "https://vendor.example/trust/b"]
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset(*urls)}})
    got = [c["url"] for c in out.candidates]
    assert got == sorted(got)


def test_irrelevant_large_sitemap_yields_nothing():
    urls = [f"https://vendor.example/products/{i}" for i in range(100)]
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset(*urls)}})
    assert out.candidates == []


def test_robots_disallow_suppresses_discovery():
    robots = b"User-agent: *\nDisallow: /trust\n"
    out = run({
        "https://vendor.example/robots.txt": {"body": robots},
        "https://vendor.example/sitemap.xml": {"body": _urlset("https://vendor.example/trust")},
    })
    assert any(r["reason"] == "discovery_suppressed_by_robots" for r in out.rejected)
    assert out.candidates == []


def test_robots_unavailable_still_discovers():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset("https://vendor.example/trust")}})
    assert out.robots_state == "unavailable"
    assert any(c["url"] == "https://vendor.example/trust" for c in out.candidates)


def test_sitemap_declared_through_robots_is_followed():
    robots = b"User-agent: *\nAllow: /\nSitemap: https://vendor.example/declared.xml\n"
    out = run({
        "https://vendor.example/robots.txt": {"body": robots},
        "https://vendor.example/declared.xml": {"body": _urlset("https://vendor.example/security")},
    })
    assert any(c["url"] == "https://vendor.example/security" for c in out.candidates)


def _robots_then_sitemaps(robots_behavior):
    requested: list[str] = []

    def fetch(url: str) -> FetchResult:
        requested.append(url)
        if url.endswith("/robots.txt"):
            return robots_behavior(url)
        return FetchResult(status=200, final_url=url, body=_urlset("https://vendor.example/trust"))

    fetch.requested = requested  # type: ignore[attr-defined]
    return fetch


def _raising_robots(message):
    def fetch(url: str) -> FetchResult:
        fetch.requested.append(url)  # type: ignore[attr-defined]
        if url.endswith("/robots.txt"):
            raise SitemapDiscoveryError(message)
        return FetchResult(status=200, final_url=url, body=_urlset("https://vendor.example/trust"))

    fetch.requested = []  # type: ignore[attr-defined]
    return fetch


def _discover(fetch):
    return discover_sitemap_candidates(DOMAINS, fetch, bounds=BOUNDS, **RUN)


def test_robots_5xx_is_unreachable_and_suppresses_all_fetching():
    fetch = _robots_then_sitemaps(lambda url: FetchResult(status=503, final_url=url, body=b""))
    out = _discover(fetch)
    assert out.robots_state == "unreachable"
    assert out.robots_reason == "robots_http_503"
    assert out.candidates == []
    assert out.sitemaps_attempted == 0
    assert all(u.endswith("/robots.txt") for u in fetch.requested)


def test_robots_transport_failure_is_unreachable_and_suppresses_all():
    fetch = _raising_robots("transport_error:TimeoutError")
    out = _discover(fetch)
    assert out.robots_state == "unreachable"
    assert out.robots_reason == "robots_transport_error"
    assert out.candidates == []
    assert all(u.endswith("/robots.txt") for u in fetch.requested)


def test_robots_timeout_is_unreachable_and_suppresses_all():
    fetch = _raising_robots("request_deadline_exceeded")
    out = _discover(fetch)
    assert out.robots_state == "unreachable"
    assert out.robots_reason == "robots_timeout"
    assert out.candidates == []
    assert all(u.endswith("/robots.txt") for u in fetch.requested)


def test_robots_redirect_overflow_is_distinct_from_transport_failure():
    fetch = _raising_robots("redirect_overflow")
    out = _discover(fetch)
    assert out.robots_state == "unreachable"
    assert out.robots_reason == "robots_redirect_overflow"
    assert out.candidates == []


def test_robots_unparseable_is_malformed_restrictive_and_suppresses_all():
    fetch = _robots_then_sitemaps(
        lambda url: FetchResult(status=200, final_url=url, body=b"garbage: nonsense\nfoo: bar\n")
    )
    out = _discover(fetch)
    assert out.robots_state == "malformed_restrictive"
    assert out.candidates == []
    assert out.sitemaps_attempted == 0
    assert all(u.endswith("/robots.txt") for u in fetch.requested)


def test_robots_4xx_absent_proceeds_with_no_restriction():
    fetch = _robots_then_sitemaps(lambda url: FetchResult(status=403, final_url=url, body=b""))
    out = _discover(fetch)
    assert out.robots_state == "unavailable"
    assert any(c["url"] == "https://vendor.example/trust" for c in out.candidates)


def test_robots_empty_200_is_success_and_proceeds():
    fetch = _robots_then_sitemaps(lambda url: FetchResult(status=200, final_url=url, body=b""))
    out = _discover(fetch)
    assert out.robots_state == "success"
    assert any(c["url"] == "https://vendor.example/trust" for c in out.candidates)


def test_malformed_locator_is_a_bounded_rejection_and_later_locators_still_process():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset(
        "https://[:::]/trust",
        "https://vendor.example:99999/security",
        "https://vendor.example/security/dpa",
    )}})
    urls = {c["url"] for c in out.candidates}
    assert "https://vendor.example/security/dpa" in urls
    assert all("[:::]" not in u and ":99999" not in u for u in urls)
    reasons = {r["reason"] for r in out.rejected}
    assert reasons & {"unsafe_candidate_url", "malformed_candidate_url"}


def test_outcome_records_parser_id_and_sitemaps_attempted():
    out = run({"https://vendor.example/sitemap.xml": {"body": _urlset("https://vendor.example/trust")}})
    assert out.robots_parser == "openva-robots.v4"
    assert out.sitemaps_attempted == 2
