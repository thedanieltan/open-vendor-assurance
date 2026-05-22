from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

RECOGNIZED_SOURCE_TYPES = {
    "dpa",
    "subprocessors_list",
    "privacy_notice",
    "trust_center",
    "security_page",
    "compliance_page",
    "certification_reference",
    "terms_of_service",
    "kyc_statement",
    "aml_statement",
    "ai_terms",
    "government_request_policy",
    "transparency_report",
    "other_public_source",
}

SOURCE_TYPE_TERMS = {
    "dpa": ["dpa", "data processing", "data-processing", "data protection addendum"],
    "subprocessors_list": ["subprocessor", "sub-processors", "sub processors"],
    "privacy_notice": ["privacy", "privacy notice", "privacy policy"],
    "trust_center": ["trust", "trust center", "trust centre"],
    "security_page": ["security", "secure", "trust"],
    "compliance_page": ["compliance", "compliant", "regulatory"],
    "certification_reference": ["certification", "certificate", "iso", "soc"],
    "terms_of_service": ["terms", "terms of service", "terms of use"],
    "kyc_statement": ["kyc", "know your customer"],
    "aml_statement": ["aml", "anti-money laundering"],
    "ai_terms": ["ai", "artificial intelligence", "model"],
    "government_request_policy": ["government request", "law enforcement"],
    "transparency_report": ["transparency", "transparency report"],
    "other_public_source": [],
}

GATED_STATUSES = {
    "login_required",
    "gated_or_login_required",
    "bot_protected",
    "rate_limited",
    "form_gated",
    "captcha_required",
    "private_portal",
    "credentialed_access_required",
    "nda_required",
}

SUCCESS_STATUSES = {
    "ok",
    "success",
    "reachable",
    "verified",
    "fetch_ok",
    "public",
    "same_domain_redirect",
}

ADVISORY_RE = re.compile(
    r"\b(approved|recommended|safe vendor|unsafe vendor|low risk|high risk|"
    r"compliant|non-compliant|legally adequate|procurement ready|"
    r"certified as compliant|sanctions clear)\b",
    re.IGNORECASE,
)

FULL_TEXT_FIELDS = {
    "raw_text",
    "document_text",
    "full_text",
    "extracted_text",
    "page_text",
    "html",
    "pdf_text",
}


def _value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _candidate_url(candidate: dict[str, Any]) -> str:
    return str(_value(candidate, "candidate_url", "source_url", "url") or "")


def _source_type(candidate: dict[str, Any]) -> str:
    return str(_value(candidate, "source_type_candidate", "source_type") or "")


def _status(verification_result: dict[str, Any]) -> str:
    return str(_value(verification_result, "verification_status", "result", "status") or "").lower()


def _http_status(verification_result: dict[str, Any]) -> int | None:
    value = _value(verification_result, "http_status", "status_code")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _final_url(candidate: dict[str, Any], verification_result: dict[str, Any]) -> str:
    return str(_value(verification_result, "final_url", "url") or _candidate_url(candidate))


def _host(url: str) -> str:
    return urlparse(url).hostname or ""


def _registrable_domain(host: str) -> str:
    parts = [part for part in host.lower().split(".") if part]
    if len(parts) < 2:
        return host.lower()
    return ".".join(parts[-2:])


def _host_matches_domain(host: str, domain: str) -> bool:
    host = host.lower()
    domain = domain.lower().lstrip(".")
    return host == domain or host.endswith(f".{domain}")


def _vendor_domains(vendor: dict[str, Any]) -> list[str]:
    domains = vendor.get("official_domains") or vendor.get("domains") or []
    if isinstance(domains, str):
        domains = [domains]
    return [str(domain).lower().lstrip(".") for domain in domains if domain]


def _vendor_controlled_domains(vendor: dict[str, Any]) -> list[str]:
    domains = _vendor_domains(vendor)
    allowlisted = vendor.get("allowlisted_source_domains") or vendor.get("vendor_controlled_domains") or []
    domains.extend(str(domain).lower().lstrip(".") for domain in allowlisted if domain)
    return domains


def _safe_final_host(candidate_url: str, final_url: str, vendor: dict[str, Any]) -> bool:
    candidate_host = _host(candidate_url)
    final_host = _host(final_url)
    if not candidate_host or not final_host:
        return False
    if candidate_host == final_host:
        return True
    if _registrable_domain(candidate_host) == _registrable_domain(final_host):
        return True
    return any(
        _host_matches_domain(final_host, domain) for domain in _vendor_controlled_domains(vendor)
    )


def _on_vendor_domain(url: str, vendor: dict[str, Any]) -> bool:
    host = _host(url)
    domains = _vendor_controlled_domains(vendor)
    return bool(host and domains and any(_host_matches_domain(host, domain) for domain in domains))


def _evidence_text(candidate: dict[str, Any], verification_result: dict[str, Any]) -> str:
    parts: list[str] = []
    for record in (candidate, verification_result):
        for key in (
            "candidate_url",
            "source_url",
            "url",
            "final_url",
            "title",
            "title_en",
            "title_native",
            "page_title",
            "content_snippet",
            "snippet",
            "matched_terms",
        ):
            value = record.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            elif value:
                parts.append(str(value))
    return " ".join(parts).lower()


def _has_source_type_evidence(
    source_type: str, candidate: dict[str, Any], verification_result: dict[str, Any]
) -> bool:
    if source_type == "other_public_source":
        return bool(_evidence_text(candidate, verification_result).strip())
    terms = SOURCE_TYPE_TERMS.get(source_type, [])
    evidence = _evidence_text(candidate, verification_result)
    return any(term in evidence for term in terms)


def _has_full_text(record: dict[str, Any]) -> bool:
    for key in FULL_TEXT_FIELDS:
        value = record.get(key)
        if isinstance(value, str) and len(value.strip()) > 300:
            return True
        if value:
            return True
    return False


def _has_advisory_wording(candidate: dict[str, Any], verification_result: dict[str, Any]) -> bool:
    fields = []
    for record in (candidate, verification_result):
        for key in ("title", "title_en", "title_native", "summary", "summary_en", "notes", "description"):
            value = record.get(key)
            if value:
                fields.append(str(value))
    return bool(ADVISORY_RE.search(" ".join(fields)))


def _verification_successful(verification_result: dict[str, Any]) -> bool:
    status = _status(verification_result)
    http_status = _http_status(verification_result)
    if status in GATED_STATUSES:
        return False
    if status in SUCCESS_STATUSES:
        return True
    return http_status is not None and 200 <= http_status < 300


def is_machine_canonical_eligible(
    candidate: dict[str, Any],
    vendor: dict[str, Any],
    verification_result: dict[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    vendor_id = vendor.get("vendor_id")
    if not vendor_id:
        reasons.append("vendor_missing")
    elif candidate.get("vendor_id") and candidate.get("vendor_id") != vendor_id:
        reasons.append("vendor_mismatch")

    candidate_url = _candidate_url(candidate)
    final_url = _final_url(candidate, verification_result)
    if not candidate_url:
        reasons.append("candidate_url_missing")
    elif urlparse(candidate_url).scheme != "https":
        reasons.append("candidate_url_not_https")

    if final_url and urlparse(final_url).scheme != "https":
        reasons.append("final_url_not_https")

    source_type = _source_type(candidate)
    if source_type not in RECOGNIZED_SOURCE_TYPES:
        reasons.append("unknown_source_type")

    status = _status(verification_result)
    if status in GATED_STATUSES:
        reasons.append(f"gated_or_blocked:{status}")

    if not _verification_successful(verification_result):
        reasons.append("verification_not_successful")

    if candidate_url and final_url and not _safe_final_host(candidate_url, final_url, vendor):
        reasons.append("unsafe_redirect_or_non_vendor_domain")

    if final_url and not _on_vendor_domain(final_url, vendor):
        reasons.append("final_url_not_on_vendor_domain")

    if source_type in RECOGNIZED_SOURCE_TYPES and not _has_source_type_evidence(
        source_type, candidate, verification_result
    ):
        reasons.append("source_type_evidence_missing")

    if _has_full_text(candidate) or _has_full_text(verification_result):
        reasons.append("raw_or_extracted_full_text_present")

    if _has_advisory_wording(candidate, verification_result):
        reasons.append("advisory_wording_present")

    return not reasons, reasons


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "source"


def build_machine_validated_source(
    candidate: dict[str, Any],
    vendor: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    eligible, reasons = is_machine_canonical_eligible(candidate, vendor, verification_result)
    if not eligible:
        raise ValueError(";".join(reasons))

    vendor_id = str(vendor["vendor_id"])
    source_type = _source_type(candidate)
    source_id = str(
        candidate.get("source_id")
        or candidate.get("candidate_source_id")
        or f"{vendor_id}-{source_type}"
    )
    source_id = _slug(source_id.replace("-candidate", ""))

    collected_at = str(
        _value(verification_result, "observed_at", "collected_at")
        or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    title = str(
        _value(candidate, "title_native", "title_en", "title")
        or _value(verification_result, "page_title", "title")
        or source_type.replace("_", " ").title()
    )

    return {
        "schema_version": str(candidate.get("schema_version") or "0.1.0"),
        "catalog_tier": "machine_validated",
        "review_state": "auto_validated",
        "advisory_boundary": "non_advisory",
        "source_id": source_id,
        "vendor_id": vendor_id,
        "source_type": source_type,
        "title_native": title,
        "title_en": candidate.get("title_en") or title,
        "source_url": _final_url(candidate, verification_result),
        "source_language": str(candidate.get("source_language") or "en"),
        "effective_or_published_at": candidate.get("effective_or_published_at"),
        "source_authority_class": str(candidate.get("source_authority_class") or "vendor_published"),
        "access_class": str(candidate.get("access_class") or "public_web"),
        "rights_class": str(candidate.get("rights_class") or "metadata_only"),
        "summary_native": None,
        "summary_en": None,
        "provenance": {
            "publisher": "vendor",
            "collected_at": collected_at,
            "observer": "agent",
            "confidence": "high",
        },
        "not_advice": True,
    }