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
- SSRF-safe fetch: :mod:`tools.openva.safe_verify` (``build_safe_verify_fetcher``)
  bound to the vendor's official domain — DNS pinning, private/loopback rejection,
  per-hop redirect validation, same-authority enforcement, byte limits, deadline.
  Plus :mod:`tools.openva.url_safety` to fail closed before any fetch;
- candidate emission: :mod:`tools.openva.candidate_record` (deterministic ids,
  evidence digests, and the one fail-closed eligibility evaluator that every
  origin must pass through);
- durable lifecycle ingress: ``maintenance/candidates/<candidate_id>.json`` — the
  same queue the autonomous-catalog-growth workflow consumes. A candidate is only
  reported as ``candidate_processing`` once it is eligible **and committed to git**
  (the scheduled workflow starts from a fresh checkout and only sees committed
  files); an uncommitted working-tree write is ``pending_ingress``. Live
  resolution never writes canonical catalogue records or ``main``.

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

Catalogue membership, source health, and lifecycle state are kept on separate
axes: ``catalog_membership`` (canonical / none) says whether the answer is backed
by a canonical record; ``status`` carries the resolution/health outcome; and
``catalog_status`` carries the durable lifecycle stage of the record backing the
answer. A deferred or rejected candidate is never reported as a usable source.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice. OpenVA preserves source-reference and
observation history; it does not archive or reproduce historical vendor
documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from tools.openva import candidate_record
from tools.openva.indexes import ROOT
from tools.openva.safe_verify import build_safe_verify_fetcher
from tools.openva.source_verification import (
    FetchResult,
    classify_status,
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

# Bounded transport defaults (mirroring config/discovery-bounds.yaml).
SAFE_MAX_REDIRECTS = 5
SAFE_TIMEOUT_SECONDS = 20.0

Fetcher = Callable[[str], FetchResult]
FetcherFactory = Callable[[list[str]], Fetcher]

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

# Catalogue-lifecycle axis (separate from the resolution/health axis above).
LIFECYCLE_CATALOGUED = "catalogued"
LIFECYCLE_PROCESSING = "candidate_processing"
LIFECYCLE_DEFERRED = "candidate_deferred"
LIFECYCLE_REJECTED = "candidate_rejected"
LIFECYCLE_PENDING = "pending_ingress"

# --- freshness modes --------------------------------------------------------

FRESHNESS_CACHED = "cached"
FRESHNESS_VERIFY = "verify"
FRESHNESS_MODES = (FRESHNESS_CACHED, FRESHNESS_VERIFY)

# Stored catalogue source-health buckets, mapped to a cached-mode result. The
# record stays canonical (catalogued) regardless of health; this is only the
# resolution/health outcome axis.
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
_VERIFY_REDIRECT = {"redirected"}
_VERIFY_GENERIC_REDIRECT = {"homepage_or_generic_redirect"}
_VERIFY_BROKEN = {
    "not_found",
    "gone",
    "unreachable",
    "server_error",
    "client_error",
    "soft_not_found",
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


def default_fetcher_factory(official_domains: list[str]) -> Fetcher:
    """Build the SSRF-safe verification fetcher bound to a vendor's authority.

    All resolution fetches go through ``SafeFetcher`` by default: DNS-pinned IP,
    private/loopback/reserved/mixed-answer rejection, per-hop redirect validation,
    same-authority enforcement, byte bound, and a monotonic deadline. The legacy
    unrestricted ``source_verification.fetch_url`` is never the default.
    """
    return build_safe_verify_fetcher(
        official_domains or [],
        max_redirects=SAFE_MAX_REDIRECTS,
        timeout_seconds=SAFE_TIMEOUT_SECONDS,
    )


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
        snapshot = {
            "catalog_commit_sha": _git_head(root),
            "catalog_generated_at": str(pack.get("generated_at") or ""),
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
            sources_by_vendor.setdefault(vendor_id, []).append(source)
        return cls(snapshot=snapshot, vendor_rows=vendor_rows, sources_by_vendor=sources_by_vendor)


# --- durable lifecycle ingress ----------------------------------------------


@dataclass(frozen=True)
class IngressOutcome:
    """Result of handing a candidate to the lifecycle ingress.

    ``record`` is the *authoritative* candidate after any merge with an existing
    persisted record. ``persisted`` means written to disk; ``committed`` means
    committed to git (and therefore visible to a fresh-checkout workflow).
    """

    record: dict[str, Any]
    persisted: bool
    committed: bool
    enqueued: bool  # newly created this call (vs reused/merged)
    reference: str | None


def catalog_status_for(eligibility_state: str, *, committed: bool) -> str:
    """Map evaluator eligibility + git-durability to a lifecycle stage.

    A candidate only "processes toward the catalogue" once it is both eligible and
    committed to git; eligible-but-uncommitted is ``pending_ingress``.
    """
    if eligibility_state == candidate_record.ELIGIBLE_STATE:
        return LIFECYCLE_PROCESSING if committed else LIFECYCLE_PENDING
    if eligibility_state.startswith("deferred"):
        return LIFECYCLE_DEFERRED
    if eligibility_state.startswith("rejected"):
        return LIFECYCLE_REJECTED
    return LIFECYCLE_PENDING


def merge_candidate(persisted: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Deterministically merge expanded discovery into a persisted candidate.

    The persisted record is authoritative for identity and origin. New source
    candidates (and their evidence) are added by normalised URL; the union is
    re-evaluated by the shared evaluator so eligibility reflects the complete set
    rather than silently discarding newly discovered sources. Returns the
    persisted record unchanged when nothing new is added.
    """
    by_url = {s["candidate_url"]: s for s in persisted.get("source_candidates", [])}
    added = False
    for source in incoming.get("source_candidates", []):
        if source["candidate_url"] not in by_url:
            by_url[source["candidate_url"]] = source
            added = True
    if not added:
        return persisted
    merged_sources = [by_url[key] for key in sorted(by_url)]
    ev_by = {e["candidate_url"]: e for e in persisted.get("evidence_references", [])}
    for evidence in incoming.get("evidence_references", []):
        ev_by.setdefault(evidence["candidate_url"], evidence)
    merged_evidence = [ev_by[key] for key in sorted(ev_by)]
    is_new_vendor = persisted.get("candidate_origin") == "catalog_discovery"
    eligibility_state, reasons = candidate_record.evaluate_eligibility(
        persisted["vendor_identity_candidate"], merged_sources, is_new_vendor=is_new_vendor
    )
    return candidate_record.build_candidate(
        candidate_origin=persisted["candidate_origin"],
        origin_reference=persisted["origin_reference"],
        vendor_identity_candidate=persisted["vendor_identity_candidate"],
        source_candidates=merged_sources,
        evidence_references=merged_evidence,
        discovery_component=persisted["discovery_component"],
        created_at=persisted["created_at"],
        eligibility_state=eligibility_state,
        decision_reasons=reasons,
    )


class CatalogQueueIngress:
    """Durable, idempotent ingress to the existing autonomous-growth queue.

    Writes the unified candidate record to ``maintenance/candidates/<id>.json``
    (atomically), the same directory ``autonomous-catalog-growth.yml`` reads
    eligible candidates from on a fresh checkout. Because that workflow only sees
    *committed* files, a freshly written working-tree file is reported as
    uncommitted (``pending_ingress``); pass ``commit=True`` to commit it to git as
    a real intake step, or commit/push it via an intake workflow. The persisted
    record is authoritative and expanded evidence is merged deterministically.
    Never writes canonical catalogue files (``data/vendors``) or ``main``.
    """

    def __init__(self, root: Path = ROOT, *, commit: bool = False) -> None:
        self.root = Path(root)
        self.queue_dir = self.root / "maintenance" / "candidates"
        self.commit = commit

    def enqueue(self, record: dict[str, Any]) -> IngressOutcome:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        path = self.queue_dir / f"{record['candidate_id']}.json"
        if path.exists():
            persisted = json.loads(path.read_text(encoding="utf-8"))
            authoritative = merge_candidate(persisted, record)
            enqueued = False
            if authoritative != persisted:
                _atomic_write_json(path, authoritative)
        else:
            authoritative = record
            enqueued = True
            _atomic_write_json(path, authoritative)
        if self.commit:
            _git_commit(path, self.root, f"Enqueue resolver candidate {record['candidate_id']}")
        committed = _is_committed(path, self.root)
        return IngressOutcome(
            record=authoritative, persisted=True, committed=committed,
            enqueued=enqueued, reference=str(path),
        )


class RecordingIngress:
    """Non-durable ingress for read-only/preview contexts and tests.

    Records candidates in memory only (still merging expanded evidence into the
    authoritative record). Because nothing is persisted or committed, it never
    claims a candidate is processing toward the catalogue.
    """

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def enqueue(self, record: dict[str, Any]) -> IngressOutcome:
        candidate_id = record["candidate_id"]
        if candidate_id in self.records:
            authoritative = merge_candidate(self.records[candidate_id], record)
            self.records[candidate_id] = authoritative
            return IngressOutcome(authoritative, persisted=False, committed=False, enqueued=False, reference=None)
        self.records[candidate_id] = record
        return IngressOutcome(record, persisted=False, committed=False, enqueued=True, reference=None)


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
    candidate_url: str | None = None  # unverified discovered URL (deferred outcomes)
    origin: str | None = None  # "catalog" | "live_discovery" | None
    catalog_membership: str = "none"  # "canonical" | "none"
    live_checked: bool = False
    checked_at: str | None = None
    catalog_status: str | None = None  # lifecycle stage (LIFECYCLE_*) or None
    previous_source_url: str | None = None
    proposed_source_history: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_type": self.source_type,
            "status": self.status,
            "source_url": self.source_url,
            "origin": self.origin,
            "catalog_membership": self.catalog_membership,
            "live_checked": self.live_checked,
            "checked_at": self.checked_at,
            "catalog_status": self.catalog_status,
        }
        if self.candidate_url is not None:
            payload["candidate_url"] = self.candidate_url
        if self.previous_source_url is not None:
            payload["previous_source_url"] = self.previous_source_url
        if self.proposed_source_history is not None:
            payload["proposed_source_history"] = self.proposed_source_history
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
    candidate_updates: list[dict[str, Any]] = field(default_factory=list)
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
        if self.candidate_updates:
            response["candidate_updates"] = list(self.candidate_updates)
        return response


# --- idempotent candidate emission ------------------------------------------


@dataclass(frozen=True)
class EmitResult:
    record: dict[str, Any]  # authoritative record (post-merge)
    outcome: IngressOutcome


class SessionEmitter:
    """Builds candidate records and hands them to a durable lifecycle ingress.

    Idempotent on two levels: the deterministic candidate id dedups within a
    session, and the injected ingress dedups (and merges) across
    sessions/processes. The record returned is always the ingress's authoritative
    record, so response state never diverges from what is persisted. Emission
    never writes canonical catalogue files; canonical mutation stays with the
    existing autonomous lifecycle.
    """

    def __init__(self, ingress: Any | None = None) -> None:
        self._ingress = ingress if ingress is not None else RecordingIngress()
        self._by_id: dict[str, EmitResult] = {}

    @property
    def candidate_updates(self) -> list[dict[str, Any]]:
        updates = []
        for candidate_id in sorted(self._by_id):
            result = self._by_id[candidate_id]
            updates.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_origin": result.record["candidate_origin"],
                    "eligibility_state": result.record["eligibility_state"],
                    "lifecycle_state": catalog_status_for(
                        result.record["eligibility_state"], committed=result.outcome.committed
                    ),
                    "persisted": result.outcome.persisted,
                    "committed": result.outcome.committed,
                }
            )
        return updates

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
    ) -> EmitResult:
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
        # Always hand to the ingress, which merges with any existing record so
        # newly discovered sources are never silently discarded; the ingress's
        # authoritative (persisted/merged) record wins.
        outcome = self._ingress.enqueue(record)
        result = EmitResult(record=outcome.record, outcome=outcome)
        self._by_id[outcome.record["candidate_id"]] = result
        return result


def _clean_source_candidate(source: dict[str, Any]) -> dict[str, Any]:
    leaked = {"source_type_conflict", "authority_proven"}
    return {key: value for key, value in source.items() if key not in leaked}


# --- bounded public discovery -----------------------------------------------

DiscoveryFn = Callable[[str, str, Fetcher, str], DiscoveryResult | None]


def bounded_discovery(
    official_domain: str,
    source_type: str,
    fetcher: Fetcher,
    observed_at: str,
) -> DiscoveryResult | None:
    """Try a small, fixed set of vendor-published paths on the official domain.

    Fails closed: only ``https`` URLs on the official domain that pass URL safety
    are fetched (through the SSRF-safe fetcher), and a candidate is accepted only
    when the response is reachable, on-domain, and semantically consistent with
    the source type.
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
    final_url = result.final_url or candidate_url
    if not _valid_replacement(final_url, semantic.get("status"), status, official_domain):
        return None
    return DiscoveryResult(
        candidate_url=candidate_url,
        final_url=final_url,
        http_status=result.http_status,
        content_type=result.content_type,
        verification_status=status,
        matched_terms=list(semantic.get("matched_terms", [])),
        observed_at=observed_at,
        on_vendor_domain=True,
    )


def _valid_replacement(
    final_url: str,
    semantic_status: str | None,
    verification_status: str,
    official_domain: str | None,
) -> bool:
    """A replacement is acceptable only when safe, on-authority, non-generic, and
    semantically consistent with the source type."""
    if validate_url_safety(final_url, resolve_dns=True):
        return False
    if verification_status not in {"ok", "redirected"}:
        return False
    if not _on_domain(final_url, official_domain):
        return False
    if semantic_status not in {"strong", "weak"}:
        return False
    return True


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
    # Catalogue membership and source health are independent axes: a stale or
    # broken source is still a canonical (catalogued) record.
    status = _CACHED_HEALTH_RESULT.get(source.health_status, RESULT_VERIFICATION_INCONCLUSIVE)
    return ResolvedSource(
        source_type=source.source_type,
        status=status,
        source_url=source.source_url,
        origin="catalog",
        catalog_membership="canonical",
        live_checked=False,  # cached never claims live verification
        checked_at=source.observed_at,
        catalog_status=LIFECYCLE_CATALOGUED,
        reasons=[f"cached_health:{source.health_status or 'unknown'}"],
    )


def _make_history(
    *,
    vendor_id: str,
    source_type: str,
    previous: CatalogSource,
    new_url: str,
    now: str,
) -> dict[str, Any]:
    """Proposed source-reference history only: former/current URL + observation
    times. Records *no* document content, text, or clause-level versions. Becomes
    durable supersession history only after the replacement is admitted by the
    lifecycle."""
    new_id = f"{vendor_id}-{source_type}-{_short_digest(new_url)}"
    return {
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


def _verify_existing_source(
    *,
    vendor_id: str,
    official_domain: str | None,
    source: CatalogSource,
    fetcher: Fetcher,
    discovery: DiscoveryFn,
    emitter: SessionEmitter,
    channel: str,
    now: str,
) -> ResolvedSource:
    # Fail closed on unsafe URLs before any network access.
    if validate_url_safety(source.source_url, resolve_dns=True):
        return _canonical_outcome(source, RESULT_VERIFICATION_INCONCLUSIVE, now, live_checked=False,
                                  reasons=["unsafe_url_not_fetched"])
    result = fetcher(source.source_url)
    text = normalize_text(result.body_sample, result.content_type)
    semantic = semantic_match(source.source_type, text, result.content_type)
    status = classify_status(
        {"source_url": source.source_url, "source_type": source.source_type}, result, semantic
    )
    if status in _VERIFY_CURRENT:
        return _canonical_outcome(source, RESULT_CATALOG_CURRENT, now, live_checked=True,
                                  source_url=result.final_url or source.source_url,
                                  reasons=[f"verified:{status}"])
    if status in _VERIFY_REDIRECT:
        new_url = result.final_url or source.source_url
        if _valid_replacement(new_url, semantic.get("status"), status, official_domain):
            return _refresh_via_replacement(
                vendor_id=vendor_id, previous=source, new_url=new_url,
                matched_terms=list(semantic.get("matched_terms", [])),
                http_status=result.http_status, content_type=result.content_type,
                on_domain=True, emitter=emitter, channel=channel, now=now, reason=f"moved:{status}",
            )
        return _discovery_fallback(
            vendor_id=vendor_id, official_domain=official_domain, previous=source,
            source_type=source.source_type, fetcher=fetcher, discovery=discovery,
            emitter=emitter, channel=channel, now=now,
            broken_reason=f"unsafe_or_generic_redirect:{status}",
            no_replacement_status=RESULT_VERIFICATION_INCONCLUSIVE,
        )
    if status in _VERIFY_GENERIC_REDIRECT:
        return _discovery_fallback(
            vendor_id=vendor_id, official_domain=official_domain, previous=source,
            source_type=source.source_type, fetcher=fetcher, discovery=discovery,
            emitter=emitter, channel=channel, now=now, broken_reason=f"generic_redirect:{status}",
            no_replacement_status=RESULT_VERIFICATION_INCONCLUSIVE,
        )
    if status in _VERIFY_BROKEN:
        return _discovery_fallback(
            vendor_id=vendor_id, official_domain=official_domain, previous=source,
            source_type=source.source_type, fetcher=fetcher, discovery=discovery,
            emitter=emitter, channel=channel, now=now, broken_reason=f"broken:{status}",
            no_replacement_status=RESULT_SOURCE_UNAVAILABLE,
        )
    # Gated / bot-protected / mismatch: cannot establish a reliable result.
    return _canonical_outcome(source, RESULT_VERIFICATION_INCONCLUSIVE, now, live_checked=True,
                              reasons=[f"inconclusive:{status}"])


def _canonical_outcome(
    source: CatalogSource,
    status: str,
    now: str,
    *,
    live_checked: bool,
    source_url: str | None = None,
    reasons: list[str] | None = None,
) -> ResolvedSource:
    return ResolvedSource(
        source_type=source.source_type,
        status=status,
        source_url=source_url or source.source_url,
        origin="catalog",
        catalog_membership="canonical",
        live_checked=live_checked,
        checked_at=now if live_checked else None,
        catalog_status=LIFECYCLE_CATALOGUED,  # the canonical record still exists
        reasons=reasons or [],
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
    emitted = _emit_source_candidate(
        emitter=emitter, candidate_origin="source_replacement", channel=channel,
        vendor_id=vendor_id, official_domain=matcher.normalize_domain(new_url),
        source_type=previous.source_type, candidate_url=new_url, final_url=new_url,
        http_status=http_status, content_type=content_type, matched_terms=matched_terms,
        on_domain=on_domain, now=now, is_new_vendor=False,
    )
    elig = emitted.record["eligibility_state"]
    status, catalog_status, surface = _outcome_view(RESULT_CATALOG_REFRESHED, elig, emitted.outcome.committed)
    history = _make_history(
        vendor_id=vendor_id, source_type=previous.source_type, previous=previous,
        new_url=new_url, now=now,
    ) if surface else None
    return ResolvedSource(
        source_type=previous.source_type,
        status=status,
        # When surfaced, the replacement is the result; otherwise keep the prior
        # canonical URL and expose the discovered URL only as unverified.
        source_url=new_url if surface else previous.source_url,
        candidate_url=None if surface else (new_url if catalog_status == LIFECYCLE_DEFERRED else None),
        origin="live_discovery",
        catalog_membership="none",
        live_checked=True,
        checked_at=now,
        catalog_status=catalog_status,
        previous_source_url=previous.source_url,
        proposed_source_history=history,
        reasons=[reason, f"eligibility:{elig}"],
    )


def _discovery_fallback(
    *,
    vendor_id: str,
    official_domain: str | None,
    previous: CatalogSource,
    source_type: str,
    fetcher: Fetcher,
    discovery: DiscoveryFn,
    emitter: SessionEmitter,
    channel: str,
    now: str,
    broken_reason: str,
    no_replacement_status: str,
) -> ResolvedSource:
    found = discovery(official_domain or "", source_type, fetcher, now) if official_domain else None
    if found is None:
        return ResolvedSource(
            source_type=source_type,
            status=no_replacement_status,
            source_url=previous.source_url,
            origin="catalog",
            catalog_membership="canonical",
            live_checked=True,
            checked_at=now,
            catalog_status=LIFECYCLE_CATALOGUED,
            reasons=[broken_reason, "no_replacement_found"],
        )
    return _refresh_via_replacement(
        vendor_id=vendor_id, previous=previous, new_url=found.final_url,
        matched_terms=found.matched_terms, http_status=found.http_status,
        content_type=found.content_type, on_domain=found.on_vendor_domain,
        emitter=emitter, channel=channel, now=now, reason=broken_reason,
    )


def _outcome_view(
    success_status: str, eligibility_state: str, committed: bool
) -> tuple[str, str, bool]:
    """Map (success status, eligibility, git-durability) to the response.

    Returns ``(resolution_status, catalog_status, surface_source_url)``. Only an
    eligible candidate is surfaced as a usable result; deferred and rejected
    candidates return ``verification_inconclusive`` so agents are never told an
    unverified or rejected URL is the resolved source.
    """
    catalog_status = catalog_status_for(eligibility_state, committed=committed)
    if eligibility_state == candidate_record.ELIGIBLE_STATE:
        return success_status, catalog_status, True
    return RESULT_VERIFICATION_INCONCLUSIVE, catalog_status, False


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
) -> EmitResult:
    identity = _identity_candidate(vendor_id, official_domain or matcher.normalize_domain(candidate_url))
    source_candidate = _source_candidate(
        source_type, candidate_url, final_url, http_status, content_type, matched_terms, on_domain
    )
    evidence = [_evidence(candidate_url, final_url, http_status, content_type, source_candidate, now)]
    origin_reference = f"{vendor_id}:{source_type}:{_canonical_url(final_url)}"
    return emitter.emit(
        candidate_origin=candidate_origin,
        origin_reference=origin_reference,
        discovery_component=f"vendor_resolution:{channel}",
        vendor_identity_candidate=identity,
        source_candidates=[source_candidate],
        evidence_references=evidence,
        created_at=now,
        is_new_vendor=is_new_vendor,
    )


def _identity_candidate(vendor_id: str, official_domain: str) -> dict[str, Any]:
    official_domain = official_domain or ""
    official_unsafe = bool(validate_url_safety(f"https://{official_domain}")) if official_domain else True
    identity = {
        "vendor_id_candidate": candidate_record.slugify(vendor_id) or "unknown-vendor",
        "official_domain": official_domain or "unknown.invalid",
    }
    if official_unsafe:
        identity["official_domain_unsafe"] = True
    return identity


def _source_candidate(
    source_type: str,
    candidate_url: str,
    final_url: str,
    http_status: int | None,
    content_type: str | None,
    matched_terms: list[str],
    on_domain: bool,
) -> dict[str, Any]:
    return {
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


def _evidence(
    candidate_url: str,
    final_url: str,
    http_status: int | None,
    content_type: str | None,
    source_candidate: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    return {
        "candidate_url": candidate_url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "verification_result": source_candidate["verification_result"],
        "observed_at": now,
    }


# --- top-level resolution ---------------------------------------------------


def resolve_vendor_sources(
    request: dict[str, Any],
    *,
    catalog: ResolutionCatalog,
    fetcher: Fetcher | None = None,
    fetcher_factory: FetcherFactory = default_fetcher_factory,
    discovery: DiscoveryFn = bounded_discovery,
    emitter: SessionEmitter | None = None,
    now: Callable[[], str] = _now_default,
) -> VendorResolution:
    """Resolve required source types for one vendor (the unified contract).

    ``request`` shape::

        {"vendor": {"vendor_name": ..., "domain": ...},
         "required_source_types": [...],
         "freshness_mode": "cached" | "verify"}

    By default fetches go through the SSRF-safe fetcher bound to the resolved
    official domain (``fetcher_factory``); pass an explicit ``fetcher`` to override
    (e.g. in tests). By default candidates are recorded but not durably committed;
    pass an ``emitter`` backed by :class:`CatalogQueueIngress` (as
    :func:`resolve_inventory` and the CLI do) to durably enqueue them.
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
        return VendorResolution(
            vendor={
                "vendor_id": None,
                "display_name": vendor_input.get("vendor_name"),
                "official_domain": identity.official_domain,
            },
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
    # Bind the SSRF-safe fetcher to the vendor's own authority unless overridden.
    active_fetcher = (
        fetcher if fetcher is not None
        else fetcher_factory([identity.official_domain] if identity.official_domain else [])
    )

    if is_new_vendor and freshness == FRESHNESS_VERIFY:
        resolved = _resolve_new_vendor(
            vendor_id=vendor_id, official_domain=identity.official_domain,
            required=required, fetcher=active_fetcher, discovery=discovery, emitter=emitter,
            channel=channel, now=timestamp,
        )
    else:
        resolved = [
            _resolve_one(
                source_type=source_type, existing=catalog_sources.get(source_type),
                freshness=freshness, vendor_id=vendor_id,
                official_domain=identity.official_domain, is_new_vendor=is_new_vendor,
                fetcher=active_fetcher, discovery=discovery, emitter=emitter, channel=channel,
                now=timestamp,
            )
            for source_type in required
        ]

    return VendorResolution(
        vendor={
            "vendor_id": identity.vendor_id,
            "display_name": identity.display_name,
            "official_domain": identity.official_domain,
        },
        resolution_status=_rollup(identity, resolved),
        freshness_mode=freshness,
        sources=resolved,
        snapshot=snapshot,
        candidate_updates=emitter.candidate_updates,
    )


def _resolve_one(
    *,
    source_type: str,
    existing: CatalogSource | None,
    freshness: str,
    vendor_id: str,
    official_domain: str | None,
    is_new_vendor: bool,
    fetcher: Fetcher,
    discovery: DiscoveryFn,
    emitter: SessionEmitter,
    channel: str,
    now: str,
) -> ResolvedSource:
    if freshness == FRESHNESS_CACHED:
        if existing is not None:
            return _resolve_cached_source(existing)
        return ResolvedSource(
            source_type=source_type, status=RESULT_NOT_FOUND, origin="catalog",
            catalog_membership="none", live_checked=False, catalog_status=None,
            reasons=["not_in_catalog_cached_mode"],
        )
    if existing is not None:
        return _verify_existing_source(
            vendor_id=vendor_id, official_domain=official_domain, source=existing,
            fetcher=fetcher, discovery=discovery, emitter=emitter, channel=channel, now=now,
        )
    # Missing type on a known vendor: independent coverage-gap candidate.
    found = discovery(official_domain or "", source_type, fetcher, now) if official_domain else None
    if found is None:
        return ResolvedSource(
            source_type=source_type, status=RESULT_NOT_FOUND, source_url=None,
            origin="live_discovery", catalog_membership="none", live_checked=True,
            checked_at=now, catalog_status=None, reasons=["no_public_source_found"],
        )
    emitted = _emit_source_candidate(
        emitter=emitter, candidate_origin="coverage_gap", channel=channel, vendor_id=vendor_id,
        official_domain=matcher.normalize_domain(found.final_url) or official_domain or "",
        source_type=source_type, candidate_url=found.final_url, final_url=found.final_url,
        http_status=found.http_status, content_type=found.content_type,
        matched_terms=found.matched_terms, on_domain=found.on_vendor_domain, now=now,
        is_new_vendor=False,
    )
    return _discovered_source(source_type, found, emitted, now)


def _resolve_new_vendor(
    *,
    vendor_id: str,
    official_domain: str | None,
    required: list[str],
    fetcher: Fetcher,
    discovery: DiscoveryFn,
    emitter: SessionEmitter,
    channel: str,
    now: str,
) -> list[ResolvedSource]:
    """Resolve a brand-new vendor: discover all requested types first, then emit
    ONE aggregate ``catalog_discovery`` candidate so the new vendor materialises
    from its complete discovery set rather than fragmenting into per-source
    candidates."""
    discovered: dict[str, DiscoveryResult] = {}
    for source_type in required:
        found = discovery(official_domain or "", source_type, fetcher, now) if official_domain else None
        if found is not None:
            discovered[source_type] = found

    if not discovered:
        return [_not_found_source(source_type, now) for source_type in required]

    domain = matcher.normalize_domain(official_domain or next(iter(discovered.values())).final_url)
    identity = _identity_candidate(vendor_id, domain)
    source_candidates = []
    evidence = []
    for source_type, found in discovered.items():
        source_candidate = _source_candidate(
            source_type, found.candidate_url, found.final_url, found.http_status,
            found.content_type, found.matched_terms, found.on_vendor_domain,
        )
        source_candidates.append(source_candidate)
        evidence.append(
            _evidence(found.candidate_url, found.final_url, found.http_status,
                      found.content_type, source_candidate, now)
        )
    emitted = emitter.emit(
        candidate_origin="catalog_discovery",
        origin_reference=f"{vendor_id}:{domain}",
        discovery_component=f"vendor_resolution:{channel}",
        vendor_identity_candidate=identity,
        source_candidates=source_candidates,
        evidence_references=evidence,
        created_at=now,
        is_new_vendor=True,
    )

    resolved: list[ResolvedSource] = []
    for source_type in required:
        found = discovered.get(source_type)
        if found is None:
            resolved.append(_not_found_source(source_type, now))
        else:
            resolved.append(_discovered_source(source_type, found, emitted, now))
    return resolved


def _discovered_source(
    source_type: str, found: DiscoveryResult, emitted: EmitResult, now: str
) -> ResolvedSource:
    elig = emitted.record["eligibility_state"]
    status, catalog_status, surface = _outcome_view(
        RESULT_NEWLY_DISCOVERED, elig, emitted.outcome.committed
    )
    return ResolvedSource(
        source_type=source_type,
        status=status,
        source_url=found.final_url if surface else None,
        candidate_url=None if surface else (found.final_url if catalog_status == LIFECYCLE_DEFERRED else None),
        origin="live_discovery",
        catalog_membership="none",
        live_checked=True,
        checked_at=now,
        catalog_status=catalog_status,
        reasons=[f"discovered:{found.verification_status}", f"eligibility:{elig}"],
    )


def _not_found_source(source_type: str, now: str) -> ResolvedSource:
    return ResolvedSource(
        source_type=source_type, status=RESULT_NOT_FOUND, source_url=None,
        origin="live_discovery", catalog_membership="none", live_checked=True,
        checked_at=now, catalog_status=None, reasons=["no_public_source_found"],
    )


def _rollup(identity: IdentityResolution, sources: list[ResolvedSource]) -> str:
    if identity.status == "ambiguous":
        return RESULT_IDENTITY_AMBIGUOUS
    if not sources:
        return RESULT_NOT_FOUND if identity.status == "absent" else RESULT_VERIFICATION_INCONCLUSIVE
    best = RESULT_NOT_FOUND
    best_rank = -1
    for source in sources:
        rank = _ROLLUP_PRECEDENCE.index(source.status) if source.status in _ROLLUP_PRECEDENCE else -1
        if rank > best_rank:
            best_rank = rank
            best = source.status
    return best


# --- inventory (human upload) shaping ---------------------------------------


def resolve_inventory(
    rows: list[dict[str, Any]],
    required_source_types: list[str],
    *,
    catalog: ResolutionCatalog,
    freshness_mode: str = FRESHNESS_VERIFY,
    channel: str = DEFAULT_CHANNEL,
    fetcher: Fetcher | None = None,
    fetcher_factory: FetcherFactory = default_fetcher_factory,
    discovery: DiscoveryFn = bounded_discovery,
    ingress: Any | None = None,
    now: Callable[[], str] = _now_default,
) -> dict[str, Any]:
    """Resolve a whole uploaded vendor list, returning results + a summary.

    A single shared emitter (durably enqueuing to ``maintenance/candidates`` by
    default) keeps the run idempotent: the same vendor or source appearing twice
    reuses (and merges into) one candidate.
    """
    emitter = SessionEmitter(ingress if ingress is not None else CatalogQueueIngress())
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
                request, catalog=catalog, fetcher=fetcher, fetcher_factory=fetcher_factory,
                discovery=discovery, emitter=emitter, now=now,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "freshness_mode": freshness_mode,
        "snapshot": catalog.snapshot,
        "summary": _inventory_summary(results),
        "results": [result.to_response() for result in results],
        "csv_rows": [resolution_csv_row(result) for result in results],
        "candidate_updates": emitter.candidate_updates,
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
    if not host or not base:
        return False
    return host == base or host.endswith(f".{base}")


def _short_digest(value: str) -> str:
    return hashlib.sha256(_canonical_url(value).encode("utf-8")).hexdigest()[:12]


def _canonical_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX/NTFS


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return os.path.relpath(str(path), str(root))


def _is_committed(path: Path, root: Path) -> bool:
    """True only when the file is git-tracked with no uncommitted changes."""
    rel = _rel(path, root)
    tracked = _git(root, "ls-files", "--error-unmatch", "--", rel)
    if tracked.returncode != 0:
        return False
    status = _git(root, "status", "--porcelain", "--", rel)
    return status.returncode == 0 and status.stdout.strip() == ""


def _git_commit(path: Path, root: Path, message: str) -> bool:
    rel = _rel(path, root)
    if _git(root, "add", "--", rel).returncode != 0:
        return False
    # The candidate-intake commit is a metadata enqueue, not a release commit; do
    # not require local commit signing (the autonomous workflow signs its own).
    return _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, "--", rel).returncode == 0


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
    resolve = sub.add_parser("resolve", help="resolve a single request JSON file")
    resolve.add_argument("--request", type=Path, required=True)
    resolve.add_argument("--root", type=Path, default=ROOT)
    resolve.add_argument(
        "--enqueue", action="store_true",
        help="durably write discovered candidates to maintenance/candidates (verify mode)",
    )
    resolve.add_argument(
        "--commit", action="store_true",
        help="commit enqueued candidate files to git so the autonomous workflow can see them",
    )
    args = parser.parse_args(argv)

    if args.command == "resolve":
        request = json.loads(args.request.read_text(encoding="utf-8"))
        request.setdefault("freshness_mode", FRESHNESS_CACHED)
        catalog = ResolutionCatalog.from_indexes(args.root)
        ingress = (
            CatalogQueueIngress(args.root, commit=args.commit)
            if args.enqueue else RecordingIngress()
        )
        result = resolve_vendor_sources(request, catalog=catalog, emitter=SessionEmitter(ingress))
        # to_response() includes candidate_updates so durable enqueue outcomes are
        # never silently dropped from the CLI output.
        print(json.dumps(result.to_response(), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
