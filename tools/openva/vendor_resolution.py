"""Unified vendor resolution: catalogue-first, live-refresh-on-use.

This module is the single synchronous entry point that turns a vendor request
(from a browser upload, an API caller, an agent, or a future MCP server) into the
best current public-source result OpenVA can establish, while routing every
discovered gap or stale source into the *existing* autonomous catalogue-growth
lifecycle.

It does not introduce a new advisory or scoring system and it never writes
canonical catalogue files. It composes machinery that already exists:

- vendor identity matching: ``openva_vendor_inventory_matcher.core`` (the single
  matching authority, shared with the CSV and MCP adapters);
- source health + safety: :mod:`tools.openva.source_verification` and
  :mod:`tools.openva.url_safety` (fail-closed on unsafe URLs);
- candidate emission: :mod:`tools.openva.candidate_record` (deterministic ids,
  evidence digests, and the one fail-closed eligibility evaluator that every
  origin must pass through).

Resolution result vocabulary (one small, consistent set):

    catalog_current          catalogue source checked and still valid
    catalog_refreshed        catalogue source stale/moved/broken; replacement found
    newly_discovered         vendor/source absent from catalogue; found live
    source_unavailable       existing source unavailable, no replacement found
    not_found                no catalogue match and no suitable public source
    identity_ambiguous       multiple plausible vendor identities/domains
    verification_inconclusive  no reliable current result could be established
    candidate_processing     a discovered/refreshed source entered the lifecycle
    catalogued               candidate passed promotion controls; now canonical

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice. OpenVA preserves source-reference and
observation history; it does not archive or reproduce historical vendor
documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from tools.openva import candidate_record
from tools.openva.indexes import ROOT
from tools.openva.source_verification import (
    FetchResult,
    classify_status,
    fetch_url,
    normalize_text,
    semantic_match,
)
from tools.openva.url_safety import validate_url_safety

# Import the shared matching authority without duplicating it.
_ADAPTER_PATH = ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher"
if str(_ADAPTER_PATH) not in sys.path:
    sys.path.insert(0, str(_ADAPTER_PATH))
from openva_vendor_inventory_matcher import core as matcher  # noqa: E402

SCHEMA_VERSION = "0.1.0"
SCHEMA_PATH = ROOT / "schemas" / "openva" / "vendor-resolution-result.schema.json"

# --- result-state vocabulary ------------------------------------------------

RESULT_CATALOG_CURRENT = "catalog_current"
RESULT_CATALOG_REFRESHED = "catalog_refreshed"
RESULT_NEWLY_DISCOVERED = "newly_discovered"
RESULT_SOURCE_UNAVAILABLE = "source_unavailable"
RESULT_NOT_FOUND = "not_found"
RESULT_IDENTITY_AMBIGUOUS = "identity_ambiguous"
RESULT_VERIFICATION_INCONCLUSIVE = "verification_inconclusive"
RESULT_CANDIDATE_PROCESSING = "candidate_processing"
RESULT_CATALOGUED = "catalogued"

RESULT_STATES = (
    RESULT_CATALOG_CURRENT,
    RESULT_CATALOG_REFRESHED,
    RESULT_NEWLY_DISCOVERED,
    RESULT_SOURCE_UNAVAILABLE,
    RESULT_NOT_FOUND,
    RESULT_IDENTITY_AMBIGUOUS,
    RESULT_VERIFICATION_INCONCLUSIVE,
    RESULT_CANDIDATE_PROCESSING,
    RESULT_CATALOGUED,
)

# Vendor-level rollup precedence (higher index wins). identity_ambiguous is
# handled before this list because it is a property of the vendor, not a source.
_ROLLUP_PRECEDENCE = (
    RESULT_VERIFICATION_INCONCLUSIVE,
    RESULT_NOT_FOUND,
    RESULT_SOURCE_UNAVAILABLE,
    RESULT_CATALOG_CURRENT,
    RESULT_NEWLY_DISCOVERED,
    RESULT_CATALOG_REFRESHED,
)

# --- freshness modes --------------------------------------------------------

FRESHNESS_CACHED = "cached"
FRESHNESS_VERIFY = "verify"
FRESHNESS_MODES = (FRESHNESS_CACHED, FRESHNESS_VERIFY)

# Stored catalogue source-health buckets, mapped to a cached-mode result.
_CACHED_HEALTH_RESULT = {
    "ok": RESULT_CATALOG_CURRENT,
    None: RESULT_CATALOG_CURRENT,
    "stale": RESULT_VERIFICATION_INCONCLUSIVE,
    "gated": RESULT_VERIFICATION_INCONCLUSIVE,
    "unknown": RESULT_VERIFICATION_INCONCLUSIVE,
    "moved": RESULT_SOURCE_UNAVAILABLE,
    "broken": RESULT_SOURCE_UNAVAILABLE,
    "retired": RESULT_SOURCE_UNAVAILABLE,
}

# Live verification statuses (from classify_status) and how they route.
_VERIFY_CURRENT = {"ok"}
_VERIFY_MOVED = {"redirected", "homepage_or_generic_redirect"}
_VERIFY_BROKEN = {
    "not_found",
    "gone",
    "unreachable",
    "server_error",
    "client_error",
    "soft_not_found",
}
_VERIFY_INCONCLUSIVE = {
    "gated_or_login_required",
    "bot_protected",
    "rate_limited",
    "forbidden_unknown",
    "possible_mismatch",
    "suspect_inferred_url",
}

# Resolution channel -> existing candidate_record origin enum. The channel is the
# *how it was requested*; the origin enum is the *kind of catalogue change*. The
# channel is preserved in discovery_component so it never reduces verification.
CHANNELS = (
    "public_matcher_discovery",
    "agent_resolution",
    "api_resolution",
    "scheduled_discovery",
    "human_submission",
)
DEFAULT_CHANNEL = "public_matcher_discovery"

# Source candidate path templates per source type, used by the default bounded
# discovery to propose vendor-published URLs on the official domain only.
_DISCOVERY_PATHS: dict[str, tuple[str, ...]] = {
    "dpa": ("legal/dpa", "legal/data-processing-addendum", "dpa"),
    "subprocessors_list": ("legal/subprocessors", "subprocessors", "legal/sub-processors"),
    "privacy_notice": ("privacy", "legal/privacy", "privacy-policy"),
    "security_page": ("security", "trust/security"),
    "compliance_page": ("compliance", "trust/compliance"),
    "trust_center": ("trust", "trust-center", "security"),
    "status_page": ("status",),
}

def _now_default() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# --- catalogue access -------------------------------------------------------


@dataclass(frozen=True)
class CatalogSource:
    """A canonical (catalogued) source the catalogue already holds."""

    source_id: str
    source_type: str
    source_url: str
    health_status: str | None = None
    observed_at: str | None = None


@dataclass(frozen=True)
class ResolutionCatalog:
    """In-memory view of the catalogue the resolver reads (never writes)."""

    snapshot: dict[str, str]
    vendor_rows: list[dict[str, Any]]
    sources_by_vendor: dict[str, list[CatalogSource]]

    def vendor_records(self) -> list[matcher.VendorRecord]:
        return [matcher.vendor_record(row) for row in self.vendor_rows]

    def display_row(self, vendor_id: str) -> dict[str, Any]:
        for row in self.vendor_rows:
            if str(row.get("vendor_id")) == vendor_id:
                return row
        return {}

    def sources_for(self, vendor_id: str) -> list[CatalogSource]:
        return list(self.sources_by_vendor.get(vendor_id, []))

    @classmethod
    def from_indexes(cls, root: Path = ROOT) -> "ResolutionCatalog":
        """Load the catalogue from generated indexes (read-only)."""
        match_index = _load_json(root / "indexes" / "vendor-match-index.json")
        sources_index = _load_json(root / "indexes" / "sources.json")
        pack = _load_json(root / "openva-pack.json")
        commit_sha = _git_head(root)
        snapshot = {
            "catalog_commit_sha": commit_sha,
            "catalog_generated_at": str(pack.get("generated_at") or matcher.scalar(None)),
        }
        vendor_rows: list[dict[str, Any]] = []
        for item in match_index.get("items", []):
            vendor_rows.append(
                {
                    "vendor_id": item.get("vendor_id"),
                    "display_name": item.get("display_name"),
                    "legal_name": item.get("legal_name"),
                    "catalog_status": item.get("catalog_status"),
                    "official_domains": item.get("official_domains", []),
                    "manifest_path": item.get("manifest_path"),
                }
            )
        health_by_source: dict[str, CatalogSource] = {}
        sources_by_vendor: dict[str, list[CatalogSource]] = {}
        for record in sources_index.get("items", []):
            vendor_id = str(record.get("vendor_id") or "")
            source_health = record.get("source_health") or {}
            provenance = record.get("provenance") or {}
            source = CatalogSource(
                source_id=str(record.get("source_id") or ""),
                source_type=str(record.get("source_type") or ""),
                source_url=str(record.get("source_url") or ""),
                health_status=source_health.get("status"),
                observed_at=source_health.get("as_of") or provenance.get("collected_at"),
            )
            health_by_source[source.source_id] = source
            sources_by_vendor.setdefault(vendor_id, []).append(source)
        return cls(snapshot=snapshot, vendor_rows=vendor_rows, sources_by_vendor=sources_by_vendor)


# --- request / result data --------------------------------------------------


@dataclass(frozen=True)
class IdentityResolution:
    status: str  # "matched" | "ambiguous" | "absent"
    vendor_id: str | None
    display_name: str | None
    official_domain: str | None
    candidates: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoveryResult:
    candidate_url: str
    final_url: str
    http_status: int | None
    content_type: str | None
    verification_status: str
    matched_terms: list[str]
    observed_at: str
    on_vendor_domain: bool


@dataclass
class ResolvedSource:
    source_type: str
    status: str
    source_url: str | None = None
    origin: str | None = None  # "catalog" | "live_discovery" | None
    live_checked: bool = False
    checked_at: str | None = None
    catalog_status: str | None = None  # "catalogued" | "candidate_processing" | None
    previous_source_url: str | None = None
    history: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_type": self.source_type,
            "status": self.status,
            "source_url": self.source_url,
            "origin": self.origin,
            "live_checked": self.live_checked,
            "checked_at": self.checked_at,
            "catalog_status": self.catalog_status,
        }
        if self.previous_source_url is not None:
            payload["previous_source_url"] = self.previous_source_url
        if self.history is not None:
            payload["history"] = self.history
        if self.reasons:
            payload["reasons"] = list(self.reasons)
        return payload


@dataclass
class VendorResolution:
    vendor: dict[str, Any]
    resolution_status: str
    freshness_mode: str
    sources: list[ResolvedSource]
    snapshot: dict[str, str]
    candidates: list[dict[str, Any]] = field(default_factory=list)
    identity_candidates: list[str] = field(default_factory=list)

    def to_response(self) -> dict[str, Any]:
        response = {
            "schema_version": SCHEMA_VERSION,
            "vendor": self.vendor,
            "resolution_status": self.resolution_status,
            "freshness_mode": self.freshness_mode,
            "sources": [source.to_dict() for source in self.sources],
            "snapshot": self.snapshot,
            "not_advice": True,
        }
        if self.identity_candidates:
            response["identity_candidates"] = list(self.identity_candidates)
        return response


# --- idempotent candidate emission ------------------------------------------


class SessionEmitter:
    """Collects discovered/refreshed sources as candidate records.

    Idempotent by construction: the candidate id is derived deterministically
    from (origin, origin_reference), so the same vendor/source discovered by
    many users or agents reuses one in-flight candidate rather than spawning
    duplicates. Emission records candidates only; it never writes canonical
    catalogue files or opens pull requests. Promotion stays with the existing
    autonomous lifecycle.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}
        self._seen_keys: set[str] = set()

    @property
    def candidates(self) -> list[dict[str, Any]]:
        return [self._by_id[key] for key in sorted(self._by_id)]

    def emit(
        self,
        *,
        candidate_origin: str,
        origin_reference: str,
        discovery_component: str,
        vendor_identity_candidate: dict[str, Any],
        source_candidates: list[dict[str, Any]],
        evidence_references: list[dict[str, Any]],
        created_at: str,
        is_new_vendor: bool,
        identity_collision: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        """Return (candidate_record, newly_created). Repeat emits are no-ops."""
        candidate_id = candidate_record.compute_candidate_id(candidate_origin, origin_reference)
        if candidate_id in self._by_id:
            return self._by_id[candidate_id], False

        eligibility_state, reasons = candidate_record.evaluate_eligibility(
            vendor_identity_candidate,
            source_candidates,
            is_new_vendor=is_new_vendor,
            identity_collision=identity_collision,
        )
        clean_identity = {
            key: value
            for key, value in vendor_identity_candidate.items()
            if key != "official_domain_unsafe"
        }
        clean_sources = [_clean_source_candidate(source) for source in source_candidates]
        record = candidate_record.build_candidate(
            candidate_origin=candidate_origin,
            origin_reference=origin_reference,
            vendor_identity_candidate=clean_identity,
            source_candidates=clean_sources,
            evidence_references=evidence_references,
            discovery_component=discovery_component,
            created_at=created_at,
            eligibility_state=eligibility_state,
            decision_reasons=reasons,
        )
        self._by_id[candidate_id] = record
        return record, True


def _clean_source_candidate(source: dict[str, Any]) -> dict[str, Any]:
    leaked = {"source_type_conflict", "authority_proven"}
    return {key: value for key, value in source.items() if key not in leaked}


# --- bounded public discovery -----------------------------------------------

DiscoveryFn = Callable[[str, str, Callable[[str], FetchResult], str], DiscoveryResult | None]


def bounded_discovery(
    official_domain: str,
    source_type: str,
    fetcher: Callable[[str], FetchResult],
    observed_at: str,
) -> DiscoveryResult | None:
    """Try a small, fixed set of vendor-published paths on the official domain.

    Fails closed: only ``https`` URLs on the official domain that pass URL
    safety are fetched, and a candidate is accepted only when the response is
    reachable, on-domain, and semantically consistent with the source type.
    """
    domain = matcher.normalize_domain(official_domain)
    if not domain:
        return None
    for path in _DISCOVERY_PATHS.get(source_type, ()):
        url = f"https://{domain}/{path}"
        if validate_url_safety(url, resolve_dns=True):
            continue  # unsafe target -> never fetched
        result = fetcher(url)
        candidate = _evaluate_fetch(url, source_type, result, observed_at, domain)
        if candidate is not None:
            return candidate
    return None


def _evaluate_fetch(
    candidate_url: str,
    source_type: str,
    result: FetchResult,
    observed_at: str,
    official_domain: str,
) -> DiscoveryResult | None:
    text = normalize_text(result.body_sample, result.content_type)
    semantic = semantic_match(source_type, text, result.content_type)
    status = classify_status({"source_url": candidate_url, "source_type": source_type}, result, semantic)
    final_host = matcher.normalize_domain(result.final_url or candidate_url)
    on_domain = final_host == official_domain or final_host.endswith(f".{official_domain}")
    accepted = (
        status in {"ok", "redirected"}
        and on_domain
        and semantic.get("status") in {"strong", "weak"}
    )
    if not accepted:
        return None
    return DiscoveryResult(
        candidate_url=candidate_url,
        final_url=result.final_url or candidate_url,
        http_status=result.http_status,
        content_type=result.content_type,
        verification_status=status,
        matched_terms=list(semantic.get("matched_terms", [])),
        observed_at=observed_at,
        on_vendor_domain=on_domain,
    )


# --- identity resolution ----------------------------------------------------


def resolve_identity(catalog: ResolutionCatalog, vendor_input: dict[str, Any]) -> IdentityResolution:
    """Resolve the requested vendor against the catalogue using the shared core."""
    domain = matcher.normalize_domain(vendor_input.get("domain"))
    name = matcher.normalize_name(
        vendor_input.get("vendor_name") or vendor_input.get("business_entity_name")
    )
    candidates = matcher.match_candidates(catalog.vendor_records(), domain, name)
    selected = matcher.select_match(candidates)
    status = matcher.classify(candidates, selected)
    if status == matcher.STATUS_MATCHED and selected is not None:
        row = catalog.display_row(selected.vendor.vendor_id)
        official = (selected.vendor.official_domains or [None])[0]
        return IdentityResolution(
            status="matched",
            vendor_id=selected.vendor.vendor_id,
            display_name=row.get("display_name") or selected.vendor.display_name,
            official_domain=official or domain or None,
        )
    if status == matcher.STATUS_AMBIGUOUS:
        return IdentityResolution(
            status="ambiguous",
            vendor_id=None,
            display_name=vendor_input.get("vendor_name"),
            official_domain=domain or None,
            candidates=[candidate.vendor.vendor_id for candidate in candidates],
        )
    return IdentityResolution(
        status="absent",
        vendor_id=None,
        display_name=vendor_input.get("vendor_name"),
        official_domain=domain or None,
    )


# --- source resolution ------------------------------------------------------


def _resolve_cached_source(source: CatalogSource) -> ResolvedSource:
    status = _CACHED_HEALTH_RESULT.get(source.health_status, RESULT_VERIFICATION_INCONCLUSIVE)
    catalog_status = RESULT_CATALOGUED if status == RESULT_CATALOG_CURRENT else None
    return ResolvedSource(
        source_type=source.source_type,
        status=status,
        source_url=source.source_url,
        origin="catalog",
        live_checked=False,  # cached never claims live verification
        checked_at=source.observed_at,
        catalog_status=catalog_status,
        reasons=[f"cached_health:{source.health_status or 'unknown'}"],
    )


def _make_history(
    *,
    vendor_id: str,
    source_type: str,
    previous: CatalogSource,
    new_url: str,
    now: str,
) -> tuple[dict[str, Any], str]:
    """Source-reference history only: former/current URL + observation times.

    Records *no* document content, text, or clause-level versions.
    """
    new_id = f"{vendor_id}-{source_type}-{_short_digest(new_url)}"
    history = {
        "source_type": source_type,
        "current_source": {
            "source_id": new_id,
            "url": new_url,
            "status": "current",
            "first_observed_at": now,
        },
        "previous_sources": [
            {
                "source_id": previous.source_id or f"{vendor_id}-{source_type}-previous",
                "url": previous.source_url,
                "status": "superseded",
                "last_observed_at": previous.observed_at or now,
                "superseded_by": new_id,
            }
        ],
    }
    return history, new_id


def _verify_existing_source(
    *,
    vendor_id: str,
    official_domain: str | None,
    source: CatalogSource,
    fetcher: Callable[[str], FetchResult],
    discovery: DiscoveryFn,
    emitter: SessionEmitter,
    channel: str,
    now: str,
) -> ResolvedSource:
    # Fail closed on unsafe URLs before any network access.
    if validate_url_safety(source.source_url, resolve_dns=True):
        return ResolvedSource(
            source_type=source.source_type,
            status=RESULT_VERIFICATION_INCONCLUSIVE,
            source_url=source.source_url,
            origin="catalog",
            live_checked=False,
            checked_at=None,
            catalog_status=RESULT_CATALOGUED,
            reasons=["unsafe_url_not_fetched"],
        )
    result = fetcher(source.source_url)
    text = normalize_text(result.body_sample, result.content_type)
    semantic = semantic_match(source.source_type, text, result.content_type)
    status = classify_status(
        {"source_url": source.source_url, "source_type": source.source_type}, result, semantic
    )
    if status in _VERIFY_CURRENT:
        return ResolvedSource(
            source_type=source.source_type,
            status=RESULT_CATALOG_CURRENT,
            source_url=result.final_url or source.source_url,
            origin="catalog",
            live_checked=True,
            checked_at=now,  # verify records the current observation time
            catalog_status=RESULT_CATALOGUED,
            reasons=[f"verified:{status}"],
        )
    if status in _VERIFY_MOVED:
        # Source moved: the redirect target is the replacement. Preserve old URL.
        new_url = result.final_url or source.source_url
        return _refresh_via_replacement(
            vendor_id=vendor_id,
            previous=source,
            new_url=new_url,
            matched_terms=list(semantic.get("matched_terms", [])),
            http_status=result.http_status,
            content_type=result.content_type,
            on_domain=_on_domain(new_url, official_domain),
            emitter=emitter,
            channel=channel,
            now=now,
            reason=f"moved:{status}",
        )
    if status in _VERIFY_BROKEN:
        return _refresh_via_discovery(
            vendor_id=vendor_id,
            official_domain=official_domain,
            previous=source,
            source_type=source.source_type,
            fetcher=fetcher,
            discovery=discovery,
            emitter=emitter,
            channel=channel,
            now=now,
            broken_reason=f"broken:{status}",
        )
    # Gated / bot-protected / mismatch: cannot establish a reliable result.
    return ResolvedSource(
        source_type=source.source_type,
        status=RESULT_VERIFICATION_INCONCLUSIVE,
        source_url=source.source_url,
        origin="catalog",
        live_checked=True,
        checked_at=now,
        catalog_status=RESULT_CATALOGUED,
        reasons=[f"inconclusive:{status}"],
    )


def _refresh_via_replacement(
    *,
    vendor_id: str,
    previous: CatalogSource,
    new_url: str,
    matched_terms: list[str],
    http_status: int | None,
    content_type: str | None,
    on_domain: bool,
    emitter: SessionEmitter,
    channel: str,
    now: str,
    reason: str,
) -> ResolvedSource:
    history, _new_id = _make_history(
        vendor_id=vendor_id,
        source_type=previous.source_type,
        previous=previous,
        new_url=new_url,
        now=now,
    )
    _emit_source_candidate(
        emitter=emitter,
        candidate_origin="source_replacement",
        channel=channel,
        vendor_id=vendor_id,
        official_domain=matcher.normalize_domain(new_url),
        source_type=previous.source_type,
        candidate_url=new_url,
        final_url=new_url,
        http_status=http_status,
        content_type=content_type,
        matched_terms=matched_terms,
        on_domain=on_domain,
        now=now,
        is_new_vendor=False,
    )
    return ResolvedSource(
        source_type=previous.source_type,
        status=RESULT_CATALOG_REFRESHED,
        source_url=new_url,
        origin="live_discovery",
        live_checked=True,
        checked_at=now,
        catalog_status=RESULT_CANDIDATE_PROCESSING,
        previous_source_url=previous.source_url,
        history=history,
        reasons=[reason],
    )


def _refresh_via_discovery(
    *,
    vendor_id: str,
    official_domain: str | None,
    previous: CatalogSource,
    source_type: str,
    fetcher: Callable[[str], FetchResult],
    discovery: DiscoveryFn,
    emitter: SessionEmitter,
    channel: str,
    now: str,
    broken_reason: str,
) -> ResolvedSource:
    found = discovery(official_domain or "", source_type, fetcher, now) if official_domain else None
    if found is None:
        return ResolvedSource(
            source_type=source_type,
            status=RESULT_SOURCE_UNAVAILABLE,
            source_url=previous.source_url,
            origin="catalog",
            live_checked=True,
            checked_at=now,
            catalog_status=RESULT_CATALOGUED,
            reasons=[broken_reason, "no_replacement_found"],
        )
    return _refresh_via_replacement(
        vendor_id=vendor_id,
        previous=previous,
        new_url=found.final_url,
        matched_terms=found.matched_terms,
        http_status=found.http_status,
        content_type=found.content_type,
        on_domain=found.on_vendor_domain,
        emitter=emitter,
        channel=channel,
        now=now,
        reason=broken_reason,
    )


def _discover_missing_source(
    *,
    vendor_id: str,
    official_domain: str | None,
    source_type: str,
    is_new_vendor: bool,
    fetcher: Callable[[str], FetchResult],
    discovery: DiscoveryFn,
    emitter: SessionEmitter,
    channel: str,
    now: str,
) -> ResolvedSource:
    found = discovery(official_domain or "", source_type, fetcher, now) if official_domain else None
    if found is None:
        return ResolvedSource(
            source_type=source_type,
            status=RESULT_NOT_FOUND,
            source_url=None,
            origin="live_discovery",
            live_checked=True,
            checked_at=now,
            catalog_status=None,
            reasons=["no_public_source_found"],
        )
    candidate_origin = "catalog_discovery" if is_new_vendor else "coverage_gap"
    _emit_source_candidate(
        emitter=emitter,
        candidate_origin=candidate_origin,
        channel=channel,
        vendor_id=vendor_id,
        official_domain=matcher.normalize_domain(found.final_url) or official_domain or "",
        source_type=source_type,
        candidate_url=found.final_url,
        final_url=found.final_url,
        http_status=found.http_status,
        content_type=found.content_type,
        matched_terms=found.matched_terms,
        on_domain=found.on_vendor_domain,
        now=now,
        is_new_vendor=is_new_vendor,
    )
    return ResolvedSource(
        source_type=source_type,
        status=RESULT_NEWLY_DISCOVERED,
        source_url=found.final_url,
        origin="live_discovery",
        live_checked=True,
        checked_at=now,
        catalog_status=RESULT_CANDIDATE_PROCESSING,
        reasons=[f"discovered:{found.verification_status}"],
    )


def _emit_source_candidate(
    *,
    emitter: SessionEmitter,
    candidate_origin: str,
    channel: str,
    vendor_id: str,
    official_domain: str,
    source_type: str,
    candidate_url: str,
    final_url: str,
    http_status: int | None,
    content_type: str | None,
    matched_terms: list[str],
    on_domain: bool,
    now: str,
    is_new_vendor: bool,
) -> None:
    official_domain = official_domain or matcher.normalize_domain(candidate_url)
    official_unsafe = bool(validate_url_safety(f"https://{official_domain}")) if official_domain else True
    identity = {
        "vendor_id_candidate": candidate_record.slugify(vendor_id) or "unknown-vendor",
        "official_domain": official_domain or "unknown.invalid",
    }
    if official_unsafe:
        identity["official_domain_unsafe"] = True
    source_candidate = {
        "candidate_url": candidate_url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "source_type_candidate": source_type,
        "access_state": "public_reachable",
        "source_role": "primary_assurance",
        "on_vendor_domain": on_domain,
        "authority_proven": on_domain,
        "verification_result": "likely_vendor_published" if on_domain else "possible_match",
        "reasons": [f"matched_terms:{len(matched_terms)}"],
    }
    evidence = [
        {
            "candidate_url": candidate_url,
            "final_url": final_url,
            "http_status": http_status,
            "content_type": content_type,
            "verification_result": source_candidate["verification_result"],
            "observed_at": now,
        }
    ]
    origin_reference = f"{vendor_id}:{source_type}:{_canonical_url(final_url)}"
    emitter.emit(
        candidate_origin=candidate_origin,
        origin_reference=origin_reference,
        discovery_component=f"vendor_resolution:{channel}",
        vendor_identity_candidate=identity,
        source_candidates=[source_candidate],
        evidence_references=evidence,
        created_at=now,
        is_new_vendor=is_new_vendor,
    )


# --- top-level resolution ---------------------------------------------------


def resolve_vendor_sources(
    request: dict[str, Any],
    *,
    catalog: ResolutionCatalog,
    fetcher: Callable[[str], FetchResult] = fetch_url,
    discovery: DiscoveryFn = bounded_discovery,
    emitter: SessionEmitter | None = None,
    now: Callable[[], str] = _now_default,
) -> VendorResolution:
    """Resolve required source types for one vendor (the unified contract).

    ``request`` shape::

        {"vendor": {"vendor_name": ..., "domain": ...},
         "required_source_types": [...],
         "freshness_mode": "cached" | "verify"}
    """
    emitter = emitter if emitter is not None else SessionEmitter()
    timestamp = now()
    vendor_input = dict(request.get("vendor") or {})
    required = list(request.get("required_source_types") or [])
    freshness = request.get("freshness_mode", FRESHNESS_VERIFY)
    if freshness not in FRESHNESS_MODES:
        raise ValueError(f"unknown freshness_mode: {freshness}")
    channel = request.get("channel", DEFAULT_CHANNEL)

    identity = resolve_identity(catalog, vendor_input)
    snapshot = catalog.snapshot

    if identity.status == "ambiguous":
        vendor_block = {
            "vendor_id": None,
            "display_name": vendor_input.get("vendor_name"),
            "official_domain": identity.official_domain,
        }
        return VendorResolution(
            vendor=vendor_block,
            resolution_status=RESULT_IDENTITY_AMBIGUOUS,
            freshness_mode=freshness,
            sources=[],
            snapshot=snapshot,
            identity_candidates=identity.candidates,
        )

    is_new_vendor = identity.status == "absent"
    vendor_id = identity.vendor_id or candidate_record.slugify(
        vendor_input.get("vendor_name") or vendor_input.get("domain") or "unknown-vendor"
    )
    catalog_sources = (
        {source.source_type: source for source in catalog.sources_for(identity.vendor_id)}
        if identity.vendor_id
        else {}
    )

    resolved: list[ResolvedSource] = []
    for source_type in required:
        existing = catalog_sources.get(source_type)
        if freshness == FRESHNESS_CACHED:
            if existing is not None:
                resolved.append(_resolve_cached_source(existing))
            else:
                resolved.append(
                    ResolvedSource(
                        source_type=source_type,
                        status=RESULT_NOT_FOUND,
                        origin="catalog",
                        live_checked=False,
                        catalog_status=None,
                        reasons=["not_in_catalog_cached_mode"],
                    )
                )
            continue
        # verify mode
        if existing is not None:
            resolved.append(
                _verify_existing_source(
                    vendor_id=vendor_id,
                    official_domain=identity.official_domain,
                    source=existing,
                    fetcher=fetcher,
                    discovery=discovery,
                    emitter=emitter,
                    channel=channel,
                    now=timestamp,
                )
            )
        else:
            resolved.append(
                _discover_missing_source(
                    vendor_id=vendor_id,
                    official_domain=identity.official_domain,
                    source_type=source_type,
                    is_new_vendor=is_new_vendor,
                    fetcher=fetcher,
                    discovery=discovery,
                    emitter=emitter,
                    channel=channel,
                    now=timestamp,
                )
            )

    resolution_status = _rollup(identity, resolved)
    vendor_block = {
        "vendor_id": identity.vendor_id,
        "display_name": identity.display_name,
        "official_domain": identity.official_domain,
    }
    return VendorResolution(
        vendor=vendor_block,
        resolution_status=resolution_status,
        freshness_mode=freshness,
        sources=resolved,
        snapshot=snapshot,
        candidates=emitter.candidates,
    )


def _rollup(identity: IdentityResolution, sources: list[ResolvedSource]) -> str:
    if identity.status == "ambiguous":
        return RESULT_IDENTITY_AMBIGUOUS
    if not sources:
        return RESULT_NOT_FOUND if identity.status == "absent" else RESULT_VERIFICATION_INCONCLUSIVE
    statuses = {source.status for source in sources}
    best = RESULT_NOT_FOUND
    best_rank = -1
    for status in statuses:
        rank = _ROLLUP_PRECEDENCE.index(status) if status in _ROLLUP_PRECEDENCE else -1
        if rank > best_rank:
            best_rank = rank
            best = status
    if identity.status == "absent" and best == RESULT_NOT_FOUND:
        return RESULT_NOT_FOUND
    return best


# --- inventory (human upload) shaping ---------------------------------------


def resolve_inventory(
    rows: list[dict[str, Any]],
    required_source_types: list[str],
    *,
    catalog: ResolutionCatalog,
    freshness_mode: str = FRESHNESS_VERIFY,
    channel: str = DEFAULT_CHANNEL,
    fetcher: Callable[[str], FetchResult] = fetch_url,
    discovery: DiscoveryFn = bounded_discovery,
    now: Callable[[], str] = _now_default,
) -> dict[str, Any]:
    """Resolve a whole uploaded vendor list, returning results + a summary.

    A single shared emitter across the list keeps the run idempotent: the same
    vendor or source appearing twice reuses one candidate.
    """
    emitter = SessionEmitter()
    results: list[VendorResolution] = []
    for row in rows:
        request = {
            "vendor": row,
            "required_source_types": required_source_types,
            "freshness_mode": freshness_mode,
            "channel": channel,
        }
        results.append(
            resolve_vendor_sources(
                request,
                catalog=catalog,
                fetcher=fetcher,
                discovery=discovery,
                emitter=emitter,
                now=now,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "freshness_mode": freshness_mode,
        "snapshot": catalog.snapshot,
        "summary": _inventory_summary(results),
        "results": [result.to_response() for result in results],
        "csv_rows": [resolution_csv_row(result) for result in results],
        "candidates": emitter.candidates,
        "not_advice": True,
    }


def _inventory_summary(results: list[VendorResolution]) -> dict[str, int]:
    counts = {state: 0 for state in RESULT_STATES}
    catalogue_current_sources = 0
    refreshed_sources = 0
    for result in results:
        counts[result.resolution_status] = counts.get(result.resolution_status, 0) + 1
        for source in result.sources:
            if source.status == RESULT_CATALOG_CURRENT:
                catalogue_current_sources += 1
            elif source.status == RESULT_CATALOG_REFRESHED:
                refreshed_sources += 1
    summary = {"vendors_processed": len(results)}
    summary.update({state: counts[state] for state in RESULT_STATES})
    summary["catalogue_sources_confirmed_current"] = catalogue_current_sources
    summary["catalogue_sources_refreshed"] = refreshed_sources
    return summary


# Stable, human/agent-friendly export columns. result_state is always present so
# CSV consumers can filter on the resolution outcome.
CSV_COLUMNS = (
    "vendor_name",
    "matched_vendor_id",
    "official_domain",
    "result_state",
    "source_types_current",
    "source_types_refreshed",
    "source_types_newly_discovered",
    "source_types_unavailable",
)


def resolution_csv_row(result: VendorResolution) -> dict[str, str]:
    by_status: dict[str, list[str]] = {}
    for source in result.sources:
        by_status.setdefault(source.status, []).append(source.source_type)
    return {
        "vendor_name": str(result.vendor.get("display_name") or ""),
        "matched_vendor_id": str(result.vendor.get("vendor_id") or ""),
        "official_domain": str(result.vendor.get("official_domain") or ""),
        "result_state": result.resolution_status,
        "source_types_current": ";".join(sorted(by_status.get(RESULT_CATALOG_CURRENT, []))),
        "source_types_refreshed": ";".join(sorted(by_status.get(RESULT_CATALOG_REFRESHED, []))),
        "source_types_newly_discovered": ";".join(sorted(by_status.get(RESULT_NEWLY_DISCOVERED, []))),
        "source_types_unavailable": ";".join(
            sorted(by_status.get(RESULT_SOURCE_UNAVAILABLE, []) + by_status.get(RESULT_NOT_FOUND, []))
        ),
    }


# --- helpers ----------------------------------------------------------------


def _on_domain(url: str, official_domain: str | None) -> bool:
    if not official_domain:
        return False
    host = matcher.normalize_domain(url)
    base = matcher.normalize_domain(official_domain)
    return host == base or host.endswith(f".{base}")


def _short_digest(value: str) -> str:
    return hashlib.sha256(_canonical_url(value).encode("utf-8")).hexdigest()[:12]


def _canonical_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _git_head(root: Path) -> str:
    head = root / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if ref.startswith("ref:"):
        ref_path = root / ".git" / ref.split(" ", 1)[1].strip()
        try:
            return ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"
    return ref


def validate_result(result: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    import jsonschema

    schema = schema or json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return [f"schema: {error.message}" for error in jsonschema.Draft202012Validator(schema).iter_errors(result)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-vendor-resolution")
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve", help="resolve a single request JSON file (cached mode by default)")
    resolve.add_argument("--request", type=Path, required=True)
    resolve.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    if args.command == "resolve":
        request = json.loads(args.request.read_text(encoding="utf-8"))
        request.setdefault("freshness_mode", FRESHNESS_CACHED)
        catalog = ResolutionCatalog.from_indexes(args.root)
        result = resolve_vendor_sources(request, catalog=catalog)
        print(json.dumps(result.to_response(), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
