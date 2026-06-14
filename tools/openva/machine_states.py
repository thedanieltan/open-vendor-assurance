"""WP40A machine eligibility states (Issue 5).

The autonomous catalog lane never routes a routine record to a human-review
queue. Where the legacy reviewed-intake path emitted reasons such as
``new_vendor_identity_requires_human_review`` or ``source_type_needs_human_review``,
the autonomous lane maps the same observable facts to one explicit machine
state from ``candidate_record.ELIGIBILITY_STATES``:

    eligible
    deferred_insufficient_evidence
    deferred_cross_authority
    deferred_language_uncertainty
    rejected_duplicate
    rejected_identity_collision
    rejected_unsafe_url
    rejected_source_type_conflict
    rejected_gated

This module is the single translation table from legacy review-reason strings
to machine states, so telemetry, the issue lifecycle, and the dashboard can
render the autonomous outcome without reintroducing a human-review verdict.
Mapping a reason to a machine state never weakens the evidence threshold — the
fail-closed ``deferred_*`` / ``rejected_*`` states preserve the same bar.

Human review remains required for changes to CODE, SCHEMAS, WORKFLOWS, POLICY
thresholds, AUTHORITY, PERMISSIONS, and GOVERNANCE — those are not routine
catalog records and are intentionally absent from this table.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

from tools.openva.candidate_record import ELIGIBILITY_STATES

# Legacy review-reason -> machine eligibility state. Every routine catalog
# review reason resolves to a fail-closed machine state; none stays a
# human-review verdict.
REASON_TO_STATE: dict[str, str] = {
    "advisory_language_needs_human_review": "rejected_source_type_conflict",
    "gated_or_access_control_language_needs_human_review": "rejected_gated",
    "new_vendor_identity_requires_human_review": "deferred_insufficient_evidence",
    "request_type_requires_human_review": "deferred_insufficient_evidence",
    "unknown_vendor_requires_human_review": "deferred_insufficient_evidence",
    "source_authority_needs_human_review": "deferred_cross_authority",
    "source_type_needs_human_review": "deferred_insufficient_evidence",
    "source_type_requires_human_review": "deferred_insufficient_evidence",
    "existing_source_update_requires_human_review": "deferred_insufficient_evidence",
    "network_verification_needs_human_review": "deferred_insufficient_evidence",
    "mixed_create_and_refresh_requires_human_review": "deferred_insufficient_evidence",
}

# Reasons that map to a hard rejection rather than a deferral.
REJECTING_STATES = {s for s in ELIGIBILITY_STATES if s.startswith("rejected_")}
DEFERRING_STATES = {s for s in ELIGIBILITY_STATES if s.startswith("deferred_")}

# Change classes that are NOT routine catalog records and always keep a human
# gate. These must never be machine-decided.
HUMAN_GOVERNED_CHANGE_CLASSES = (
    "code",
    "schema",
    "workflow",
    "policy",
    "authority",
    "permissions",
    "governance",
)


def map_reason(reason: str) -> str:
    """Map one legacy review reason to a machine eligibility state.

    Unknown reasons fail closed to ``deferred_insufficient_evidence`` rather
    than to any human-review verdict.
    """
    return REASON_TO_STATE.get(reason, "deferred_insufficient_evidence")


def resolve_state(reasons: list[str]) -> str:
    """Resolve a list of review reasons to one machine state.

    Rejections dominate deferrals (most decisive fail-closed state wins); an
    empty reason list is ``eligible``.
    """
    if not reasons:
        return "eligible"
    states = [map_reason(r) for r in reasons]
    for state in states:
        if state in REJECTING_STATES:
            return state
    for state in states:
        if state in DEFERRING_STATES:
            return state
    return "eligible"


def is_human_review_verdict(value: str) -> bool:
    """True if a value is a legacy human-review verdict the autonomous lane drops."""
    return value in {"needs_human_review", "needs-human-review"} or value.endswith("_requires_human_review") or value.endswith("_needs_human_review")
