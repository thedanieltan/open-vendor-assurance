"""Tier A: bounded, report-only sitemap and robots discovery.

Discovery may be opportunistic; catalog admission stays evidentiary. This lane
inspects a vendor's OWN official domain(s) for assurance-related locators via
robots.txt and sitemaps, under hard bounds, and emits zero-weight discovery
events. A sitemap entry can create a candidate but can never, by itself, satisfy
identity, authority, materialization, or promotion gates.

Security boundary (sitemaps are untrusted XML/data):
- XML is parsed with DTDs and entities forbidden (no XXE, no entity-expansion
  bombs); the parser never resolves external entities or retrieves over the
  network.
- gzip payloads are size-bounded both compressed and while decompressing
  (incremental cap, never decompress-all-then-check).
- every URL (sitemaps, candidates, redirects) passes url_safety, which rejects
  private / loopback / link-local targets (SSRF).
- "same authority" is the repository's official-domain rule; off-authority
  sitemaps and URLs are recorded as rejected discovery metadata, never
  candidates, without strong delegation proof.
- robots.txt is operating policy, not evidence: a disallow suppresses fetching
  through this lane; it never implies private/invalid/gated/absent.

The whole candidate set is bounded BEFORE any candidate page is fetched.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import yaml

from tools.openva.indexes import ROOT
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.source_authority import is_on_official_domain
from tools.openva.url_safety import validate_url_safety

USER_AGENT = "OpenVA-Discovery"
BOUNDS_PATH = ROOT / "config" / "discovery-bounds.yaml"
POLICY_VERSION = "tier-a-sitemap-discovery.v1"

# A DTD or any entity declaration is forbidden outright: this kills XXE and
# billion-laughs before the XML parser ever expands anything.
_FORBIDDEN_XML = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
_GZIP_MAGIC = b"\x1f\x8b"
_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class SitemapDiscoveryError(Exception):
    """Bounded-discovery failure (malformed input, exceeded bound, unsafe)."""


@dataclass(frozen=True)
class Bounds:
    max_sitemap_index_depth: int = 2
    max_sitemap_files: int = 20
    max_candidate_urls: int = 200
    max_compressed_bytes: int = 5_000_000
    max_decompressed_bytes: int = 50_000_000
    max_request_seconds: float = 20.0
    max_redirects: int = 5
    relevance_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class FetchResult:
    status: int
    final_url: str
    body: bytes
    content_encoding: str | None = None
    redirects: int = 0


# A fetcher returns a FetchResult or raises. It is injected so this module never
# performs network I/O in tests, and so the real fetcher can enforce timeouts
# and compressed-byte limits at the socket.
Fetcher = Callable[[str], FetchResult]


@dataclass
class DiscoveryOutcome:
    candidates: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    robots_state: str = "unavailable"
    events: list[dict[str, Any]] = field(default_factory=list)


def load_bounds(path: Path = BOUNDS_PATH) -> Bounds:
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("sitemap_discovery") or {}
    return Bounds(
        max_sitemap_index_depth=int(raw.get("max_sitemap_index_depth", 2)),
        max_sitemap_files=int(raw.get("max_sitemap_files", 20)),
        max_candidate_urls=int(raw.get("max_candidate_urls", 200)),
        max_compressed_bytes=int(raw.get("max_compressed_bytes", 5_000_000)),
        max_decompressed_bytes=int(raw.get("max_decompressed_bytes", 50_000_000)),
        max_request_seconds=float(raw.get("max_request_seconds", 20)),
        max_redirects=int(raw.get("max_redirects", 5)),
        relevance_terms=tuple(raw.get("relevance_terms", []) or []),
    )


# --- safe bytes -> XML ----------------------------------------------------


def decode_sitemap_bytes(result: FetchResult, bounds: Bounds) -> bytes:
    """Return the (possibly gzip-decompressed) sitemap bytes, size-bounded.

    The compressed limit is checked before decompression; the decompressed
    limit is enforced incrementally so a small gzip bomb can never expand past
    the cap (we never decompress everything and check afterwards).
    """
    body = result.body
    is_gzip = (
        (result.content_encoding or "").lower() == "gzip"
        or result.final_url.lower().endswith(".gz")
        or body[:2] == _GZIP_MAGIC
    )
    if not is_gzip:
        if len(body) > bounds.max_decompressed_bytes:
            raise SitemapDiscoveryError("sitemap_too_large")
        return body
    if len(body) > bounds.max_compressed_bytes:
        raise SitemapDiscoveryError("compressed_sitemap_too_large")
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = bytearray()
    limit = bounds.max_decompressed_bytes
    for offset in range(0, len(body), 65536):
        chunk = decompressor.decompress(body[offset : offset + 65536], limit - len(out) + 1)
        out += chunk
        if len(out) > limit:
            raise SitemapDiscoveryError("decompressed_sitemap_too_large")
    out += decompressor.flush()
    if len(out) > limit:
        raise SitemapDiscoveryError("decompressed_sitemap_too_large")
    return bytes(out)


def parse_sitemap_xml(data: bytes) -> ET.Element:
    if _FORBIDDEN_XML.search(data):
        raise SitemapDiscoveryError("xml_dtd_or_entity_forbidden")
    try:
        # expat via ElementTree: no external entity resolution, no network.
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise SitemapDiscoveryError(f"malformed_sitemap_xml:{exc}") from exc


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def sitemap_kind(root: ET.Element) -> str:
    name = _localname(root.tag)
    if name == "sitemapindex":
        return "index"
    if name == "urlset":
        return "urlset"
    return "unknown"


def _locs(root: ET.Element) -> list[str]:
    return [
        (el.text or "").strip()
        for el in root.iter()
        if _localname(el.tag) == "loc" and (el.text or "").strip()
    ]


# --- authority & safety ---------------------------------------------------


def url_is_safe(url: str) -> bool:
    return not validate_url_safety(url, resolve_dns=False)


def normalize_candidate_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # Drop fragment; keep query (it can distinguish public assurance pages).
    return f"{parts.scheme.lower()}://{host}{path}" + (f"?{parts.query}" if parts.query else "")


# --- the bounded pipeline -------------------------------------------------


def _gather_locs(
    sitemap_url: str,
    official_domains: list[str],
    fetcher: Fetcher,
    bounds: Bounds,
    *,
    depth: int,
    visited: set[str],
    files_fetched: list[int],
    rejected: list[dict[str, str]],
) -> list[tuple[str, str]]:
    """Walk a sitemap (or sitemap index) within bounds, returning (loc, found_in)."""
    if depth > bounds.max_sitemap_index_depth:
        rejected.append({"url": sitemap_url, "reason": "sitemap_index_depth_exceeded"})
        return []
    if sitemap_url in visited:  # cyclic index guard
        return []
    visited.add(sitemap_url)
    if files_fetched[0] >= bounds.max_sitemap_files:
        rejected.append({"url": sitemap_url, "reason": "sitemap_file_count_exceeded"})
        return []
    if not is_on_official_domain(sitemap_url, official_domains):
        rejected.append({"url": sitemap_url, "reason": "off_authority_sitemap"})
        return []
    if not url_is_safe(sitemap_url):
        rejected.append({"url": sitemap_url, "reason": "unsafe_sitemap_url"})
        return []

    result = fetcher(sitemap_url)
    files_fetched[0] += 1
    if result.redirects > bounds.max_redirects:
        rejected.append({"url": sitemap_url, "reason": "sitemap_redirect_overflow"})
        return []
    if not is_on_official_domain(result.final_url, official_domains) or not url_is_safe(result.final_url):
        rejected.append({"url": sitemap_url, "reason": "sitemap_redirect_off_authority_or_unsafe"})
        return []
    if result.status != 200:
        rejected.append({"url": sitemap_url, "reason": f"sitemap_http_{result.status}"})
        return []

    root = parse_sitemap_xml(decode_sitemap_bytes(result, bounds))
    kind = sitemap_kind(root)
    if kind == "index":
        out: list[tuple[str, str]] = []
        for child in _locs(root):
            out.extend(
                _gather_locs(
                    child, official_domains, fetcher, bounds,
                    depth=depth + 1, visited=visited, files_fetched=files_fetched, rejected=rejected,
                )
            )
        return out
    if kind == "urlset":
        return [(loc, sitemap_url) for loc in _locs(root)]
    rejected.append({"url": sitemap_url, "reason": "unknown_sitemap_kind"})
    return []


def _relevant(url: str, terms: tuple[str, ...]) -> bool:
    low = url.lower()
    return any(term in low for term in terms)


def discover_sitemap_candidates(
    official_domains: list[str],
    fetcher: Fetcher,
    *,
    bounds: Bounds | None = None,
    discovery_run_id: str,
    discovered_at: str,
    vendor_id: str | None = None,
) -> DiscoveryOutcome:
    """Bounded robots+sitemap discovery for a vendor's own official domain(s).

    Deterministic order: robots -> sitemap inputs -> parse under bounds ->
    normalize -> reject unsafe/off-authority -> dedup -> relevance-filter ->
    sort -> cap -> (candidate fetch happens downstream, not here).
    """
    bounds = bounds or load_bounds()
    outcome = DiscoveryOutcome()
    if not official_domains:
        return outcome
    base = f"https://{official_domains[0].strip().lower().rstrip('.')}/"

    robots_state, sitemap_urls, robots = _read_robots(base, fetcher)
    outcome.robots_state = robots_state

    # Default sitemap locations plus any declared in robots.
    candidate_sitemaps = [urljoin(base, "/sitemap.xml"), urljoin(base, "/sitemap_index.xml")]
    candidate_sitemaps.extend(sitemap_urls)

    visited: set[str] = set()
    files_fetched = [0]
    locs: list[tuple[str, str]] = []
    for sitemap_url in candidate_sitemaps:
        # robots is operating policy: do not fetch a disallowed sitemap path.
        if robots is not None and not robots.can_fetch(USER_AGENT, sitemap_url):
            outcome.rejected.append({"url": sitemap_url, "reason": "discovery_suppressed_by_robots"})
            continue
        try:
            locs.extend(
                _gather_locs(
                    sitemap_url, official_domains, fetcher, bounds,
                    depth=0, visited=visited, files_fetched=files_fetched, rejected=outcome.rejected,
                )
            )
        except SitemapDiscoveryError as exc:
            outcome.rejected.append({"url": sitemap_url, "reason": str(exc)})

    # normalize -> reject unsafe/off-authority -> dedup -> relevance-filter
    seen: set[str] = set()
    found_in: dict[str, str] = {}
    for loc, sitemap_url in locs:
        url = normalize_candidate_url(loc)
        if url in seen:
            continue
        if not url_is_safe(url):
            outcome.rejected.append({"url": loc, "reason": "unsafe_candidate_url"})
            continue
        if not is_on_official_domain(url, official_domains):
            outcome.rejected.append({"url": loc, "reason": "off_authority_candidate_url"})
            continue
        if robots is not None and not robots.can_fetch(USER_AGENT, url):
            outcome.rejected.append({"url": url, "reason": "discovery_suppressed_by_robots"})
            continue
        if bounds.relevance_terms and not _relevant(url, bounds.relevance_terms):
            continue
        seen.add(url)
        found_in[url] = sitemap_url

    # deterministic order then cap
    ordered = sorted(seen)[: bounds.max_candidate_urls]
    for url in ordered:
        outcome.candidates.append({"url": url, "discovered_from": found_in[url]})
        outcome.events.append(
            _discovery_event(
                url=url,
                discovered_from=found_in[url],
                vendor_id=vendor_id,
                discovery_run_id=discovery_run_id,
                discovered_at=discovered_at,
            )
        )
    return outcome


def _read_robots(base: str, fetcher: Fetcher) -> tuple[str, list[str], robotparser.RobotFileParser | None]:
    url = urljoin(base, "/robots.txt")
    try:
        result = fetcher(url)
    except Exception:
        return "unavailable", [], None
    if result.status != 200 or not result.body:
        return "unavailable", [], None
    robots = robotparser.RobotFileParser()
    robots.parse(result.body.decode("utf-8", "replace").splitlines())
    sitemaps = list(robots.site_maps() or [])
    # "restrictive" if it disallows the root for our agent; still operating policy.
    state = "restrictive" if not robots.can_fetch(USER_AGENT, base) else "found"
    return state, sitemaps, robots


def _discovery_event(
    *,
    url: str,
    discovered_from: str,
    vendor_id: str | None,
    discovery_run_id: str,
    discovered_at: str,
) -> dict[str, Any]:
    """A zero-weight discovery event in the existing ledger shape.

    Records where the locator was found; asserts no authority and no content
    verification. reason_codes carry the unverified/not-fetched/no-weight state.
    """
    evidence = {
        "candidate_url": url,
        "discovered_from": discovered_from,
        "vendor_id": vendor_id,
        "authority_state": "unverified_candidate",
        "content_state": "not_fetched",
        "promotion_weight": "none",
    }
    evidence_digest = sha256_bytes(canonical_json(evidence))
    return {
        "schema_version": "0.1.0",
        "discovery_event_id": sha256_bytes(canonical_json([url, discovery_run_id]))[len("sha256:") : len("sha256:") + 32],
        "candidate_id": f"cand-sitemap-{sha256_bytes(canonical_json(url))[len('sha256:'): len('sha256:') + 12]}",
        "origin": "sitemap",
        "candidate_url": url,
        "evidence_digest": evidence_digest,
        "classification": "unverified_candidate",
        "reason_codes": [
            "discovery_method:sitemap",
            f"discovered_from:{discovered_from}",
            "authority_state:unverified_candidate",
            "content_state:not_fetched",
            "promotion_weight:none",
        ],
        "discovery_run_id": discovery_run_id,
        "policy_version": POLICY_VERSION,
        "discovered_at": discovered_at,
        "not_advice": True,
    }
