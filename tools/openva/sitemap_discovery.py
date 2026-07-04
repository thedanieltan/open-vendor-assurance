"""Bounded, report-only sitemap and robots discovery.

Discovery inspects a vendor's own official domains and emits zero-weight
candidates. It respects robots rules and the most-specific Crawl-delay before
issuing each post-robots request. Admission remains evidentiary and separate.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import yaml

from tools.openva.indexes import ROOT
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.robots_policy import PARSER_ID as ROBOTS_PARSER_ID
from tools.openva.robots_policy import RobotsPolicy
from tools.openva.source_authority import is_on_official_domain
from tools.openva.url_safety import validate_url_safety

USER_AGENT = "OpenVA-Discovery"
BOUNDS_PATH = ROOT / "config" / "discovery-bounds.yaml"
POLICY_VERSION = "tier-a-sitemap-discovery.v1"
_FORBIDDEN_XML = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
_GZIP_MAGIC = b"\x1f\x8b"


class SitemapDiscoveryError(Exception):
    """Bounded-discovery failure."""


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
    headers: dict[str, str] | None = None


Fetcher = Callable[[str], FetchResult]

ROBOTS_SUCCESS = "success"
ROBOTS_UNAVAILABLE = "unavailable"
ROBOTS_UNREACHABLE = "unreachable"
ROBOTS_RESTRICTIVE = "restrictive"
ROBOTS_MALFORMED_RESTRICTIVE = "malformed_restrictive"
_ROBOTS_SUPPRESS_ALL = frozenset({ROBOTS_UNREACHABLE, ROBOTS_MALFORMED_RESTRICTIVE})


@dataclass(frozen=True)
class RobotsAccess:
    state: str
    reason_code: str
    sitemaps: tuple[str, ...]
    policy: RobotsPolicy | None

    @property
    def suppress_all(self) -> bool:
        return self.state in _ROBOTS_SUPPRESS_ALL


@dataclass
class DiscoveryOutcome:
    candidates: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    robots_state: str = ROBOTS_UNAVAILABLE
    robots_reason: str = ""
    robots_parser: str = ROBOTS_PARSER_ID
    sitemaps_attempted: int = 0
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


def decode_sitemap_bytes(result: FetchResult, bounds: Bounds) -> bytes:
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
        out += decompressor.decompress(body[offset : offset + 65536], limit - len(out) + 1)
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
        (element.text or "").strip()
        for element in root.iter()
        if _localname(element.tag) == "loc" and (element.text or "").strip()
    ]


def url_is_safe(url: str) -> bool:
    return not validate_url_safety(url, resolve_dns=False)


def normalize_candidate_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{parts.scheme.lower()}://{host}{path}" + (f"?{parts.query}" if parts.query else "")


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
    if depth > bounds.max_sitemap_index_depth:
        rejected.append({"url": sitemap_url, "reason": "sitemap_index_depth_exceeded"})
        return []
    if sitemap_url in visited:
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
        output: list[tuple[str, str]] = []
        for child in _locs(root):
            output.extend(
                _gather_locs(
                    child,
                    official_domains,
                    fetcher,
                    bounds,
                    depth=depth + 1,
                    visited=visited,
                    files_fetched=files_fetched,
                    rejected=rejected,
                )
            )
        return output
    if kind == "urlset":
        return [(location, sitemap_url) for location in _locs(root)]
    rejected.append({"url": sitemap_url, "reason": "unknown_sitemap_kind"})
    return []


def _relevant(url: str, terms: tuple[str, ...]) -> bool:
    low = url.lower()
    return any(term in low for term in terms)


def _paced_fetcher(
    fetcher: Fetcher,
    delay: float | None,
    *,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> Fetcher:
    if delay is None or delay <= 0:
        return fetcher
    next_allowed = [clock() + delay]

    def paced(url: str) -> FetchResult:
        wait = next_allowed[0] - clock()
        if wait > 0:
            sleeper(wait)
        result = fetcher(url)
        next_allowed[0] = clock() + delay
        return result

    return paced


def discover_sitemap_candidates(
    official_domains: list[str],
    fetcher: Fetcher,
    *,
    bounds: Bounds | None = None,
    discovery_run_id: str,
    discovered_at: str,
    vendor_id: str | None = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> DiscoveryOutcome:
    bounds = bounds or load_bounds()
    outcome = DiscoveryOutcome()
    if not official_domains:
        return outcome
    base = f"https://{official_domains[0].strip().lower().rstrip('.')}/"

    access = _read_robots(base, fetcher)
    outcome.robots_state = access.state
    outcome.robots_reason = access.reason_code
    robots = access.policy
    if robots is not None:
        outcome.robots_parser = robots.parser_id
    if access.suppress_all:
        outcome.rejected.append({"url": base, "reason": f"discovery_suppressed:{access.reason_code}"})
        return outcome

    effective_fetcher = _paced_fetcher(
        fetcher,
        robots.crawl_delay(USER_AGENT) if robots is not None else None,
        clock=clock or time.monotonic,
        sleeper=sleeper or time.sleep,
    )
    candidate_sitemaps = [urljoin(base, "/sitemap.xml"), urljoin(base, "/sitemap_index.xml")]
    candidate_sitemaps.extend(access.sitemaps)

    visited: set[str] = set()
    files_fetched = [0]
    locations: list[tuple[str, str]] = []
    for sitemap_url in candidate_sitemaps:
        if robots is not None and not robots.can_fetch(USER_AGENT, sitemap_url):
            outcome.rejected.append({"url": sitemap_url, "reason": "discovery_suppressed_by_robots"})
            continue
        try:
            locations.extend(
                _gather_locs(
                    sitemap_url,
                    official_domains,
                    effective_fetcher,
                    bounds,
                    depth=0,
                    visited=visited,
                    files_fetched=files_fetched,
                    rejected=outcome.rejected,
                )
            )
        except SitemapDiscoveryError as exc:
            outcome.rejected.append({"url": sitemap_url, "reason": str(exc)})
        except ValueError:
            outcome.rejected.append({"url": sitemap_url, "reason": "malformed_sitemap_url"})

    seen: set[str] = set()
    found_in: dict[str, str] = {}
    for location, sitemap_url in locations:
        try:
            url = normalize_candidate_url(location)
            if url in seen:
                continue
            if not url_is_safe(url):
                outcome.rejected.append({"url": location, "reason": "unsafe_candidate_url"})
                continue
            if not is_on_official_domain(url, official_domains):
                outcome.rejected.append({"url": location, "reason": "off_authority_candidate_url"})
                continue
        except ValueError:
            outcome.rejected.append({"url": location, "reason": "malformed_candidate_url"})
            continue
        if robots is not None and not robots.can_fetch(USER_AGENT, url):
            outcome.rejected.append({"url": url, "reason": "discovery_suppressed_by_robots"})
            continue
        if bounds.relevance_terms and not _relevant(url, bounds.relevance_terms):
            continue
        seen.add(url)
        found_in[url] = sitemap_url

    outcome.sitemaps_attempted = files_fetched[0]
    for url in sorted(seen)[: bounds.max_candidate_urls]:
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


def _robots_error_reason(message: str) -> str:
    if message.startswith("redirect_overflow"):
        return "robots_redirect_overflow"
    if message.startswith("transport_error"):
        return "robots_transport_error"
    if message.startswith("dns_") or "blocked_ip" in message:
        return "robots_dns_error"
    if message.startswith("request_deadline_exceeded"):
        return "robots_timeout"
    if message.startswith("response_too_large"):
        return "robots_oversized"
    return "robots_fetch_error"


def _read_robots(base: str, fetcher: Fetcher) -> RobotsAccess:
    url = urljoin(base, "/robots.txt")
    try:
        result = fetcher(url)
    except SitemapDiscoveryError as exc:
        return RobotsAccess(ROBOTS_UNREACHABLE, _robots_error_reason(str(exc)), (), None)
    except Exception:
        return RobotsAccess(ROBOTS_UNREACHABLE, "robots_fetch_error", (), None)

    status = int(result.status)
    if 400 <= status <= 499:
        return RobotsAccess(ROBOTS_UNAVAILABLE, f"robots_http_{status}", (), None)
    if status != 200:
        return RobotsAccess(ROBOTS_UNREACHABLE, f"robots_http_{status}", (), None)

    robots = RobotsPolicy.parse((result.body or b"").decode("utf-8", "replace"))
    if robots.malformed:
        return RobotsAccess(
            ROBOTS_MALFORMED_RESTRICTIVE,
            "robots_unparseable",
            tuple(robots.sitemaps),
            robots,
        )
    if not robots.can_fetch(USER_AGENT, base):
        return RobotsAccess(
            ROBOTS_RESTRICTIVE,
            "robots_root_disallowed",
            tuple(robots.sitemaps),
            robots,
        )
    return RobotsAccess(ROBOTS_SUCCESS, "robots_ok", tuple(robots.sitemaps), robots)


def _discovery_event(
    *,
    url: str,
    discovered_from: str,
    vendor_id: str | None,
    discovery_run_id: str,
    discovered_at: str,
) -> dict[str, Any]:
    evidence = {
        "candidate_url": url,
        "discovered_from": discovered_from,
        "vendor_id": vendor_id,
        "authority_state": "unverified_candidate",
        "content_state": "not_fetched",
        "promotion_weight": "none",
    }
    evidence_digest = sha256_bytes(canonical_json(evidence))
    candidate_id = f"cand-sitemap-{sha256_bytes(canonical_json(url))[len('sha256:'): len('sha256:') + 12]}"
    classification = "unverified_candidate"
    return {
        "schema_version": "0.1.0",
        "discovery_event_id": sha256_bytes(
            canonical_json([candidate_id, discovery_run_id, evidence_digest, classification])
        )[len("sha256:") : len("sha256:") + 32],
        "candidate_id": candidate_id,
        "origin": "sitemap",
        "candidate_url": url,
        "evidence_digest": evidence_digest,
        "classification": classification,
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
