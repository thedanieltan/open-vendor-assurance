"""WP40 unified candidate record.

One canonical candidate schema for every origin — human submissions, catalog
discovery, coverage gaps, source replacement, and machine-readable surfaces.
All origins feed the same eligibility evaluation; candidate origin never
reduces verification requirements.

This module owns three deterministic, side-effect-free operations:

- ``compute_candidate_id`` derives a stable id from (origin, origin_reference)
  so identical inputs always yield the same candidate id;
- ``compute_evidence_digest`` hashes the canonical JSON of the evidence
  references (SHA-256 only) so a candidate's evidence is tamper-evident and
  reproducible;
- ``evaluate_eligibility`` maps a candidate's identity and per-source facts to
  exactly one machine eligibility state plus reasons. It fails closed: when
  evidence is insufficient, conflicting, gated, or ambiguous it returns a
  ``deferred_*`` or ``rejected_*`` state and never an implicit human-review
  queue.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from tools.openva.indexes import ROOT

SCHEMA_VERSION = "0.1.0"
SCHEMA_PATH = ROOT / "schemas" / "openva" / "candidate-record.schema.json"

CANDIDATE_ORIGINS = (
    "human_submission",
    "catalog_discovery",
    "coverage_gap",
    "source_replacement",
    "machine_readable_surface",
)

ELIGIBILITY_STATES = (
    "pending",
    "eligible",
    "deferred_insufficient_evidence",
    "deferred_cross_authority",
    "deferred_language_uncertainty",
    "rejected_duplicate",
    "rejected_identity_collision",
    "rejected_unsafe_url",
    "rejected_source_type_conflict",
    "rejected_gated",
)

# Eligibility states that allow a candidate to enter the machine-provisional
# materialisation lane. Everything else fails closed.
ELIGIBLE_STATE = "eligible"

# Per-source access states that count as a usable public assurance source.
PUBLIC_ACCESS_STATES = {"public_reachable"}
GATED_ACCESS_STATES = {"declared_gated", "bot_protected", "gated_or_auth_required"}

# Source roles that satisfy the minimum useful source-role threshold.
USEFUL_SOURCE_ROLES = {"primary_assurance", "supporting_assurance"}

# Minimum number of usable assurance sources a new vendor candidate needs
# before it may materialise. Fail closed below this.
DEFAULT_MIN_USEFUL_SOURCE_ROLES = 1

# Phase 6 user-facing reusable-memory states. These are deliberately separate
# from evaluator states, ingress durability rungs, machine-provisional PRs, and
# quorum terms. Ordinary users should see whether a discovered source can be
# reused later, not the internal candidate lifecycle mechanics.
USER_MEMORY_QUEUED_FOR_REUSE = "queued_for_reuse"
USER_MEMORY_ALREADY_KNOWN = "already_known"
USER_MEMORY_CANDIDATE_FOUND = "candidate_found"
USER_MEMORY_NOT_QUEUED_AMBIGUOUS = "not_queued_ambiguous"
USER_MEMORY_NOT_QUEUED_UNSAFE = "not_queued_unsafe"
USER_MEMORY_NOT_QUEUED_INSUFFICIENT_EVIDENCE = "not_queued_insufficient_evidence"

USER_MEMORY_STATES = (
    USER_MEMORY_QUEUED_FOR_REUSE,
    USER_MEMORY_ALREADY_KNOWN,
    USER_MEMORY_CANDIDATE_FOUND,
    USER_MEMORY_NOT_QUEUED_AMBIGUOUS,
    USER_MEMORY_NOT_QUEUED_UNSAFE,
    USER_MEMORY_NOT_QUEUED_INSUFFICIENT_EVIDENCE,
)

USER_MEMORY_STATE_LABELS = {
    USER_MEMORY_QUEUED_FOR_REUSE: "queued for reuse",
    USER_MEMORY_ALREADY_KNOWN: "already known",
    USER_MEMORY_CANDIDATE_FOUND: "candidate found",
    USER_MEMORY_NOT_QUEUED_AMBIGUOUS: "not queued: ambiguous",
    USER_MEMORY_NOT_QUEUED_UNSAFE: "not queued: unsafe",
    USER_MEMORY_NOT_QUEUED_INSUFFICIENT_EVIDENCE: "not queued: insufficient evidence",
}

# String constants are used here to avoid a dependency cycle with
# ``vendor_resolution``. These are the durability rungs that mean the candidate
# has reached a durable/reusable intake path rather than read-only preview memory.
DURABLE_REUSE_INGRESS_STATES = frozenset(
    {"persisted_local", "committed_local", "submitted_remote", "workflow_visible"}
)


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    """Lowercase, hyphenated slug matching the catalog id convention."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def compute_candidate_id(candidate_origin: str, origin_reference: str) -> str:
    """Deterministic candidate id from origin + origin reference.

    Identical inputs always produce the same id, so re-running intake on the
    same submission/discovery row never spawns a second candidate.
    """
    origin_slug = slugify(candidate_origin) or "unknown"
    ref_slug = slugify(origin_reference)
    if not ref_slug:
        digest = hashlib.sha256(origin_reference.encode("utf-8")).hexdigest()[:12]
        ref_slug = f"ref-{digest}"
    # Bound the length while keeping determinism for very long references.
    if len(ref_slug) > 80:
        digest = hashlib.sha256(origin_reference.encode("utf-8")).hexdigest()[:12]
        ref_slug = f"{ref_slug[:67]}-{digest}"
    return f"cand-{origin_slug}-{ref_slug}"


def _canonical(value: Any) -> Any:
    """Canonicalise evidence for hashing: sort keys, drop None, stable order."""
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items()) if v is not None}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def compute_evidence_digest(evidence_references: list[dict[str, Any]]) -> str:
    """SHA-256 over the canonical JSON of the evidence references.

    OpenVA digests are SHA-256 only (bot constitution). The digest is stable
    under key ordering and absent/None fields so identical evidence always
    hashes identically.
    """
    canonical = json.dumps(
        _canonical(list(evidence_references)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_candidate_content_digest(record: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the *whole* candidate record.

    This is the binding digest carried through the candidate-activation path
    (controller decision -> dispatch -> mutation). It covers the full record
    content, so any post-decision mutation of the persisted candidate — a
    changed source, a forged ``eligibility_state``, an altered identity —
    changes the digest and fails the binding closed. SHA-256 only (bot
    constitution); stable under key ordering and absent/None fields so an
    unchanged record always hashes identically.
    """
    canonical = json.dumps(
        _canonical(dict(record)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_eligibility(
    vendor_identity_candidate: dict[str, Any],
    source_candidates: list[dict[str, Any]],
    *,
    is_new_vendor: bool = True,
    identity_collision: bool = False,
    language_uncertain: bool = False,
    min_useful_source_roles: int = DEFAULT_MIN_USEFUL_SOURCE_ROLES,
) -> tuple[str, list[str]]:
    """Map identity + per-source facts to one eligibility state + reasons.

    Fail-closed precedence (most decisive first):

    1. ``rejected_identity_collision`` — the candidate's identity collides with
       a different existing vendor identity (caller-supplied signal).
    2. ``rejected_duplicate`` — a new-vendor candidate already exists in the
       catalog.
    3. ``rejected_unsafe_url`` — the vendor identity anchor (official domain)
       itself is unsafe; the vendor cannot be anchored.
    4. ``rejected_gated`` — every supplied source is gated/bot-protected, so no
       public assurance source can be recorded.
    5. ``rejected_source_type_conflict`` — sources remain but every non-gated
       source's content contradicts its declared type.
    6. ``deferred_cross_authority`` — the only usable sources sit on an
       unproven third-party authority.
    7. ``deferred_language_uncertainty`` — caller flagged language ambiguity.
    8. ``deferred_insufficient_evidence`` — fewer usable assurance sources than
       the minimum useful threshold.
    9. ``eligible`` — enough usable, on-authority assurance sources remain.

    One bad source does not invalidate the vendor when enough valid sources
    remain (handled by counting usable sources rather than rejecting on any
    single failure).
    """
    reasons: list[str] = []

    if identity_collision:
        return "rejected_identity_collision", ["vendor_identity_collision"]

    if is_new_vendor and vendor_identity_candidate.get("matches_existing_vendor_id"):
        return "rejected_duplicate", [
            f"vendor_already_in_catalog:{vendor_identity_candidate['matches_existing_vendor_id']}"
        ]

    # The vendor must have a safe, anchorable official domain.
    if vendor_identity_candidate.get("official_domain_unsafe"):
        return "rejected_unsafe_url", ["official_domain_failed_url_safety"]

    if source_candidates:
        non_unsafe = [s for s in source_candidates if s.get("access_state") != "unsafe_url"]
        gated = [s for s in non_unsafe if s.get("access_state") in GATED_ACCESS_STATES]
        # All non-unsafe sources gated -> no public assurance source recordable.
        if non_unsafe and all(s.get("access_state") in GATED_ACCESS_STATES for s in non_unsafe):
            return "rejected_gated", ["all_sources_gated_or_bot_protected"]

    usable: list[dict[str, Any]] = []
    cross_authority: list[dict[str, Any]] = []
    type_conflicts = 0
    public_non_gated = 0
    for source in source_candidates:
        access = source.get("access_state")
        role = source.get("source_role")
        if access not in PUBLIC_ACCESS_STATES:
            continue
        public_non_gated += 1
        if source.get("source_type_conflict"):
            type_conflicts += 1
            continue
        if role not in USEFUL_SOURCE_ROLES:
            continue
        if source.get("on_vendor_domain") is False and not source.get("authority_proven"):
            cross_authority.append(source)
            continue
        usable.append(source)

    if not usable:
        if public_non_gated and type_conflicts == public_non_gated:
            return "rejected_source_type_conflict", ["every_public_source_content_conflicts_declared_type"]
        if cross_authority and not usable:
            return "deferred_cross_authority", ["only_unproven_third_party_authority_sources"]

    if language_uncertain:
        return "deferred_language_uncertainty", ["non_english_summary_uncertainty"]

    if len(usable) < min_useful_source_roles:
        reasons.append(
            f"usable_assurance_sources={len(usable)}<min={min_useful_source_roles}"
        )
        if cross_authority:
            reasons.append("cross_authority_sources_present_unproven")
        return "deferred_insufficient_evidence", reasons

    reasons.append(f"usable_assurance_sources={len(usable)}")
    return ELIGIBLE_STATE, reasons


def user_facing_candidate_memory_state(
    eligibility_state: str,
    *,
    ingress_state: str | None = None,
) -> str:
    """Map internal candidate eligibility to a user-facing reusable-memory state.

    Phase 6 keeps candidate memory as a background cache. This function is the
    public vocabulary bridge: it hides internal evaluator, ingress, PR, quorum,
    and machine-provisional language behind a small set of states users can act
    on. It is not advice and does not change eligibility, promotion, or mutation
    authority.
    """
    if eligibility_state == "rejected_duplicate":
        return USER_MEMORY_ALREADY_KNOWN
    if eligibility_state in {"rejected_identity_collision", "deferred_cross_authority", "deferred_language_uncertainty"}:
        return USER_MEMORY_NOT_QUEUED_AMBIGUOUS
    if eligibility_state == "rejected_unsafe_url":
        return USER_MEMORY_NOT_QUEUED_UNSAFE
    if eligibility_state in {
        "deferred_insufficient_evidence",
        "rejected_source_type_conflict",
        "rejected_gated",
    }:
        return USER_MEMORY_NOT_QUEUED_INSUFFICIENT_EVIDENCE
    if eligibility_state == ELIGIBLE_STATE:
        return (
            USER_MEMORY_QUEUED_FOR_REUSE
            if ingress_state in DURABLE_REUSE_INGRESS_STATES
            else USER_MEMORY_CANDIDATE_FOUND
        )
    return USER_MEMORY_CANDIDATE_FOUND


def user_facing_candidate_memory_view(
    record: dict[str, Any],
    *,
    ingress_state: str | None = None,
) -> dict[str, Any]:
    """Return the Phase 6 user-facing reusable-memory projection.

    The projection intentionally omits candidate ids, eligibility states,
    ingress states, PR state, quorum state, and other internal lifecycle details.
    Internal orchestration can still use the candidate record directly.
    """
    state = user_facing_candidate_memory_state(
        str(record.get("eligibility_state") or "pending"),
        ingress_state=ingress_state,
    )
    return {
        "state": state,
        "label": USER_MEMORY_STATE_LABELS[state],
        "not_advice": True,
    }


def build_candidate(
    *,
    candidate_origin: str,
    origin_reference: str,
    vendor_identity_candidate: dict[str, Any],
    source_candidates: list[dict[str, Any]],
    evidence_references: list[dict[str, Any]],
    discovery_component: str,
    created_at: str,
    eligibility_state: str = "pending",
    decision_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble a schema-valid candidate record.

    ``candidate_id`` and ``evidence_digest`` are derived deterministically so
    the same inputs always produce byte-identical candidate records.
    """
    if candidate_origin not in CANDIDATE_ORIGINS:
        raise ValueError(f"unknown candidate_origin: {candidate_origin}")
    if eligibility_state not in ELIGIBILITY_STATES:
        raise ValueError(f"unknown eligibility_state: {eligibility_state}")
    record = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": compute_candidate_id(candidate_origin, origin_reference),
        "candidate_origin": candidate_origin,
        "origin_reference": origin_reference,
        "vendor_identity_candidate": vendor_identity_candidate,
        "source_candidates": list(source_candidates),
        "evidence_references": list(evidence_references),
        "evidence_digest": compute_evidence_digest(evidence_references),
        "discovery_component": discovery_component,
        "created_at": created_at,
        "eligibility_state": eligibility_state,
        "decision_reasons": list(decision_reasons or []),
        "not_advice": True,
    }
    return record


def validate_candidate(record: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    schema = schema or load_schema()
    errors = [f"schema: {e.message}" for e in jsonschema.Draft202012Validator(schema).iter_errors(record)]
    # The schema's source_candidate $defs allow extra evaluator-only keys to be
    # rejected; evaluator inputs (source_type_conflict, authority_proven,
    # official_domain_unsafe) are consumed before build and must not appear in
    # the committed record. Guard against accidental leakage.
    leaked = {"source_type_conflict", "authority_proven"}
    for source in record.get("source_candidates", []):
        for key in leaked & set(source):
            errors.append(f"source_candidate carries evaluator-only key {key!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-candidate-record")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate a candidate record JSON file")
    validate.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        record = json.loads(args.candidate.read_text(encoding="utf-8"))
        errors = validate_candidate(record)
        if errors:
            for error in errors:
                print(error)
            return 1
        print(f"candidate {record.get('candidate_id')} is valid.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
