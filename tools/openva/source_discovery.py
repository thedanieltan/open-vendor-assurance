from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yaml

from tools.openva.source_verification import (
    FetchResult,
    ROOT,
    classify_status,
    normalize_text,
    semantic_match,
    title_from_sample,
)

SOURCE_TYPE_REGISTRY: dict[str, dict[str, Any]] = {
    "dpa": {
        "candidate_paths": (
            "/legal/data-processing-addendum",
            "/data-processing-addendum",
            "/legal/dpa",
            "/dpa",
            "/privacy/dpa.html",
            "/privacy/dpa",
        ),
        "known_subdomain_patterns": (),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": True,
        "qualifies_as_promotion_source_role": True,
    },
    "subprocessors_list": {
        "candidate_paths": (
            "/legal/subprocessors",
            "/subprocessors",
            "/legal/sub-processors",
            "/sub-processors",
            "/privacy/sub-processors.html",
            "/privacy/subprocessors",
        ),
        "known_subdomain_patterns": (),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": True,
        "qualifies_as_promotion_source_role": True,
    },
    "privacy_notice": {
        "candidate_paths": (
            "/privacy",
            "/privacy-policy",
            "/legal/privacy",
            "/legal/privacy-policy",
            "/privacy.html",
        ),
        "known_subdomain_patterns": (),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": True,
        "qualifies_as_promotion_source_role": True,
    },
    "security_page": {
        "candidate_paths": (
            "/security",
            "/trust",
            "/trust-center",
            "/trustcenter",
            "/security.html",
        ),
        "known_subdomain_patterns": ("security",),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": True,
        "qualifies_as_promotion_source_role": True,
    },
    "compliance_page": {
        "candidate_paths": (
            "/compliance",
            "/security/compliance",
            "/trust/compliance",
            "/trust-center/compliance",
            "/trustcenter/compliance",
            "/compliance.html",
        ),
        "known_subdomain_patterns": (),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": False,
        "qualifies_as_promotion_source_role": True,
    },
    "trust_center": {
        "candidate_paths": (
            "/trust",
            "/trust-center",
            "/trustcenter",
            "/security",
            "/security/trust",
            "/security/compliance",
        ),
        "known_subdomain_patterns": ("trust", "trustcenter"),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": True,
        "qualifies_as_promotion_source_role": True,
    },
    "status_page": {
        "candidate_paths": (
            "/status",
            "/statuspage",
            "/system-status",
            "/service-status",
            "/uptime",
        ),
        "known_subdomain_patterns": ("status",),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": False,
        "qualifies_as_promotion_source_role": False,
    },
    "certification_reference": {
        "candidate_paths": (
            "/security/certifications",
            "/trust/certifications",
            "/trust-center/certifications",
            "/trustcenter/certifications",
            "/compliance/certifications",
            "/security/compliance",
            "/trust/compliance",
        ),
        "known_subdomain_patterns": (),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": True,
        "qualifies_as_promotion_source_role": True,
    },
    "ai_terms": {
        "candidate_paths": (
            "/legal/ai-terms",
            "/ai-terms",
            "/terms/ai",
            "/legal/ai",
            "/responsible-ai",
            "/trust/ai",
        ),
        "known_subdomain_patterns": (),
        "qualifies_for_coverage": True,
        "qualifies_for_vendor_materialization": False,
        "qualifies_as_promotion_source_role": True,
    },
}

DEFAULT_SOURCE_TYPES = tuple(SOURCE_TYPE_REGISTRY)
DISCOVERY_PATHS: dict[str, tuple[str, ...]] = {
    source_type: registry["candidate_paths"]
    for source_type, registry in SOURCE_TYPE_REGISTRY.items()
}

UNAVAILABLE_REASON = {
    source_type: "distinct_public_url_not_identified"
    for source_type in SOURCE_TYPE_REGISTRY
}


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def parse_source_types(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        return DEFAULT_SOURCE_TYPES
    source_types = tuple(item.strip() for item in value.split(",") if item.strip())
    if not source_types:
        raise ValueError("source types must not be empty")
    unknown = sorted(set(source_types) - set(DEFAULT_SOURCE_TYPES))
    if unknown:
        raise ValueError(f"unsupported source types: {', '.join(unknown)}")
    return source_types


def source_type_role(source_type: str, role: str) -> bool:
    return bool(SOURCE_TYPE_REGISTRY.get(source_type, {}).get(role, False))


def safe_discovery_fetcher(
    vendor: dict[str, Any], fetch_timeout: float | None = None
) -> Callable[[str], FetchResult]:
    """SSRF-safe discovery fetcher bound to the vendor's own official domains."""
    official_domains = [str(domain) for domain in (vendor.get("official_domains") or []) if domain]
    if not official_domains:
        def _unresolved(url: str) -> FetchResult:
            return FetchResult(
                requested_url=url,
                final_url=url,
                http_status=None,
                content_type=None,
                content_length=None,
                etag=None,
                last_modified=None,
                body_sample=b"",
                error="authority_unresolved:no_official_domains",
            )

        return _unresolved

    from tools.openva.safe_verify import build_safe_verify_fetcher
    from tools.openva.sitemap_discovery import load_bounds

    bounds = load_bounds()
    return build_safe_verify_fetcher(
        official_domains,
        max_redirects=bounds.max_redirects,
        timeout_seconds=fetch_timeout if fetch_timeout is not None else bounds.max_request_seconds,
    )


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def vendor_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/vendor.yaml"))


def canonical_source_types_for_vendor(vendor_id: str, root: Path = ROOT) -> set[str]:
    result: set[str] = set()
    for path in sorted((root / "data" / "vendors" / vendor_id / "sources").glob("*.yaml")):
        source = load_yaml(path)
        source_type = source.get("source_type")
        if isinstance(source_type, str):
            result.add(source_type)
    return result


def unavailable_records_for_vendor(vendor_id: str, root: Path = ROOT) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "vendors" / vendor_id / "unavailable_sources").glob("*.yaml")):
        unavailable = load_yaml(path)
        if isinstance(unavailable.get("source_type"), str):
            records.append(unavailable)
    return records


def unavailable_lifecycle(record: dict[str, Any], *, today: date | None = None) -> str:
    if record.get("status") in {"recovered", "superseded"}:
        return str(record["status"])
    today = today or date.today()
    next_review_after = record.get("next_review_after")
    if not next_review_after:
        return "due_for_recheck"
    try:
        due = date.fromisoformat(str(next_review_after))
    except ValueError:
        return "due_for_recheck"
    return "not_due" if today < due else "due_for_recheck"


def not_due_unavailable_source_types(vendor_id: str, root: Path = ROOT) -> set[str]:
    return {
        str(record["source_type"])
        for record in unavailable_records_for_vendor(vendor_id, root)
        if unavailable_lifecycle(record) == "not_due"
    }


def base_urls_for_vendor(vendor: dict[str, Any]) -> list[str]:
    bases: list[str] = []
    for entrypoint in vendor.get("public_entrypoints", []) or []:
        parsed = urlparse(str(entrypoint))
        if parsed.scheme and parsed.netloc:
            bases.append(f"{parsed.scheme}://{parsed.netloc}")
    for domain in vendor.get("official_domains", []) or []:
        bases.append(f"https://www.{domain}")
        bases.append(f"https://{domain}")
    return list(dict.fromkeys(base.rstrip("/") for base in bases))


def candidate_urls_for(vendor: dict[str, Any], source_type: str) -> list[str]:
    urls: list[str] = []
    for base in base_urls_for_vendor(vendor):
        for path in DISCOVERY_PATHS.get(source_type, ()):
            urls.append(f"{base}{path}")
    for domain in vendor.get("official_domains", []) or []:
        normalized_domain = str(domain).strip().lower().removeprefix("www.")
        for label in SOURCE_TYPE_REGISTRY.get(source_type, {}).get("known_subdomain_patterns", ()):
            base = f"https://{label}.{normalized_domain}"
            urls.append(base)
            for path in DISCOVERY_PATHS.get(source_type, ()):
                urls.append(f"{base}{path}")
    return list(dict.fromkeys(urls))


def is_candidate_match(source_type: str, result: FetchResult) -> tuple[bool, dict[str, Any]]:
    if result.http_status != 200:
        return False, {"status": "not_checked_non_200", "matched_terms": []}
    text = normalize_text(result.body_sample, result.content_type)
    semantic = semantic_match(source_type, text, result.content_type)
    return semantic.get("status") in {"strong", "weak", "not_evaluated_pdf_sample"}, semantic


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "msclkid"}


def canonical_url_for_id(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    host = parsed.hostname or parsed.netloc
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        host = host.lower()
    host = host.lower()
    port = parsed.port
    netloc = host
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def url_digest(url: str) -> str:
    return hashlib.sha256(canonical_url_for_id(url).encode("utf-8")).hexdigest()[:12]


def candidate_source_id(vendor_id: str, source_type: str, url: str | None = None) -> str:
    suffix = source_type.replace("_", "-")
    if url:
        return f"{vendor_id}-{suffix}-{url_digest(url)}"
    return f"{vendor_id}-{suffix}-candidate"


def unavailable_source_id(vendor_id: str, source_type: str) -> str:
    suffix = source_type.replace("_", "-")
    return f"{vendor_id}-{suffix}"


def same_authority(candidate_url: str, final_url: str | None) -> bool:
    candidate_host = urlparse(candidate_url).netloc.lower().removeprefix("www.")
    final_host = urlparse(final_url or candidate_url).netloc.lower().removeprefix("www.")
    return candidate_host == final_host


def evidence_digest(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def candidate_record(
    vendor_id: str,
    source_type: str,
    url: str,
    result: FetchResult,
    semantic: dict[str, Any],
    discovered_at: str,
) -> dict[str, Any]:
    verification_source = {"source_url": url, "source_type": source_type}
    verification_status = classify_status(verification_source, result, semantic)
    canonical_candidate_url = result.final_url if same_authority(url, result.final_url) else url
    evidence = {
        "page_title": title_from_sample(result.body_sample, result.content_type),
        "matched_terms": semantic.get("matched_terms", []),
        "final_url": result.final_url,
        "http_status": result.http_status,
        "content_type": result.content_type,
        "semantic_status": semantic.get("status"),
        "verification_status": verification_status,
        "soft_404_detected": verification_status == "soft_not_found",
    }
    return {
        "schema_version": "0.1.0",
        "candidate_source_id": candidate_source_id(vendor_id, source_type, canonical_candidate_url),
        "vendor_id": vendor_id,
        "source_type_candidate": source_type,
        "candidate_url": url,
        "requested_url": url,
        "observed_final_url": result.final_url,
        "canonical_candidate_url": canonical_candidate_url,
        "candidate_status": "selected",
        "selection_run_id": discovered_at,
        "superseded_by_candidate_id": None,
        "evidence_digest": evidence_digest(evidence),
        "discovery_method": "official_domain_crawl",
        "confidence": "likely" if semantic.get("status") == "strong" else "candidate",
        "requires_review": True,
        "discovered_at": discovered_at,
        "discovered_by": "agent",
        "evidence": evidence,
        "notes": "Candidate source discovered from official vendor domains. Not promoted to canonical source without review.",
        "not_advice": True,
    }


def unavailable_record(
    vendor_id: str,
    source_type: str,
    checked_urls: list[str],
    reviewed_at: str,
    next_review_after: str,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "unavailable_source_id": unavailable_source_id(vendor_id, source_type),
        "vendor_id": vendor_id,
        "source_type": source_type,
        "status": "not_identified",
        "reason": UNAVAILABLE_REASON.get(source_type, "other"),
        "reviewed_at": reviewed_at,
        "reviewed_by": "agent",
        "next_review_after": next_review_after,
        "candidate_urls_checked": checked_urls[:20],
        "notes": "No matching public source was identified by narrow official-domain candidate discovery. This is not a legal or procurement conclusion.",
        "not_advice": True,
    }


def url_text_evidence(source_type: str, url: str, result: FetchResult) -> bool:
    haystack = " ".join(
        [
            urlparse(url).path.replace("-", " ").replace("_", " "),
            urlparse(result.final_url or "").path.replace("-", " ").replace("_", " "),
            title_from_sample(result.body_sample, result.content_type) or "",
        ]
    ).lower()
    terms = {
        "dpa": ("dpa", "data processing"),
        "subprocessors_list": ("subprocessor", "sub processor"),
        "privacy_notice": ("privacy",),
        "security_page": ("security", "trust"),
        "compliance_page": ("compliance", "soc", "iso"),
        "trust_center": ("trust", "security", "compliance"),
        "status_page": ("status", "uptime", "incident"),
        "certification_reference": ("certification", "certificate", "soc", "iso", "audit"),
        "ai_terms": ("ai", "artificial intelligence", "machine learning", "model training"),
    }.get(source_type, ())
    return any(term in haystack for term in terms)


def candidate_rank(source_type: str, url: str, result: FetchResult, semantic: dict[str, Any]) -> tuple[int, str]:
    if result.http_status != 200:
        return 0, "unavailable_or_mismatch"
    status = str(semantic.get("status") or "")
    authority = same_authority(url, result.final_url)
    corroborated_pdf = (
        status == "not_evaluated_pdf_sample"
        and "pdf" in str(result.content_type or "").lower()
        and url_text_evidence(source_type, url, result)
    )
    if status == "strong" and authority:
        return 500, "strong_same_authority_canonical_url"
    if status == "strong":
        return 450, "strong_same_authority_redirect"
    if corroborated_pdf:
        return 400, "pdf_with_corroborating_title_path_evidence"
    if status == "weak":
        return 300, "weak_semantic_candidate"
    return 0, "unavailable_or_mismatch"


def discovery_event(
    *,
    vendor_id: str,
    source_type: str,
    observation: dict[str, Any],
    classification: str,
    discovered_at: str,
    discovery_run_id: str,
) -> dict[str, Any]:
    candidate_url = str(observation.get("candidate_url") or "")
    return {
        "schema_version": "0.1.0",
        "discovery_event_id": evidence_digest(
            {
                "candidate_id": candidate_source_id(vendor_id, source_type, candidate_url),
                "discovery_run_id": discovery_run_id,
                "evidence_digest": evidence_digest(observation),
                "classification": classification,
            }
        ).removeprefix("sha256:")[:32],
        "candidate_id": candidate_source_id(vendor_id, source_type, candidate_url),
        "vendor_id": vendor_id,
        "source_type": source_type,
        "origin": "source_discovery",
        "candidate_url": candidate_url,
        "evidence_digest": evidence_digest(observation),
        "classification": classification,
        "reason_codes": [str(observation.get("rank_reason") or classification)],
        "retry_after": None,
        "supersedes": None,
        "discovered_at": discovered_at,
        "discovery_run_id": discovery_run_id,
        "policy_version": "source_discovery_registry_0.3.0",
        "not_advice": True,
    }


def discover_for_vendor(
    vendor: dict[str, Any],
    root: Path = ROOT,
    fetcher: Callable[[str], FetchResult] | None = None,
    source_types: tuple[str, ...] = DEFAULT_SOURCE_TYPES,
    max_urls_per_type: int = 20,
    fetch_timeout: float | None = None,
) -> dict[str, Any]:
    if fetcher is None:
        fetcher = safe_discovery_fetcher(vendor, fetch_timeout)
    vendor_id = str(vendor["vendor_id"])
    existing_types = canonical_source_types_for_vendor(vendor_id, root) | not_due_unavailable_source_types(vendor_id, root)
    discovered_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    discovery_run_id = f"{vendor_id}-{discovered_at}"
    next_review_after = (date.today() + timedelta(days=90)).isoformat()
    candidates: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for source_type in source_types:
        if source_type in existing_types:
            continue
        checked_urls: list[str] = []
        candidate_urls = candidate_urls_for(vendor, source_type)[:max_urls_per_type]
        ranked: list[tuple[int, int, str, str, FetchResult, dict[str, Any]]] = []
        for index, url in enumerate(candidate_urls):
            checked_urls.append(url)
            result = fetcher(url)
            matched, semantic = is_candidate_match(source_type, result)
            rank, rank_reason = candidate_rank(source_type, url, result, semantic)
            observation = {
                "source_type": source_type,
                "candidate_url": url,
                "http_status": result.http_status,
                "final_url": result.final_url,
                "content_type": result.content_type,
                "semantic_status": semantic.get("status"),
                "verification_status": classify_status({"source_url": url, "source_type": source_type}, result, semantic),
                "matched_terms": semantic.get("matched_terms", []),
                "candidate_rank": rank,
                "rank_reason": rank_reason,
            }
            observations.append(observation)
            events.append(
                discovery_event(
                    vendor_id=vendor_id,
                    source_type=source_type,
                    observation=observation,
                    classification=rank_reason,
                    discovered_at=discovered_at,
                    discovery_run_id=discovery_run_id,
                )
            )
            if matched and rank > 0:
                ranked.append((rank, index, rank_reason, url, result, semantic))
        if ranked:
            rank, _index, rank_reason, url, result, semantic = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
            selected = candidate_record(vendor_id, source_type, url, result, semantic, discovered_at)
            selected["selection"] = {
                "rank": rank,
                "rank_reason": rank_reason,
                "alternative_candidate_count": max(0, len(ranked) - 1),
            }
            selected["alternative_candidates"] = [
                {
                    "candidate_source_id": candidate_source_id(vendor_id, source_type, alternative_url),
                    "candidate_status": "alternative",
                    "candidate_url": alternative_url,
                    "requested_url": alternative_url,
                    "observed_final_url": alternative_result.final_url,
                    "canonical_candidate_url": alternative_result.final_url or alternative_url,
                    "candidate_rank": alternative_rank,
                    "rank_reason": alternative_reason,
                    "semantic_status": alternative_semantic.get("status"),
                    "matched_terms": alternative_semantic.get("matched_terms", []),
                    "http_status": alternative_result.http_status,
                    "final_url": alternative_result.final_url,
                }
                for alternative_rank, _alternative_index, alternative_reason, alternative_url, alternative_result, alternative_semantic in ranked
                if alternative_url != url
            ]
            candidates.append(selected)
        else:
            unavailable.append(unavailable_record(vendor_id, source_type, checked_urls, discovered_at, next_review_after))

    return {
        "vendor_id": vendor_id,
        "candidates": candidates,
        "unavailable_sources": unavailable,
        "observations": observations,
        "discovery_events": events,
    }


def verify_sitemap_locators(
    vendor: dict[str, Any],
    locator_urls: list[str],
    *,
    fetcher: Callable[[str], FetchResult],
    source_types: tuple[str, ...] = DEFAULT_SOURCE_TYPES,
    discovered_at: str | None = None,
    discovery_run_id: str | None = None,
    max_locators: int = 50,
) -> dict[str, Any]:
    vendor_id = str(vendor["vendor_id"])
    discovered_at = discovered_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    discovery_run_id = discovery_run_id or f"{vendor_id}-sitemap-{discovered_at}"
    candidates: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()

    for url in list(dict.fromkeys(locator_urls))[:max_locators]:
        result = fetcher(url)
        best: tuple[int, str, dict[str, Any], str] | None = None
        for source_type in source_types:
            matched, semantic = is_candidate_match(source_type, result)
            rank, rank_reason = candidate_rank(source_type, url, result, semantic)
            if matched and rank > 0 and (best is None or rank > best[0]):
                best = (rank, source_type, semantic, rank_reason)
        if best is not None:
            rank, source_type, semantic, rank_reason = best
        else:
            source_type = source_types[0]
            _matched, semantic = is_candidate_match(source_type, result)
            rank, rank_reason = candidate_rank(source_type, url, result, semantic)
        observation = {
            "source_type": source_type,
            "candidate_url": url,
            "http_status": result.http_status,
            "final_url": result.final_url,
            "content_type": result.content_type,
            "semantic_status": semantic.get("status"),
            "verification_status": classify_status({"source_url": url, "source_type": source_type}, result, semantic),
            "matched_terms": semantic.get("matched_terms", []),
            "candidate_rank": rank,
            "rank_reason": rank_reason,
            "discovery_method": "sitemap_locator_verification",
        }
        observations.append(observation)
        events.append(
            discovery_event(
                vendor_id=vendor_id,
                source_type=source_type,
                observation=observation,
                classification=rank_reason,
                discovered_at=discovered_at,
                discovery_run_id=discovery_run_id,
            )
        )
        if best is not None:
            record = candidate_record(vendor_id, source_type, url, result, semantic, discovered_at)
            record["discovery_method"] = "sitemap_locator_verification"
            if record["candidate_source_id"] not in seen_candidate_ids:
                seen_candidate_ids.add(record["candidate_source_id"])
                candidates.append(record)

    return {
        "vendor_id": vendor_id,
        "candidates": candidates,
        "unavailable_sources": [],
        "observations": observations,
        "discovery_events": events,
    }


def write_discovery_outputs(discovery: dict[str, Any], root: Path = ROOT) -> None:
    vendor_id = discovery["vendor_id"]
    base = root / "data" / "vendors" / vendor_id
    for candidate in discovery["candidates"]:
        write_yaml(base / "candidate_sources" / f"{candidate['candidate_source_id']}.yaml", candidate)
    for unavailable in discovery["unavailable_sources"]:
        write_yaml(base / "unavailable_sources" / f"{unavailable['unavailable_source_id']}.yaml", unavailable)


def candidate_to_vendor(candidate: dict[str, Any]) -> dict[str, Any]:
    vendor_id = str(candidate.get("candidate_vendor_id") or "")
    domain = str(candidate.get("official_domain_candidate") or "").strip().lower().removeprefix("www.")
    entrypoint = str(candidate.get("source_index_url") or f"https://{domain}")
    return {
        "vendor_id": vendor_id,
        "display_name": candidate.get("display_name_candidate"),
        "official_domains": [domain] if domain else [],
        "public_entrypoints": [entrypoint] if entrypoint else [],
    }


def build_discovery_report(
    root: Path = ROOT,
    fetcher: Callable[[str], FetchResult] | None = None,
    vendor_limit: int | None = None,
    write: bool = False,
    source_types: tuple[str, ...] = DEFAULT_SOURCE_TYPES,
    max_urls_per_type: int = 20,
    fetch_timeout: float | None = None,
) -> dict[str, Any]:
    paths = vendor_paths(root)
    if vendor_limit is not None:
        paths = paths[:vendor_limit]
    vendor_results: list[dict[str, Any]] = []
    for path in paths:
        vendor = load_yaml(path)
        result = discover_for_vendor(vendor, root=root, fetcher=fetcher, source_types=source_types, max_urls_per_type=max_urls_per_type, fetch_timeout=fetch_timeout)
        if write:
            write_discovery_outputs(result, root=root)
        vendor_results.append(result)
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "source_discovery_report",
        "posture": {
            "network_fetch_performed": True,
            "writes_repository_state": write,
            "writes_canonical_sources": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
        },
        "summary": {
            "vendors_checked": len(vendor_results),
            "candidate_sources_written_or_reported": sum(len(item["candidates"]) for item in vendor_results),
            "unavailable_sources_written_or_reported": sum(len(item["unavailable_sources"]) for item in vendor_results),
        },
        "vendors": vendor_results,
    }


def build_vendor_candidate_discovery_report(
    vendor_candidate_report: dict[str, Any],
    root: Path = ROOT,
    fetcher: Callable[[str], FetchResult] | None = None,
    vendor_limit: int | None = None,
    source_types: tuple[str, ...] = DEFAULT_SOURCE_TYPES,
    max_urls_per_type: int = 20,
    fetch_timeout: float | None = None,
) -> dict[str, Any]:
    if vendor_candidate_report.get("report_type") != "vendor_candidate_discovery_report":
        raise ValueError("expected vendor_candidate_discovery_report")
    candidates = [item for item in vendor_candidate_report.get("vendor_candidates", []) or [] if isinstance(item, dict)]
    if vendor_limit is not None:
        candidates = candidates[:vendor_limit]
    vendor_results: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.get("candidate_vendor_id") or not candidate.get("official_domain_candidate"):
            continue
        result = discover_for_vendor(candidate_to_vendor(candidate), root=root, fetcher=fetcher, source_types=source_types, max_urls_per_type=max_urls_per_type, fetch_timeout=fetch_timeout)
        result.update(
            {
                "candidate_vendor_id": candidate.get("candidate_vendor_id"),
                "display_name_candidate": candidate.get("display_name_candidate"),
                "official_domain_candidate": candidate.get("official_domain_candidate"),
                "coverage_lane": candidate.get("coverage_lane"),
                "cohort_id": candidate.get("cohort_id"),
            }
        )
        vendor_results.append(result)
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "source_discovery_report",
        "discovery_context": "vendor_candidate_source_discovery",
        "posture": {
            "network_fetch_performed": True,
            "writes_repository_state": False,
            "writes_canonical_sources": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
        },
        "summary": {
            "vendors_checked": len(vendor_results),
            "vendor_candidates_checked": len(vendor_results),
            "candidate_sources_written_or_reported": sum(len(item["candidates"]) for item in vendor_results),
            "unavailable_sources_written_or_reported": sum(len(item["unavailable_sources"]) for item in vendor_results),
        },
        "vendors": vendor_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-discovery")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--vendor-limit", type=int)
    discover.add_argument("--write", action="store_true")
    discover.add_argument("--source-types", help="Comma-separated source types to discover")
    discover.add_argument("--max-urls-per-type", type=int, default=20)
    discover.add_argument("--fetch-timeout", type=float, default=10.0)
    discover.add_argument("--output", type=Path, default=ROOT / "source-discovery-report.json")
    candidate_discover = subparsers.add_parser("discover-vendor-candidates")
    candidate_discover.add_argument("--vendor-candidates", type=Path, required=True)
    candidate_discover.add_argument("--vendor-limit", type=int)
    candidate_discover.add_argument("--source-types", help="Comma-separated source types to discover")
    candidate_discover.add_argument("--max-urls-per-type", type=int, default=20)
    candidate_discover.add_argument("--fetch-timeout", type=float, default=10.0)
    candidate_discover.add_argument("--output", type=Path, default=ROOT / "vendor-candidate-source-discovery-report.json")
    args = parser.parse_args()

    if args.command == "discover-vendor-candidates":
        report = build_vendor_candidate_discovery_report(
            load_json(args.vendor_candidates),
            vendor_limit=args.vendor_limit,
            fetch_timeout=args.fetch_timeout,
            source_types=parse_source_types(args.source_types),
            max_urls_per_type=args.max_urls_per_type,
        )
    else:
        report = build_discovery_report(
            vendor_limit=args.vendor_limit,
            write=args.write,
            fetch_timeout=args.fetch_timeout,
            source_types=parse_source_types(args.source_types),
            max_urls_per_type=args.max_urls_per_type,
        )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
