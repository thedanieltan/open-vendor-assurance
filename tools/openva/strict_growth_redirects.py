from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse

REDIRECT_CANONICALIZED = "redirect_canonicalized"
REDIRECT_CANONICALIZATION_REQUIRED = "redirect_canonicalization_required"
REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED = "redirect_cross_authority_review_required"
REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED = "redirect_generic_or_homepage_rejected"
REDIRECT_SEMANTIC_MISMATCH = "redirect_semantic_mismatch"

REDIRECT_METRIC_KEYS = (
    "redirect_count",
    "redirect_canonicalized_count",
    "redirect_deferred_count",
    "cross_authority_redirect_count",
    "generic_redirect_rejected_count",
    "unresolved_redirect_count",
)


def normalized_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def hostname(value: Any) -> str:
    return (urlparse(str(value or "")).hostname or "").lower()


def host_matches_domain(host: str, domain: str) -> bool:
    normalized_host = host.lower().removeprefix("www.")
    normalized_domain = str(domain or "").lower().removeprefix("www.").lstrip(".")
    return bool(
        normalized_host
        and normalized_domain
        and (normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}"))
    )


def official_domains_from_vendor(vendor: dict[str, Any]) -> list[str]:
    domains: list[str] = []
    for key in ("official_domain_candidate", "official_domain"):
        value = vendor.get(key)
        if value:
            domains.append(str(value))
    for key in ("official_domains", "allowlisted_source_domains", "vendor_controlled_domains"):
        values = vendor.get(key) or []
        if isinstance(values, str):
            values = [values]
        domains.extend(str(value) for value in values if value)
    return list(dict.fromkeys(domain.lower().removeprefix("www.") for domain in domains if domain))


def final_url_is_official(final_url: str, vendor: dict[str, Any]) -> bool:
    final_host = hostname(final_url)
    return any(host_matches_domain(final_host, domain) for domain in official_domains_from_vendor(vendor))


def is_redirecting_source(source: dict[str, Any]) -> bool:
    evidence = source.get("evidence", {}) or {}
    candidate_url = str(source.get("candidate_url") or source.get("source_url") or "")
    final_url = str(evidence.get("final_url") or source.get("final_url") or "")
    return (
        str(evidence.get("verification_status") or source.get("verification_status") or "") == "redirected"
        or bool(candidate_url and final_url and normalized_url(candidate_url) != normalized_url(final_url))
    )


def redirect_decision(vendor: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    evidence = source.get("evidence", {}) or {}
    candidate_url = str(source.get("candidate_url") or "")
    final_url = str(evidence.get("final_url") or source.get("final_url") or "")
    status = str(evidence.get("verification_status") or source.get("verification_status") or "")
    semantic_status = str(evidence.get("semantic_status") or "")

    if status == "homepage_or_generic_redirect":
        return {
            "redirect_status": "rejected",
            "decision": "defer",
            "reason": REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED,
            "candidate_url": candidate_url,
            "final_url": final_url,
        }
    if status == "possible_mismatch" or semantic_status == "mismatch":
        return {
            "redirect_status": "rejected",
            "decision": "defer",
            "reason": REDIRECT_SEMANTIC_MISMATCH,
            "candidate_url": candidate_url,
            "final_url": final_url,
        }
    if status != "redirected" and normalized_url(candidate_url) == normalized_url(final_url):
        return {
            "redirect_status": "not_redirected",
            "decision": "keep",
            "reason": None,
            "candidate_url": candidate_url,
            "final_url": final_url,
        }
    if not final_url:
        return {
            "redirect_status": "unresolved",
            "decision": "defer",
            "reason": REDIRECT_CANONICALIZATION_REQUIRED,
            "candidate_url": candidate_url,
            "final_url": final_url,
        }
    if normalized_url(candidate_url) == normalized_url(final_url):
        return {
            "redirect_status": "canonical",
            "decision": "keep",
            "reason": None,
            "candidate_url": candidate_url,
            "final_url": final_url,
        }
    if not final_url_is_official(final_url, vendor):
        return {
            "redirect_status": "cross_authority_review_required",
            "decision": "defer",
            "reason": REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED,
            "candidate_url": candidate_url,
            "final_url": final_url,
        }
    return {
        "redirect_status": "canonicalized",
        "decision": "canonicalize",
        "reason": REDIRECT_CANONICALIZED,
        "candidate_url": candidate_url,
        "final_url": final_url,
    }


def materialize_redirect_for_strict_growth(
    vendor: dict[str, Any],
    source: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    decision = redirect_decision(vendor, source)
    materialized = {**source}
    evidence = dict(source.get("evidence", {}) or {})
    evidence["redirect_status"] = decision["redirect_status"]
    evidence["redirect_decision"] = decision["decision"]
    evidence["redirect_reason"] = decision["reason"]
    if decision["decision"] == "canonicalize":
        evidence["original_candidate_url"] = source.get("candidate_url")
        materialized["candidate_url"] = decision["final_url"]
    materialized["evidence"] = evidence
    return materialized, decision


def canonical_clean_reasons(action: dict[str, Any]) -> list[str]:
    source = action.get("source", {}) or {}
    evidence = source.get("evidence", {}) or {}
    candidate_url = str(source.get("candidate_url") or "")
    final_url = str(evidence.get("final_url") or "")
    redirect_status = str(evidence.get("redirect_status") or "")
    redirect_reason = str(evidence.get("redirect_reason") or "")
    status = str(evidence.get("verification_status") or "")

    if status == "homepage_or_generic_redirect" or redirect_reason == REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED:
        return [REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED]
    if status == "possible_mismatch" or redirect_reason == REDIRECT_SEMANTIC_MISMATCH:
        return [REDIRECT_SEMANTIC_MISMATCH]
    if status == "redirected" and normalized_url(candidate_url) != normalized_url(final_url):
        if redirect_status == "cross_authority_review_required" or redirect_reason == REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED:
            return [REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED]
        return [REDIRECT_CANONICALIZATION_REQUIRED]
    return []


def redirect_metrics_for_actions(
    actions: list[dict[str, Any]],
    deferred_actions: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for action in actions:
        source = action.get("source", {}) or {}
        evidence = source.get("evidence", {}) or {}
        if evidence.get("verification_status") == "redirected" or evidence.get("redirect_status") in {
            "canonicalized",
            "cross_authority_review_required",
            "unresolved",
        }:
            counts["redirect_count"] += 1
        if evidence.get("redirect_reason") == REDIRECT_CANONICALIZED:
            counts["redirect_canonicalized_count"] += 1
    for row in deferred_actions or []:
        reason_codes = set(row.get("reason_codes", []) or [])
        action = row.get("action", {}) or {}
        evidence = ((action.get("source", {}) or {}).get("evidence", {}) or {})
        if reason_codes & {
            REDIRECT_CANONICALIZATION_REQUIRED,
            REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED,
            REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED,
            REDIRECT_SEMANTIC_MISMATCH,
        } or evidence.get("verification_status") == "redirected":
            counts["redirect_count"] += 1
            counts["redirect_deferred_count"] += 1
        if REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED in reason_codes:
            counts["cross_authority_redirect_count"] += 1
        if REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED in reason_codes:
            counts["generic_redirect_rejected_count"] += 1
        if reason_codes & {REDIRECT_CANONICALIZATION_REQUIRED, REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED}:
            counts["unresolved_redirect_count"] += 1
    return {key: counts.get(key, 0) for key in REDIRECT_METRIC_KEYS}
