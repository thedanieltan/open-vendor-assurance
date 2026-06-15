"""Tier A: structured authority-provenance invariants.

Locator discovered != authority proven. A discovered URL is only treated as
vendor-authorized when its `authority` object records a reconstructable,
content-anchored or governed basis. CNAME and TLS relationships are
corroboration only and never establish authority by themselves
(dangling-CNAME / forgotten-subdomain takeover risk). Off-domain targets
require a strong, content-anchored or governed method.

The JSON Schema enforces class/method coherence; this module adds the
domain-contextual rules a schema cannot express (it needs the vendor's official
domains) and is the single authority for the `establishes_authority` decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from tools.openva.indexes import ROOT

_VOCAB_PATH = ROOT / "config" / "controlled-vocabulary.yaml"

# Content-anchored or governed signals that may stand alone as strong authority.
STRONG_METHODS = (
    "same_official_domain",
    "official_domain_link",
    "official_domain_redirect",
    "official_vendor_manifest",
    "manual_exception",
)
# Off-domain authority cannot rest on same_official_domain (that is on-domain by
# definition) — it needs a link/redirect/manifest/exception proving delegation.
OFF_DOMAIN_STRONG_METHODS = (
    "official_domain_link",
    "official_domain_redirect",
    "official_vendor_manifest",
    "manual_exception",
)
CORROBORATING_METHODS = ("cname_corroboration", "tls_corroboration")


def _vocab() -> dict[str, Any]:
    return yaml.safe_load(_VOCAB_PATH.read_text(encoding="utf-8"))


def normalize_host(url: str | None) -> str:
    host = urlsplit(url or "").netloc.lower()
    host = host.rsplit("@", maxsplit=1)[-1]
    if host.count(":") == 1:
        host = host.split(":", maxsplit=1)[0]
    host = host.strip().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def is_on_official_domain(url: str | None, official_domains: list[str]) -> bool:
    host = normalize_host(url)
    if not host:
        return False
    for domain in official_domains:
        domain = (domain or "").strip().lower().rstrip(".")
        if not domain:
            continue
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def establishes_authority(authority: dict[str, Any] | None) -> bool:
    """Only a strong authority object establishes vendor authority on its own."""
    return bool(authority) and authority.get("class") == "strong"


def validate_authority(authority: dict[str, Any] | None, official_domains: list[str]) -> list[str]:
    """Return reasons the authority object is invalid (empty list = valid).

    Fails closed: an unrecognized class/method, a corroboration-only method
    claimed as strong, or an off-domain target without a content-anchored strong
    method is rejected.
    """
    if authority is None:
        return []
    reasons: list[str] = []
    cls = authority.get("class")
    method = authority.get("method")
    target = authority.get("target_url")

    if cls not in {"strong", "corroborating", "unproven"}:
        reasons.append(f"authority_class_unknown:{cls}")
    if method not in STRONG_METHODS + CORROBORATING_METHODS:
        reasons.append(f"authority_method_unknown:{method}")
    if not target:
        reasons.append("authority_target_url_missing")

    # Corroboration-only methods can never be strong.
    if method in CORROBORATING_METHODS and cls == "strong":
        reasons.append("authority_corroboration_claimed_strong")
    # A strong class must use a strong method.
    if cls == "strong" and method not in STRONG_METHODS:
        reasons.append("authority_strong_requires_strong_method")

    # Off-domain target: only a content-anchored / governed strong method proves
    # delegation; same_official_domain and corroboration are insufficient.
    if target and not is_on_official_domain(target, official_domains):
        if cls != "strong" or method not in OFF_DOMAIN_STRONG_METHODS:
            reasons.append("authority_off_domain_requires_strong_content_anchored_method")

    return reasons
