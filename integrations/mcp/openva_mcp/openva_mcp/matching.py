"""Inventory matching over the verified vendor index.

Identity-only matching: an exact official-domain hit, a subdomain of an official
domain, or an exact normalized-name hit. Insufficient evidence stays
``unmatched``; competing equally-strong candidates stay ``ambiguous``. The
matcher never silently picks a vendor when identity evidence is weak — that is a
deliberate safety boundary, since a wrong silent match would misattribute public
assurance sources to the wrong company.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

MINIMUM_MATCH_CONFIDENCE = 0.90
AMBIGUITY_MARGIN = 0.05


@dataclass(frozen=True)
class Candidate:
    vendor_id: str
    canonical_name: str
    confidence: float
    method: str


def normalize_domain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        domain = urlsplit(raw).netloc
    else:
        domain = re.split(r"[/#?]", raw, maxsplit=1)[0]
    domain = domain.rsplit("@", maxsplit=1)[-1]
    if domain.count(":") == 1:
        domain = domain.split(":", maxsplit=1)[0]
    domain = domain.strip().rstrip(".")
    return domain[4:] if domain.startswith("www.") else domain


def normalize_name(value: str | None) -> str:
    raw = (value or "").strip().lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", raw).split())


def _name_keys(vendor: dict[str, Any]) -> set[str]:
    vendor_id = str(vendor.get("vendor_id") or "")
    keys = {
        normalize_name(vendor_id),
        normalize_name(vendor_id.replace("-", " ")),
        normalize_name(vendor.get("canonical_name")),
    }
    return {key for key in keys if key}


def _candidate_for(vendor: dict[str, Any], domain: str, name: str) -> Candidate | None:
    domains = [normalize_domain(d) for d in vendor.get("domains") or []]
    domains = [d for d in domains if d]
    name_keys = _name_keys(vendor)
    vendor_id = str(vendor.get("vendor_id") or "")
    canonical_name = str(vendor.get("canonical_name") or "")
    if domain:
        if domain in domains:
            return Candidate(vendor_id, canonical_name, 1.00, "domain_exact")
        if any(domain.endswith(f".{d}") for d in domains):
            return Candidate(vendor_id, canonical_name, 0.95, "domain_subdomain")
    if name and name in name_keys:
        return Candidate(vendor_id, canonical_name, 0.90, "name_exact")
    return None


def match_row(vendors: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    """Match a single inventory row against the vendor index rows."""
    domain = normalize_domain(row.get("domain"))
    name = normalize_name(row.get("vendor_name")) or normalize_name(row.get("business_entity_name"))

    best: dict[str, Candidate] = {}
    for vendor in vendors:
        candidate = _candidate_for(vendor, domain, name)
        if candidate and candidate.confidence >= MINIMUM_MATCH_CONFIDENCE:
            current = best.get(candidate.vendor_id)
            if current is None or candidate.confidence > current.confidence:
                best[candidate.vendor_id] = candidate

    candidates = sorted(best.values(), key=lambda c: (-c.confidence, c.vendor_id))
    candidate_json = [
        {"vendor_id": c.vendor_id, "canonical_name": c.canonical_name, "confidence": c.confidence, "method": c.method}
        for c in candidates
    ]

    if not candidates:
        status, selected = "unmatched", None
    elif len(candidates) == 1:
        status, selected = "matched", candidates[0]
    elif candidates[0].confidence - candidates[1].confidence < AMBIGUITY_MARGIN:
        # Two equally strong identities: stay ambiguous, do not pick one.
        status, selected = "ambiguous", None
    else:
        status, selected = "matched", candidates[0]

    return {
        "input": row,
        "match_status": status,
        "matched_vendor_id": selected.vendor_id if selected else None,
        "matched_canonical_name": selected.canonical_name if selected else None,
        "match_confidence": selected.confidence if selected else None,
        "match_method": selected.method if selected else None,
        "candidates": candidate_json,
    }
