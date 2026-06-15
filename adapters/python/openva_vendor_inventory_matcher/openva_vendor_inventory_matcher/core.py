"""Shared vendor-identity and legal-entity matching core.

This is the single authority for OpenVA inventory matching decisions. It works
on normalized records and has no CSV or pack dependency, so both the CSV adapter
(``matcher.py``) and the MCP adapter (``openva_mcp.matching``) make the same
decision for the same evidence. Adapters own input parsing and output
formatting only; the match status, vendor id, confidence, method, candidate set,
and legal-entity resolution come from here.

Insufficient evidence stays ``no_match``; equally strong competing identities
stay ``ambiguous``. The matcher never silently picks a vendor when identity
evidence is weak — a wrong silent match would misattribute public assurance
sources to the wrong company.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

MINIMUM_MATCH_CONFIDENCE = 0.90
AMBIGUITY_MARGIN = 0.05

# Match status vocabulary (shared by every adapter).
STATUS_MATCHED = "matched"
STATUS_NO_MATCH = "no_match"
STATUS_AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class VendorRecord:
    vendor_id: str
    display_name: str
    legal_name: str
    catalog_status: str
    official_domains: list[str]
    manifest_path: str
    name_keys: frozenset[str]


@dataclass(frozen=True)
class LegalEntityRecord:
    entity_id: str
    vendor_id: str
    legal_name: str
    jurisdiction: str
    registration_number: str
    catalog_status: str
    registered_address: dict[str, Any] | None


@dataclass(frozen=True)
class MatchCandidate:
    vendor: VendorRecord
    confidence: float
    method: str


@dataclass(frozen=True)
class LegalEntityResolution:
    method: str
    confidence: str
    matched_entity: LegalEntityRecord | None
    candidates: list[LegalEntityRecord]


# --- normalization --------------------------------------------------------


def normalize_domain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        parsed = urlsplit(raw)
        domain = parsed.netloc
    else:
        domain = re.split(r"[/#?]", raw, maxsplit=1)[0]
    domain = domain.rsplit("@", maxsplit=1)[-1]
    if ":" in domain and domain.count(":") == 1:
        domain = domain.split(":", maxsplit=1)[0]
    domain = domain.strip().rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def normalize_jurisdiction(value: str | None) -> str:
    return (value or "").strip().upper()


def normalize_name(value: str | None) -> str:
    raw = (value or "").strip().lower()
    raw = raw.replace("&", " and ")
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    return " ".join(raw.split())


def strip_legal_suffixes(value: str | None) -> str:
    tokens = normalize_name(value).split()
    suffixes = {"inc", "llc", "ltd", "limited", "corp", "corporation", "company", "co"}
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def normalize_registration_number(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value or "").upper()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# --- record construction --------------------------------------------------


def vendor_record(row: dict[str, Any]) -> VendorRecord:
    vendor_id = scalar(row.get("vendor_id"))
    display_name = scalar(row.get("display_name"))
    legal_name = scalar(row.get("legal_name"))
    domains = [domain for domain in [normalize_domain(value) for value in row.get("official_domains", [])] if domain]
    name_keys = {normalize_name(value) for value in [vendor_id, display_name, legal_name, vendor_id.replace("-", " ")]}
    name_keys.add(strip_legal_suffixes(legal_name))
    return VendorRecord(
        vendor_id=vendor_id,
        display_name=display_name,
        legal_name=legal_name,
        catalog_status=scalar(row.get("catalog_status", row.get("status"))),
        official_domains=domains,
        manifest_path=scalar(row.get("manifest_path")),
        name_keys=frozenset(key for key in name_keys if key),
    )


def legal_entity_record(row: dict[str, Any]) -> LegalEntityRecord:
    registered_address = row.get("registered_address")
    return LegalEntityRecord(
        entity_id=scalar(row.get("entity_id")),
        vendor_id=scalar(row.get("vendor_id")),
        legal_name=scalar(row.get("legal_name")),
        jurisdiction=normalize_jurisdiction(row.get("jurisdiction", "")),
        registration_number=scalar(row.get("registration_number")),
        catalog_status=scalar(row.get("catalog_status")),
        registered_address=registered_address if isinstance(registered_address, dict) else None,
    )


# --- identity matching ----------------------------------------------------


def candidate_for_vendor(vendor: VendorRecord, domain: str, name: str) -> MatchCandidate | None:
    if domain:
        for official_domain in vendor.official_domains:
            if domain == official_domain:
                return MatchCandidate(vendor, 1.00, "domain_exact")
        for official_domain in vendor.official_domains:
            if domain.endswith(f".{official_domain}"):
                return MatchCandidate(vendor, 0.95, "domain_subdomain")
    if name and name in vendor.name_keys:
        return MatchCandidate(vendor, 0.90, "name_exact")
    return None


def match_candidates(vendors: list[VendorRecord], domain: str, name: str) -> list[MatchCandidate]:
    candidates: dict[str, MatchCandidate] = {}
    for vendor in vendors:
        candidate = candidate_for_vendor(vendor, domain, name)
        if candidate and candidate.confidence >= MINIMUM_MATCH_CONFIDENCE:
            current = candidates.get(vendor.vendor_id)
            if current is None or candidate.confidence > current.confidence:
                candidates[vendor.vendor_id] = candidate
    return sorted(candidates.values(), key=lambda item: (-item.confidence, item.vendor.vendor_id))


def select_match(candidates: list[MatchCandidate]) -> MatchCandidate | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    first, second = candidates[0], candidates[1]
    if first.confidence == second.confidence or first.confidence - second.confidence < AMBIGUITY_MARGIN:
        return None
    return first


def classify(candidates: list[MatchCandidate], selected: MatchCandidate | None) -> str:
    if selected is not None:
        return STATUS_MATCHED
    return STATUS_AMBIGUOUS if candidates else STATUS_NO_MATCH


# --- legal-entity resolution ----------------------------------------------


def sorted_legal_entities(rows: list[LegalEntityRecord]) -> list[LegalEntityRecord]:
    return sorted(rows, key=lambda row: (row.vendor_id, row.jurisdiction, row.entity_id))


def group_legal_entities_by_vendor(rows: list[LegalEntityRecord]) -> dict[str, list[LegalEntityRecord]]:
    grouped: dict[str, list[LegalEntityRecord]] = {}
    for row in rows:
        grouped.setdefault(row.vendor_id, []).append(row)
    return {vendor_id: sorted_legal_entities(items) for vendor_id, items in grouped.items()}


def group_legal_entities_by_registration(rows: list[LegalEntityRecord]) -> dict[str, list[LegalEntityRecord]]:
    grouped: dict[str, list[LegalEntityRecord]] = {}
    for row in rows:
        registration_number = normalize_registration_number(row.registration_number)
        if registration_number:
            grouped.setdefault(registration_number, []).append(row)
    return {registration_number: sorted_legal_entities(items) for registration_number, items in grouped.items()}


def resolve_legal_entity(
    input_row: dict[str, str],
    selected_vendor: VendorRecord | None,
    *,
    by_registration: dict[str, list[LegalEntityRecord]],
    by_id: dict[str, LegalEntityRecord],
    contracting_by_key: dict[tuple[str, str], dict[str, Any]],
) -> LegalEntityResolution:
    registration_number = normalize_registration_number(input_row.get("registration_number", ""))
    jurisdiction = normalize_jurisdiction(input_row.get("jurisdiction", ""))
    if registration_number:
        matches = by_registration.get(registration_number, [])
        if jurisdiction:
            matches = [entity for entity in matches if entity.jurisdiction == jurisdiction]
        if len(matches) == 1:
            return LegalEntityResolution("registration_number_exact", "matched", matches[0], matches)
        if len(matches) > 1:
            return LegalEntityResolution("registration_number_exact", "ambiguous", None, sorted_legal_entities(matches))

    if selected_vendor is not None and jurisdiction:
        resolution = contracting_by_key.get((selected_vendor.vendor_id, jurisdiction))
        if resolution is not None:
            candidate_ids = list_value(resolution.get("candidate_entity_ids"))
            candidates = sorted_legal_entities(
                [by_id[entity_id] for entity_id in candidate_ids if isinstance(entity_id, str) and entity_id in by_id]
            )
            resolved_entity_id = resolution.get("resolved_entity_id")
            matched_entity = by_id.get(resolved_entity_id) if isinstance(resolved_entity_id, str) else None
            if matched_entity is not None and matched_entity not in candidates:
                candidates = sorted_legal_entities([matched_entity, *candidates])
            status = scalar(resolution.get("resolution_status"))
            confidence = "ambiguous" if status == "ambiguous" else "candidate"
            return LegalEntityResolution("jurisdiction_resolution_index", confidence, matched_entity, candidates)

    return LegalEntityResolution("unresolved", "unresolved", None, [])
