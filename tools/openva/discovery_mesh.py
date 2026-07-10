"""Autonomous, bounded discovery mesh for OpenVA catalog growth.

This module expands the upstream signal supply without changing catalog admission.
It emits source locators, vendor identity signals, crawl memory, and an execution
plan. Existing eligibility, verification, promotion, release, and automerge gates
remain authoritative.

The crawler is intentionally broad within explicit per-vendor budgets. Discovery
signals are not catalog facts and never imply vendor approval, risk, compliance,
or a contracting-party conclusion.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from tools.openva.source_authority import is_on_official_domain
from tools.openva.source_verification import FetchResult
from tools.openva.url_safety import validate_url_safety

SCHEMA_VERSION = "0.1.0"
POLICY_VERSION = "discovery-mesh.v1"

SOURCE_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "dpa": (
        "dpa",
        "data processing addendum",
        "data processing agreement",
        "accord de traitement des données",
        "vereinbarung zur auftragsverarbeitung",
        "auftragsverarbeitung",
        "acuerdo de tratamiento de datos",
        "acordo de processamento de dados",
        "データ処理契約",
        "数据处理协议",
        "資料處理協議",
        "데이터 처리 계약",
    ),
    "subprocessors_list": (
        "subprocessor",
        "sub-processors",
        "sub processor",
        "sous-traitants ultérieurs",
        "unterauftragsverarbeiter",
        "subencargados",
        "suboperadores",
        "サブプロセッサ",
        "次级处理者",
        "次級處理者",
        "하위 처리자",
    ),
    "privacy_notice": (
        "privacy policy",
        "privacy notice",
        "data protection notice",
        "politique de confidentialité",
        "datenschutzerklärung",
        "política de privacidad",
        "política de privacidade",
        "informativa sulla privacy",
        "プライバシーポリシー",
        "隐私政策",
        "隱私政策",
        "개인정보 처리방침",
        "kebijakan privasi",
        "dasar privasi",
    ),
    "security_page": (
        "security",
        "information security",
        "sécurité",
        "sicherheit",
        "seguridad",
        "segurança",
        "sicurezza",
        "セキュリティ",
        "安全",
        "보안",
        "keamanan",
        "keselamatan",
    ),
    "trust_center": (
        "trust center",
        "trust centre",
        "centre de confiance",
        "trust-center",
        "centro de confianza",
        "centro de confiança",
        "トラストセンター",
        "信任中心",
        "신뢰 센터",
        "pusat kepercayaan",
    ),
    "compliance_page": (
        "compliance",
        "certifications",
        "conformité",
        "konformität",
        "cumplimiento",
        "conformidade",
        "conformità",
        "コンプライアンス",
        "合规",
        "合規",
        "규정 준수",
        "kepatuhan",
        "pematuhan",
    ),
    "status_page": (
        "system status",
        "service status",
        "uptime",
        "état du service",
        "systemstatus",
        "estado del servicio",
        "status do serviço",
        "システムステータス",
        "服务状态",
        "服務狀態",
        "서비스 상태",
    ),
    "certification_reference": (
        "soc 2",
        "iso 27001",
        "iso 27701",
        "pci dss",
        "certification",
        "certificate",
        "certificat",
        "zertifizierung",
        "certificación",
        "certificação",
        "認証",
        "认证",
        "認證",
        "인증",
        "sertifikasi",
    ),
    "ai_terms": (
        "ai terms",
        "artificial intelligence terms",
        "generative ai terms",
        "conditions relatives à l'ia",
        "ki-bedingungen",
        "términos de inteligencia artificial",
        "termos de inteligência artificial",
        "ai利用規約",
        "人工智能条款",
        "人工智能條款",
        "인공지능 약관",
    ),
}

NAVIGATION_HINTS = (
    "legal",
    "privacy",
    "security",
    "trust",
    "compliance",
    "terms",
    "governance",
    "assurance",
    "resource",
    "company",
    "about",
    "footer",
    "data protection",
    "datenschutz",
    "confidentialité",
    "privacidad",
    "privacidade",
    "プライバシー",
    "隐私",
    "隱私",
    "개인정보",
)

RELATIONSHIP_HINTS = (
    "subprocessor",
    "sub-processor",
    "service provider",
    "infrastructure provider",
    "technology partner",
    "integration partner",
    "processor",
    "vendor",
    "supplier",
    "hosting provider",
)

GENERIC_ANCHORS = {
    "learn more",
    "read more",
    "here",
    "website",
    "link",
    "visit",
    "details",
}

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid"}


@dataclass(frozen=True)
class CrawlLimits:
    """Per-vendor safety bounds; defaults favour catalog growth, not tiny trials."""

    max_depth: int = 2
    max_pages: int = 500
    max_total_requests: int = 750
    max_links_per_page: int = 750
    max_locator_candidates: int = 2_000
    max_delegated_hosts: int = 100
    retry_transient_days: int = 2
    retry_dead_days: int = 30


@dataclass(frozen=True)
class LinkEvidence:
    url: str
    anchor_text: str
    rel: str
    surrounding_text: str


class AssuranceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[LinkEvidence] = []
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.text_parts: list[str] = []
        self._href: str | None = None
        self._rel = ""
        self._anchor_parts: list[str] = []
        self._in_title = False
        self._heading_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        low = tag.lower()
        if low == "a" and attributes.get("href"):
            self._href = attributes["href"]
            self._rel = attributes.get("rel", "")
            self._anchor_parts = []
        elif low == "title":
            self._in_title = True
        elif low in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low == "a" and self._href:
            anchor = normalize_space(" ".join(self._anchor_parts))
            context = normalize_space(" ".join(self.text_parts[-20:]))[-1_000:]
            self.links.append(LinkEvidence(self._href, anchor, self._rel, context))
            self._href = None
            self._rel = ""
            self._anchor_parts = []
        elif low == "title":
            self._in_title = False
        elif low in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._heading_depth:
            self._heading_depth -= 1

    def handle_data(self, data: str) -> None:
        text = normalize_space(data)
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
        return normalize_space(" ".join(self.title_parts))[:500]

    @property
    def headings(self) -> str:
        return normalize_space(" ".join(self.heading_parts))[:2_000]

    @property
    def text(self) -> str:
        return normalize_space(" ".join(self.text_parts))[:20_000]


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL has no host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    port = parsed.port
    netloc = host
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_QUERY_KEYS
            and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
        ),
        doseq=True,
    )
    return urlunparse((scheme, netloc, path, "", query, ""))


def url_is_public_safe(url: str) -> bool:
    try:
        return not validate_url_safety(url, resolve_dns=False)
    except (TypeError, ValueError):
        return False


def html_from_result(result: FetchResult) -> str | None:
    if result.http_status != 200:
        return None
    content_type = str(result.content_type or "").lower()
    if "html" not in content_type and b"<html" not in (result.body_sample or b"").lower():
        return None
    return (result.body_sample or b"").decode("utf-8", "replace")


def parse_html(result: FetchResult) -> AssuranceHTMLParser | None:
    html = html_from_result(result)
    if html is None:
        return None
    parser = AssuranceHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    return parser


def term_matches(text: str, terms: Iterable[str]) -> list[str]:
    haystack = normalize_space(text).casefold()
    return sorted({term for term in terms if term.casefold() in haystack})


def classify_locator(
    *,
    url: str,
    anchor_text: str = "",
    surrounding_text: str = "",
    page_title: str = "",
    page_headings: str = "",
) -> list[dict[str, Any]]:
    """Rank plausible source types from deterministic multilingual evidence."""

    parsed = urlparse(url)
    path_text = f"{parsed.hostname or ''} {parsed.path.replace('-', ' ').replace('_', ' ')}"
    fields = {
        "path": path_text,
        "anchor": anchor_text,
        "context": surrounding_text,
        "title": page_title,
        "headings": page_headings,
    }
    field_weights = {"path": 5, "anchor": 6, "context": 2, "title": 4, "headings": 4}
    ranked: list[dict[str, Any]] = []
    for source_type, terms in SOURCE_TYPE_TERMS.items():
        evidence: dict[str, list[str]] = {}
        score = 0
        for field, value in fields.items():
            matches = term_matches(value, terms)
            if matches:
                evidence[field] = matches
                score += field_weights[field] + min(4, len(matches) - 1)
        if score:
            ranked.append(
                {
                    "source_type": source_type,
                    "score": score,
                    "matched_terms": sorted({term for matches in evidence.values() for term in matches}),
                    "evidence_fields": evidence,
                }
            )
    return sorted(ranked, key=lambda row: (-int(row["score"]), str(row["source_type"])))


def navigation_relevance(url: str, anchor: str, context: str) -> int:
    text = f"{urlparse(url).path} {anchor} {context}".casefold()
    return sum(1 for hint in NAVIGATION_HINTS if hint.casefold() in text)


def relationship_relevance(anchor: str, context: str) -> int:
    text = f"{anchor} {context}".casefold()
    return sum(1 for hint in RELATIONSHIP_HINTS if hint.casefold() in text)


def official_entrypoints(vendor: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in vendor.get("public_entrypoints", []) or []:
        try:
            urls.append(canonical_url(str(value)))
        except ValueError:
            continue
    for value in vendor.get("official_domains", []) or []:
        domain = str(value).strip().lower().removeprefix("www.")
        if not domain:
            continue
        urls.extend((f"https://{domain}/", f"https://www.{domain}/"))
    return list(dict.fromkeys(urls))


def page_fingerprint(result: FetchResult) -> str | None:
    if not result.body_sample:
        return None
    return "sha256:" + hashlib.sha256(result.body_sample).hexdigest()


def retry_after_for(result: FetchResult, now: datetime, limits: CrawlLimits) -> str:
    if result.http_status is None or int(result.http_status or 0) >= 500:
        due = now + timedelta(days=limits.retry_transient_days)
    else:
        due = now + timedelta(days=limits.retry_dead_days)
    return due.isoformat().replace("+00:00", "Z")


def memory_record(
    *,
    vendor_id: str,
    url: str,
    provider: str,
    result: FetchResult,
    depth: int,
    observed_at: str,
    limits: CrawlLimits,
    candidate_count: int,
) -> dict[str, Any]:
    now = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    return {
        "schema_version": SCHEMA_VERSION,
        "vendor_id": vendor_id,
        "url": url,
        "provider": provider,
        "depth": depth,
        "last_attempted_at": observed_at,
        "http_status": result.http_status,
        "final_url": result.final_url,
        "content_type": result.content_type,
        "error": result.error,
        "content_fingerprint": page_fingerprint(result),
        "candidate_count": candidate_count,
        "retry_after": retry_after_for(result, now, limits),
        "not_advice": True,
    }


def source_locator_signal(
    *,
    vendor_id: str,
    url: str,
    source_type: str,
    score: int,
    matched_terms: list[str],
    evidence_fields: dict[str, list[str]],
    provider: str,
    discovered_from: str,
    authority_state: str,
    discovered_at: str,
) -> dict[str, Any]:
    identity = json.dumps([vendor_id, source_type, canonical_url(url)], separators=(",", ":"))
    signal_id = "srcsig-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_id": signal_id,
        "signal_type": "source_locator",
        "vendor_id": vendor_id,
        "candidate_url": canonical_url(url),
        "source_type_candidate": source_type,
        "score": score,
        "matched_terms": matched_terms,
        "evidence_fields": evidence_fields,
        "provider": provider,
        "discovered_from": discovered_from,
        "authority_state": authority_state,
        "discovered_at": discovered_at,
        "admission_weight": "none",
        "requires_verification": True,
        "not_advice": True,
    }


def _should_enqueue(url: str, anchor: str, context: str, depth: int, limits: CrawlLimits) -> bool:
    if depth >= limits.max_depth:
        return False
    return navigation_relevance(url, anchor, context) > 0 or bool(classify_locator(url=url, anchor_text=anchor))


def discover_source_frontier(
    vendor: dict[str, Any],
    fetcher: Callable[[str], FetchResult],
    *,
    limits: CrawlLimits | None = None,
    discovered_at: str | None = None,
) -> dict[str, Any]:
    """Crawl all attested official domains and emit unverified locator signals."""

    limits = limits or CrawlLimits()
    discovered_at = discovered_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    vendor_id = str(vendor["vendor_id"])
    official_domains = [str(value) for value in vendor.get("official_domains", []) or [] if value]
    frontier = deque((url, 0, "official_entrypoint") for url in official_entrypoints(vendor))
    visited: set[str] = set()
    queued: set[str] = {url for url, _, _ in frontier}
    signals: dict[str, dict[str, Any]] = {}
    memory: list[dict[str, Any]] = []
    delegated_hosts: set[str] = set()
    request_count = 0

    while frontier and len(visited) < limits.max_pages and request_count < limits.max_total_requests:
        url, depth, provider = frontier.popleft()
        if url in visited or not url_is_public_safe(url):
            continue
        visited.add(url)
        request_count += 1
        result = fetcher(url)
        parser = parse_html(result)
        page_candidate_count = 0
        if parser is not None:
            for link in parser.links[: limits.max_links_per_page]:
                try:
                    absolute = canonical_url(urljoin(result.final_url or url, link.url))
                except ValueError:
                    continue
                if not url_is_public_safe(absolute):
                    continue
                on_official_domain = is_on_official_domain(absolute, official_domains)
                classifications = classify_locator(
                    url=absolute,
                    anchor_text=link.anchor_text,
                    surrounding_text=link.surrounding_text,
                    page_title=parser.title,
                    page_headings=parser.headings,
                )
                if classifications:
                    authority_state = "official_domain" if on_official_domain else "first_party_attested_delegate"
                    if not on_official_domain:
                        host = (urlparse(absolute).hostname or "").lower()
                        if host not in delegated_hosts and len(delegated_hosts) >= limits.max_delegated_hosts:
                            continue
                        delegated_hosts.add(host)
                    for classification in classifications:
                        signal = source_locator_signal(
                            vendor_id=vendor_id,
                            url=absolute,
                            source_type=str(classification["source_type"]),
                            score=int(classification["score"]) + (8 if on_official_domain else 3),
                            matched_terms=list(classification["matched_terms"]),
                            evidence_fields=dict(classification["evidence_fields"]),
                            provider="html_link_graph",
                            discovered_from=result.final_url or url,
                            authority_state=authority_state,
                            discovered_at=discovered_at,
                        )
                        prior = signals.get(signal["signal_id"])
                        if prior is None or int(signal["score"]) > int(prior["score"]):
                            signals[signal["signal_id"]] = signal
                        page_candidate_count += 1
                if on_official_domain and absolute not in visited and absolute not in queued:
                    if _should_enqueue(absolute, link.anchor_text, link.surrounding_text, depth, limits):
                        frontier.append((absolute, depth + 1, "html_link_graph"))
                        queued.add(absolute)
        memory.append(
            memory_record(
                vendor_id=vendor_id,
                url=url,
                provider=provider,
                result=result,
                depth=depth,
                observed_at=discovered_at,
                limits=limits,
                candidate_count=page_candidate_count,
            )
        )

    ranked = sorted(
        signals.values(),
        key=lambda row: (-int(row["score"]), str(row["source_type_candidate"]), str(row["candidate_url"])),
    )[: limits.max_locator_candidates]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "source_frontier_discovery",
        "policy_version": POLICY_VERSION,
        "vendor_id": vendor_id,
        "generated_at": discovered_at,
        "summary": {
            "official_domain_count": len(official_domains),
            "pages_attempted": len(memory),
            "requests": request_count,
            "locator_signal_count": len(ranked),
            "delegated_host_count": len(delegated_hosts),
            "frontier_remaining": len(frontier),
        },
        "source_locator_signals": ranked,
        "discovery_memory": memory,
        "posture": {
            "catalog_mutation_performed": False,
            "signals_are_catalog_facts": False,
            "delegated_links_require_verification": True,
            "non_advisory": True,
        },
    }


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized[:80] or "unresolved-vendor"


def vendor_identity_signal(
    *,
    observed_name: str,
    source_url: str,
    provider: str,
    observed_domain: str | None = None,
    country: str | None = None,
    relationship_context: str | None = None,
    observed_at: str | None = None,
    demand_count: int = 1,
) -> dict[str, Any]:
    observed_at = observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    clean_name = normalize_space(observed_name)[:200]
    clean_domain = (observed_domain or "").strip().lower().removeprefix("www.") or None
    key = json.dumps([clean_name.casefold(), clean_domain, provider, canonical_url(source_url)], separators=(",", ":"))
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_id": "vidsig-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20],
        "signal_type": "vendor_identity",
        "candidate_vendor_id": slugify(clean_domain.split(".")[0] if clean_domain else clean_name),
        "display_name_observed": clean_name,
        "domain_observed": clean_domain,
        "country_observed": country,
        "source_url": canonical_url(source_url),
        "provider": provider,
        "relationship_context": relationship_context,
        "observed_at": observed_at,
        "demand_count": max(1, int(demand_count)),
        "identity_state": "partially_resolved" if clean_domain else "unresolved",
        "admission_weight": "none",
        "requires_identity_resolution": True,
        "not_advice": True,
    }


def extract_relationship_identity_signals(
    *,
    source_url: str,
    result: FetchResult,
    provider: str = "relationship_graph",
    observed_at: str | None = None,
) -> list[dict[str, Any]]:
    """Extract named external relationships from a public first-party page."""

    parser = parse_html(result)
    if parser is None:
        return []
    source_host = (urlparse(result.final_url or source_url).hostname or "").lower().removeprefix("www.")
    output: dict[str, dict[str, Any]] = {}
    for link in parser.links:
        try:
            absolute = canonical_url(urljoin(result.final_url or source_url, link.url))
        except ValueError:
            continue
        host = (urlparse(absolute).hostname or "").lower().removeprefix("www.")
        anchor = normalize_space(link.anchor_text)
        if not host or host == source_host or anchor.casefold() in GENERIC_ANCHORS or len(anchor) < 2:
            continue
        relationship_score = relationship_relevance(anchor, link.surrounding_text)
        if relationship_score <= 0:
            continue
        signal = vendor_identity_signal(
            observed_name=anchor,
            observed_domain=host,
            source_url=source_url,
            provider=provider,
            relationship_context=normalize_space(link.surrounding_text)[-500:],
            observed_at=observed_at,
        )
        output[signal["signal_id"]] = signal
    return sorted(output.values(), key=lambda row: (str(row["display_name_observed"]), str(row["domain_observed"])))


def aggregate_identity_signals(
    signals: Iterable[dict[str, Any]],
    *,
    known_vendor_ids: set[str] | None = None,
    known_domains: set[str] | None = None,
) -> dict[str, Any]:
    """Aggregate demand and provenance without discarding incomplete identities."""

    known_vendor_ids = known_vendor_ids or set()
    known_domains = {value.lower().removeprefix("www.") for value in (known_domains or set())}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        name_key = normalize_space(str(signal.get("display_name_observed") or "")).casefold()
        domain_key = str(signal.get("domain_observed") or "").lower().removeprefix("www.")
        groups[(domain_key, name_key)].append(dict(signal))

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for (domain, name), members in groups.items():
        candidate_vendor_id = str(members[0].get("candidate_vendor_id") or slugify(domain or name))
        collision_reasons = []
        if candidate_vendor_id in known_vendor_ids:
            collision_reasons.append("vendor_id")
        if domain and domain in known_domains:
            collision_reasons.append("official_domain")
        if collision_reasons:
            skipped.append(
                {
                    "candidate_vendor_id": candidate_vendor_id,
                    "reason": "already_materialized",
                    "collisions": collision_reasons,
                    "signal_ids": sorted(str(row.get("signal_id")) for row in members),
                }
            )
            continue
        providers = sorted({str(row.get("provider")) for row in members if row.get("provider")})
        source_urls = sorted({str(row.get("source_url")) for row in members if row.get("source_url")})
        demand = sum(max(1, int(row.get("demand_count", 1))) for row in members)
        candidates.append(
            {
                "schema_version": SCHEMA_VERSION,
                "candidate_vendor_id": candidate_vendor_id,
                "display_name_candidate": str(members[0].get("display_name_observed") or candidate_vendor_id),
                "official_domain_candidate": domain or None,
                "headquarters_country_candidate": next(
                    (row.get("country_observed") for row in members if row.get("country_observed")), None
                ),
                "identity_state": "partially_resolved" if domain else "unresolved",
                "signal_count": len(members),
                "demand_count": demand,
                "independent_provider_count": len(providers),
                "providers": providers,
                "source_urls": source_urls,
                "signal_ids": sorted(str(row.get("signal_id")) for row in members),
                "priority": demand * 5 + len(providers) * 10 + (10 if domain else 0),
                "requires_review": True,
                "writes_canonical_vendors": False,
                "not_advice": True,
            }
        )
    candidates.sort(key=lambda row: (-int(row["priority"]), str(row["candidate_vendor_id"])))
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "vendor_identity_signal_aggregation",
        "summary": {
            "input_signal_count": sum(len(rows) for rows in groups.values()),
            "candidate_count": len(candidates),
            "collision_count": len(skipped),
            "unresolved_candidate_count": sum(1 for row in candidates if not row["official_domain_candidate"]),
        },
        "vendor_candidates": candidates,
        "skipped": skipped,
        "posture": {
            "incomplete_signals_retained": True,
            "catalog_mutation_performed": False,
            "non_advisory": True,
        },
    }


def build_discovery_plan(
    *,
    coverage_queue: Iterable[dict[str, Any]],
    identity_candidates: Iterable[dict[str, Any]] = (),
    max_tasks: int = 500,
    breadth_share: float = 0.45,
    depth_share: float = 0.40,
    maintenance_share: float = 0.15,
) -> dict[str, Any]:
    """Build independently budgeted breadth, depth, and maintenance queues."""

    if max_tasks < 1:
        raise ValueError("max_tasks must be positive")
    shares = {"breadth": breadth_share, "depth": depth_share, "maintenance": maintenance_share}
    if any(value < 0 for value in shares.values()) or sum(shares.values()) <= 0:
        raise ValueError("queue shares must be non-negative and have a positive total")
    total_share = sum(shares.values())
    budgets = {name: int(max_tasks * value / total_share) for name, value in shares.items()}
    remainder = max_tasks - sum(budgets.values())
    for name in ("breadth", "depth", "maintenance"):
        if remainder <= 0:
            break
        budgets[name] += 1
        remainder -= 1

    queues: dict[str, list[dict[str, Any]]] = {"breadth": [], "depth": [], "maintenance": []}
    for candidate in identity_candidates:
        queues["breadth"].append(
            {
                "task_type": "resolve_vendor_identity",
                "candidate_vendor_id": candidate.get("candidate_vendor_id"),
                "priority": int(candidate.get("priority", 0)),
                "payload": candidate,
            }
        )
    for row in coverage_queue:
        queue_class = str(row.get("queue_class") or "")
        if queue_class == "missing_vendor":
            lane = "breadth"
            task_type = "discover_vendor_identity"
        elif queue_class in {"missing_source_type", "high_priority_vendor", "machine_readable_surface_needed"}:
            lane = "depth"
            task_type = "discover_source_frontier"
        else:
            lane = "maintenance"
            task_type = "recheck_source"
        queues[lane].append(
            {
                "task_type": task_type,
                "vendor_id": row.get("vendor_id"),
                "source_id": row.get("source_id"),
                "source_type": row.get("source_type"),
                "priority": int(row.get("priority", 0)),
                "payload": row,
            }
        )

    planned: dict[str, list[dict[str, Any]]] = {}
    for lane, rows in queues.items():
        rows.sort(
            key=lambda row: (
                -int(row.get("priority", 0)),
                str(row.get("candidate_vendor_id") or row.get("vendor_id") or ""),
                str(row.get("source_type") or ""),
            )
        )
        planned[lane] = rows[: budgets[lane]]

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "discovery_mesh_plan",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "max_tasks": max_tasks,
        "budgets": budgets,
        "summary": {
            "planned_task_count": sum(len(rows) for rows in planned.values()),
            "available_task_count": sum(len(rows) for rows in queues.values()),
            "planned_by_lane": {name: len(rows) for name, rows in planned.items()},
            "available_by_lane": {name: len(rows) for name, rows in queues.items()},
        },
        "queues": planned,
        "posture": {
            "catalog_mutation_performed": False,
            "promotion_concurrency_is_external": True,
            "non_advisory": True,
        },
    }
