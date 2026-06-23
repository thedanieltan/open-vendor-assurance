"""Candidate-ingress boundary (WP-02D).

The hosted match service operates in the **discovery role only**. When the worker's
SSRF-safe resolution surfaces a genuinely newly-discovered public source, this module
proposes the corresponding non-canonical candidate(s) into the EXISTING durable candidate
ingress (the ``maintenance/candidates`` queue path), reusing the existing
``tools.openva.candidate_record`` machinery and ``tools.openva.vendor_resolution`` ingress
classes. It is provider-neutral application code: NO cloud SDK, NO GitHub credential, NO
``data/**`` write, NO ``main`` write, NO catalogue mutation, NO merge.

Authoritative spec: docs/operations/contracts/hosted-deployment.yaml —
``access_matrix.async_worker`` (the worker holds ``github_app_key: none``),
``access_matrix.candidate_ingress`` (the ONLY component that may hold the GitHub App key;
``catalog_truth: none``; proposes PRs only). The credentialed PR-opening component is the
EXISTING ``candidate-intake-pr.yml`` / ``candidate_ingress`` boundary — it is NOT built
here. This module only STAGES candidate records into the existing ingress; the separate,
infra-gated, credentialed component later opens the PR.

Separation of duties (enforced by construction):
  - the proposer holds no GitHub credential and never opens/merges anything;
  - it only enqueues into the same durable ingress the rest of the system uses
    (deterministic candidate id + evidence digest from the one canonical
    ``candidate_record`` evaluator — never a second/parallel ingress);
  - discovery is a side output: the proposer runs AFTER the verify job is terminalized,
    never gates the verify result, and a proposer failure never fails the verify job.

Off by default: the worker is constructed WITHOUT a proposer (``proposer=None``) unless the
verify transport is enabled AND ingress is explicitly turned on, in which case it behaves
exactly as the WP-02C worker (no candidate proposal).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from tools.openva import candidate_record
from tools.openva.vendor_resolution import (
    CatalogQueueIngress,
    IngressOutcome,
    RecordingIngress,
    SessionEmitter,
)

# Resolution/health states that indicate a GENUINELY newly-discovered public source — the
# only outcomes that should propose a candidate. A catalogued / current / cached source is
# already canonical and proposes nothing; a not-found / ambiguous / inconclusive outcome has
# no usable discovery to propose. These mirror the resolver's result vocabulary
# (tools.openva.vendor_resolution.RESULT_*).
PROPOSABLE_RESULT_STATES = frozenset({"newly_discovered", "catalog_refreshed"})


@dataclass(frozen=True)
class CandidateProposal:
    """One staged candidate, the outcome of handing it to the durable ingress.

    ``candidate_id`` / ``evidence_digest`` are the deterministic identifiers the existing
    ``candidate_record`` machinery produced (NOT re-derived here), so an identical discovery
    always proposes the identical candidate id and the durable ingress dedups it.
    ``ingress_state`` is the durability rung the existing ingress reported (INGRESS_*)."""

    candidate_id: str
    evidence_digest: str
    candidate_origin: str
    eligibility_state: str
    ingress_state: str
    enqueued: bool
    reference: str | None

    @classmethod
    def from_outcome(cls, outcome: IngressOutcome) -> "CandidateProposal":
        record = outcome.record
        return cls(
            candidate_id=record["candidate_id"],
            evidence_digest=record["evidence_digest"],
            candidate_origin=record["candidate_origin"],
            eligibility_state=record["eligibility_state"],
            ingress_state=outcome.ingress_state,
            enqueued=outcome.enqueued,
            reference=outcome.reference,
        )


@runtime_checkable
class CandidateProposer(Protocol):
    """Provider-neutral discovery-only boundary.

    Implementations take candidate records that the resolver built during a verify job and
    STAGE them into the existing durable candidate ingress. An implementation MUST NOT hold
    a GitHub credential, write ``data/**``, mutate the catalogue, or open/merge a PR — it
    only enqueues into the existing ingress path. ``propose`` MUST be best-effort: any
    failure is the caller's to swallow (discovery never gates the verify result)."""

    def propose(self, records: Iterable[dict[str, Any]]) -> list[CandidateProposal]:
        ...


def is_proposable_resolution(resolution: Any) -> bool:
    """True only when the resolution's rolled-up status is a genuinely-new discovery.

    Accepts either a ``VendorResolution`` (``resolution_status`` attribute) or the plain
    dict the worker stores in the result payload (a ``resolution`` body with a
    ``resolution_status`` key). A catalogued/current/not-found/ambiguous resolution is never
    proposable, so an already-catalogued or non-new resolution proposes nothing."""
    status = _resolution_status(resolution)
    return status in PROPOSABLE_RESULT_STATES


def _resolution_status(resolution: Any) -> str | None:
    if hasattr(resolution, "resolution_status"):
        return getattr(resolution, "resolution_status")
    if isinstance(resolution, dict):
        body = resolution.get("resolution") if isinstance(resolution.get("resolution"), dict) else resolution
        value = body.get("resolution_status")
        return str(value) if value is not None else None
    return None


class DurableIngressProposer:
    """Default proposer: stage candidate records into the EXISTING durable ingress.

    Wraps the existing ``vendor_resolution`` ingress (``CatalogQueueIngress`` by default —
    the single canonical writer of ``maintenance/candidates/<id>.json`` the rest of the
    system uses). It NEVER opens or merges a PR and holds no credential: the credentialed
    PR-opening remains the existing, infra-gated ``candidate_ingress`` component. Each record
    is re-validated against the candidate-record schema before staging; an invalid record is
    skipped (fail closed) rather than corrupting the queue.

    ``commit`` / ``workflow_ref`` are forwarded to ``CatalogQueueIngress`` unchanged; both
    default to off, so by default the proposer only writes the working-tree staging file
    (``persisted_local``) and never commits or pushes — visibility to the autonomous-growth
    workflow remains a separate, infra-gated step."""

    def __init__(self, ingress: Any | None = None) -> None:
        # The existing durable ingress (the SAME path the resolver/CLI use). A test injects
        # an in-memory ``RecordingIngress`` sink; production uses ``CatalogQueueIngress``.
        self._ingress = ingress if ingress is not None else CatalogQueueIngress()

    def propose(self, records: Iterable[dict[str, Any]]) -> list[CandidateProposal]:
        proposals: list[CandidateProposal] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            # Never trust a record into the queue without revalidating it through the one
            # canonical schema validator (the same one the ingress trusts on read).
            if candidate_record.validate_candidate(record):
                continue
            outcome = self._ingress.enqueue(record)
            proposals.append(CandidateProposal.from_outcome(outcome))
        return proposals


def new_session_emitter() -> SessionEmitter:
    """A capture-only emitter for use DURING verify execution.

    Backed by a non-durable ``RecordingIngress`` so candidate records are built (via the one
    canonical ``candidate_record`` machinery the resolver already uses) and collected in
    memory while the job executes, WITHOUT any durable side effect on the execution path.
    The durable staging happens only later, AFTER terminalization, when the proposer replays
    the captured records into the existing durable ingress. This keeps discovery a strict
    side output: nothing is persisted until the verify result is already terminal."""
    return SessionEmitter(RecordingIngress())


def captured_records(emitter: SessionEmitter) -> list[dict[str, Any]]:
    """Extract the candidate records a capture emitter collected during execution.

    Returns the authoritative (post in-session merge) record per candidate id, in
    deterministic candidate-id order. Only records whose own rolled-up discovery is
    proposable reach this — the emitter only built candidates the resolver chose to emit, and
    the proposer additionally schema-revalidates each before staging."""
    ingress = getattr(emitter, "_ingress", None)
    if isinstance(ingress, RecordingIngress):
        return [ingress.records[cid] for cid in sorted(ingress.records)]
    return []
