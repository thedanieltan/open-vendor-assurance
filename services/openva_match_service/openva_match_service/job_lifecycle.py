"""Hosted verify job-lifecycle state machine + handoff protocol (WP-02B).

This is the actor-scoped, compare-and-set (CAS) lifecycle LIBRARY for the durable
job store. It operates DIRECTLY on the stores (JobStore + RequestEnvelopeStore +
ResultStore from ``verify_transport``); it does NOT ship a worker FETCH/execute loop,
a real queue adapter, provider provisioning, or request deduplication (those are
WP-02C). Every transition here uses only edges DECLARED in the authoritative contract.

Authoritative spec: ``docs/operations/contracts/hosted-deployment.yaml`` sections
``transitions`` (actor-scoped edges), ``execution_lease``, ``handoff``,
``access_matrix`` (per-actor ``owned_transitions``), ``transition_mutations`` (the
EXACT atomic field set per edge), and ``expiry``. The record shape + its
state-dependent invariants are in ``schemas/openva/hosted-job-record.schema.json``.

Invariants enforced by the central guarded mutate (``_guarded_transition``):
  - EDGE: the (from_state -> to_state) edge must exist in ``transitions`` and list the
    acting actor (IllegalTransition / UnauthorizedActor otherwise).
  - ACTOR AUTHORITY: the edge must additionally be in the actor's
    ``access_matrix.owned_transitions`` (defence in depth alongside the edge actor list).
  - VERSION CAS: ``expected_version`` must equal the stored record's version
    (StaleVersion otherwise); a successful mutation bumps ``version`` and persists with a
    version-guarded write (a lost CAS race also raises StaleVersion).
  - MUTATION: exactly the contract's ``transition_mutations`` field set for that edge is
    applied (state + the nulled/set lease/ref/error/attempt fields + updated_at).
  - LEASE: a live lease is never preempted (LivePreemption); a stale lease defers to the
    watchdog; the heartbeat extends only for the current lease_owner.

Negative rules enforced: there is NO ``queued->failed`` edge; ``api`` may NOT do
``queued->executing``; the watchdog owns ONLY ``executing->queued`` / ``executing->failed``;
the reconciler owns ONLY ``received->queued``. ``attempt`` is the watchdog's EXECUTION
retry counter (0 while received); ``dispatch_attempt`` is the reconciler's DISPATCH
recovery counter — they are kept strictly distinct.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from enum import Enum

from .verify_transport import (
    ERROR_CODES,
    JobRecord,
    JobStore,
    RequestEnvelopeStore,
    _parse_iso_z,
)


# --- Actors -------------------------------------------------------------------


class Actor(str, Enum):
    """The four lifecycle actors. Each owns a fixed, contract-declared set of edges
    (access_matrix.owned_transitions). API on the normal path; WORKER for execution +
    recovery; WATCHDOG for stale-lease recovery; RECONCILER for dispatch recovery."""

    API = "api"
    WORKER = "worker"
    WATCHDOG = "watchdog"
    RECONCILER = "reconciler"


# --- Errors -------------------------------------------------------------------


class LifecycleError(Exception):
    """Base for every lifecycle CAS protocol violation."""


class IllegalTransition(LifecycleError):
    """No such edge exists in the transition graph (e.g. queued->failed,
    received->executing direct), regardless of actor."""


class UnauthorizedActor(LifecycleError):
    """The edge exists but the acting actor is not permitted for it, per the edge's
    actor list AND the actor's access_matrix.owned_transitions (e.g. api doing
    queued->executing; reconciler doing executing->*)."""


class StaleVersion(LifecycleError):
    """expected_version != the stored record's version (a concurrent writer won). The
    actor must re-read and retry."""


class LivePreemption(LifecycleError):
    """An attempt to preempt a LIVE execution lease (forbidden). A redelivered task whose
    record is executing with a live lease is acked-and-dropped by the caller; with an
    EXPIRED lease it defers to the watchdog (never preempts)."""


class InvalidLease(LifecycleError):
    """A lease deadline is malformed, in the past, or not strictly later than required
    (Blocker 3). Acquisition must create a STRICTLY-future lease; a heartbeat may only
    extend a currently-LIVE lease to a deadline strictly later than both ``now`` and the
    existing ``lease_expires_at`` (no reviving an expired lease, no shortening/past-dating)."""


class InvalidErrorCode(LifecycleError):
    """A terminalizing error_code is outside the schema enum
    (execution_timeout|upstream_unavailable|rate_limited|internal_error). Rejected at the
    transition boundary (defence in depth; the persistence schema validation is the
    backstop)."""


# --- Edge + actor authority tables (mirrors the contract) ---------------------
#
# transitions: actor-scoped edges, hosted-deployment.yaml `transitions`.
# Frozenset of permitted actor VALUES per (from_state, to_state).
_TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("received", "queued"): frozenset({"api", "reconciler", "worker"}),
    ("received", "failed"): frozenset({"api"}),
    ("queued", "executing"): frozenset({"worker"}),
    ("executing", "completed"): frozenset({"worker"}),
    ("executing", "failed"): frozenset({"worker", "watchdog"}),
    ("executing", "queued"): frozenset({"watchdog"}),
}

# access_matrix.<actor>.owned_transitions, hosted-deployment.yaml `access_matrix`.
# "from->to" strings, the second authority gate alongside the edge actor list.
_OWNED_TRANSITIONS: dict[Actor, frozenset[str]] = {
    Actor.API: frozenset({"received->queued", "received->failed"}),
    Actor.WORKER: frozenset(
        {"received->queued", "queued->executing", "executing->completed", "executing->failed"}
    ),
    Actor.WATCHDOG: frozenset({"executing->queued", "executing->failed"}),
    Actor.RECONCILER: frozenset({"received->queued"}),
}


def _check_edge_and_actor(from_state: str, to_state: str, actor: Actor) -> None:
    """Validate an edge exists and the actor is permitted (both gates). Raises
    IllegalTransition (no edge) or UnauthorizedActor (edge present, actor not allowed)."""
    allowed_actors = _TRANSITIONS.get((from_state, to_state))
    if allowed_actors is None:
        raise IllegalTransition(
            f"no such transition edge: {from_state}->{to_state}"
        )
    edge = f"{from_state}->{to_state}"
    if actor.value not in allowed_actors or edge not in _OWNED_TRANSITIONS.get(actor, frozenset()):
        raise UnauthorizedActor(
            f"actor {actor.value} is not permitted for edge {edge}"
        )


# --- Central guarded mutate ---------------------------------------------------


def _guarded_transition(
    jobs: JobStore,
    job_id: str,
    *,
    actor: Actor,
    to_state: str,
    expected_version: int,
    now: datetime,
    set_fields: dict[str, object] | None = None,
) -> JobRecord:
    """Load the record, verify the edge+actor+version, apply the EXACT mutated field
    set, bump version, and persist with a version-guarded CAS write.

    ``set_fields`` is the per-edge atomic mutation (the contract's transition_mutations
    `set`), already materialised with runtime values (lease owner/deadline, error_code,
    result_ref, attempt, etc.) but WITHOUT state/updated_at/version, which this function
    always sets. Returns the freshly persisted record.

    Raises IllegalTransition / UnauthorizedActor (edge+actor gates), or StaleVersion
    (expected_version mismatch, including a lost CAS race on the persist)."""
    record = jobs.get(job_id)
    if record is None:
        # Treated as a stale read: the actor must re-read (the record may have been
        # purged by expiry between the actor's prior read and this mutation).
        raise StaleVersion(f"job {job_id} not found (re-read required)")
    if record.version != expected_version:
        raise StaleVersion(
            f"expected version {expected_version}, stored version is {record.version}"
        )
    _check_edge_and_actor(record.state, to_state, actor)

    mutated = replace(
        record,
        state=to_state,
        updated_at=_iso_z(now),
        version=record.version + 1,
        **(set_fields or {}),
    )
    if not jobs.cas_update(mutated, expected_version):
        # A concurrent writer advanced the version between our read and our write.
        raise StaleVersion(
            f"CAS lost for job {job_id} at version {expected_version} (re-read required)"
        )
    return mutated


def _iso_z(value: datetime) -> str:
    """Render a timezone-aware datetime as ISO-8601 with a literal Z suffix (mirrors the
    app/transport renderer so persisted timestamps stay schema-valid date-times)."""
    from datetime import timezone

    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_lease(value: str, *, what: str) -> datetime:
    """Parse a lease/timestamp string, raising ``InvalidLease`` (not a bare ValueError) on
    a malformed value so the boundary rejects it cleanly (Blocker 3)."""
    try:
        return _parse_iso_z(value)
    except (ValueError, TypeError) as exc:
        raise InvalidLease(f"{what} is malformed: {value!r}") from exc


def _require_valid_error_code(error_code: str) -> None:
    """Reject a terminalizing error_code outside the schema enum (Blocker 4 boundary
    check; the persistence schema validation is the backstop)."""
    if error_code not in ERROR_CODES:
        raise InvalidErrorCode(
            f"error_code {error_code!r} is not one of {sorted(ERROR_CODES)}"
        )


# --- Typed transition functions (one per declared edge + recovery variants) ---


def api_received_to_queued(
    jobs: JobStore, job_id: str, expected_version: int, *, now: datetime
) -> JobRecord:
    """API normal-path enqueue ack: received -> queued.

    transition_mutations.api__received_to_queued: set state=queued, updated_at.
    request_ref preserved; lease stays null."""
    return _guarded_transition(
        jobs, job_id, actor=Actor.API, to_state="queued", expected_version=expected_version, now=now
    )


def api_received_to_failed(
    jobs: JobStore,
    envelopes: RequestEnvelopeStore,
    job_id: str,
    expected_version: int,
    *,
    error_code: str,
    now: datetime,
) -> JobRecord:
    """API terminalizes a received job it cannot enqueue: received -> failed.

    transition_mutations.api__received_to_failed: set failed + error_code; null
    request_ref/result_ref/lease; THEN delete the request envelope. The CAS clears the
    in-record pointer; the physical envelope delete is the separate `then` step.

    Rejects an error_code outside the schema enum (InvalidErrorCode) at the boundary."""
    _require_valid_error_code(error_code)
    record = jobs.get(job_id)
    request_ref = record.request_ref if record is not None else None
    mutated = _guarded_transition(
        jobs,
        job_id,
        actor=Actor.API,
        to_state="failed",
        expected_version=expected_version,
        now=now,
        set_fields={
            "error_code": error_code,
            "request_ref": None,
            "result_ref": None,
            "lease_owner": None,
            "lease_expires_at": None,
        },
    )
    if request_ref is not None:
        envelopes.delete(request_ref)
    return mutated


def worker_received_to_queued(
    jobs: JobStore, job_id: str, expected_version: int, *, now: datetime
) -> JobRecord:
    """Worker recovery (API crashed before its CAS): received -> queued.

    Same mutation as the API received->queued edge, actor WORKER (handoff.worker:
    on_delivery_if_received_cas_received_to_queued)."""
    return _guarded_transition(
        jobs, job_id, actor=Actor.WORKER, to_state="queued", expected_version=expected_version, now=now
    )


def worker_queued_to_executing(
    jobs: JobStore,
    job_id: str,
    expected_version: int,
    *,
    lease_owner: str,
    lease_expires_at: str,
    now: datetime,
) -> JobRecord:
    """Worker wins the job and takes a lease: queued -> executing.

    transition_mutations.worker__queued_to_executing: set executing + lease; request_ref
    preserved.

    Duplicate-delivery handling (handoff.duplicate_delivery): if the record is ALREADY
    executing with a LIVE lease, raise LivePreemption — the caller acks-and-drops. If it
    is executing with an EXPIRED lease, raise LivePreemption too (the redelivery defers
    to the watchdog; it must NOT preempt). Only a genuinely `queued` record proceeds.

    LEASE GUARD (Blocker 3): acquisition must create a STRICTLY-future lease. The supplied
    ``lease_expires_at`` is parsed and rejected (InvalidLease) if malformed or not strictly
    later than ``now`` (<= now), so a worker can never take a lease that is already stale."""
    deadline = _parse_lease(lease_expires_at, what="lease_expires_at")
    if deadline <= now:
        raise InvalidLease(
            f"acquired lease_expires_at {lease_expires_at!r} must be strictly after now"
        )
    record = jobs.get(job_id)
    if record is not None and record.state == "executing":
        # Already executing: never preempt. Live -> ack-and-drop; expired -> watchdog.
        raise LivePreemption(
            f"job {job_id} is already executing (lease "
            f"{'live' if _lease_is_live(record, now) else 'expired; defer to watchdog'}); "
            "not preempting"
        )
    return _guarded_transition(
        jobs,
        job_id,
        actor=Actor.WORKER,
        to_state="executing",
        expected_version=expected_version,
        now=now,
        set_fields={"lease_owner": lease_owner, "lease_expires_at": lease_expires_at},
    )


def worker_heartbeat(
    jobs: JobStore,
    job_id: str,
    expected_version: int,
    *,
    lease_owner: str,
    new_lease_expires_at: str,
    now: datetime,
) -> JobRecord:
    """Extend the execution lease (execution_lease.extended_by: worker_heartbeat).

    ONLY the current lease_owner may extend; this does NOT change state. It still
    CAS-bumps version (version-gated like every mutation), but it is an executing ->
    executing self-edge (not a state change). Raises UnauthorizedActor if the record is
    not executing or the caller is not the current lease_owner; StaleVersion on a version
    mismatch.

    LEASE GUARD (Blocker 3): a heartbeat may only extend a currently-LIVE lease and may
    only push the deadline FORWARD. It raises InvalidLease if the existing
    ``lease_expires_at`` is malformed or already expired (existing <= now: no reviving a
    dead lease), or if the new deadline is malformed or not strictly later than BOTH
    ``now`` AND the existing deadline (no shortening, no past-dating)."""
    record = jobs.get(job_id)
    if record is None:
        raise StaleVersion(f"job {job_id} not found (re-read required)")
    if record.version != expected_version:
        raise StaleVersion(
            f"expected version {expected_version}, stored version is {record.version}"
        )
    if record.state != "executing":
        raise UnauthorizedActor(
            f"heartbeat is only valid while executing, not {record.state}"
        )
    if record.lease_owner != lease_owner:
        raise UnauthorizedActor(
            "only the current lease_owner may heartbeat the lease"
        )
    # The existing lease must be currently LIVE — an already-expired lease (existing <= now)
    # cannot be revived by a heartbeat; it defers to the watchdog.
    existing = _parse_lease(record.lease_expires_at, what="existing lease_expires_at")
    if existing <= now:
        raise InvalidLease(
            f"lease {record.lease_expires_at!r} is already expired; cannot heartbeat (defer to watchdog)"
        )
    # The new deadline must move strictly forward past BOTH now and the existing deadline.
    new_deadline = _parse_lease(new_lease_expires_at, what="new_lease_expires_at")
    if new_deadline <= now or new_deadline <= existing:
        raise InvalidLease(
            f"new lease_expires_at {new_lease_expires_at!r} must be strictly after both now "
            f"and the existing lease {record.lease_expires_at!r}"
        )
    mutated = replace(
        record,
        lease_expires_at=new_lease_expires_at,
        updated_at=_iso_z(now),
        version=record.version + 1,
    )
    if not jobs.cas_update(mutated, expected_version):
        raise StaleVersion(
            f"CAS lost for job {job_id} at version {expected_version} (re-read required)"
        )
    return mutated


def worker_executing_to_completed(
    jobs: JobStore,
    envelopes: RequestEnvelopeStore,
    job_id: str,
    expected_version: int,
    *,
    result_ref: str,
    now: datetime,
) -> JobRecord:
    """Worker success terminalization: executing -> completed.

    transition_mutations.worker__executing_to_completed: set completed + result_ref; null
    request_ref/error/lease; THEN delete the request envelope. Per terminalization_order
    the result blob is ALREADY written by the caller (producing result_ref), then this
    atomic CAS records it, then the envelope is deleted (TTL is the backstop if the
    delete fails)."""
    record = jobs.get(job_id)
    request_ref = record.request_ref if record is not None else None
    mutated = _guarded_transition(
        jobs,
        job_id,
        actor=Actor.WORKER,
        to_state="completed",
        expected_version=expected_version,
        now=now,
        set_fields={
            "result_ref": result_ref,
            "request_ref": None,
            "error_code": None,
            "lease_owner": None,
            "lease_expires_at": None,
        },
    )
    if request_ref is not None:
        envelopes.delete(request_ref)
    return mutated


def worker_executing_to_failed(
    jobs: JobStore,
    envelopes: RequestEnvelopeStore,
    job_id: str,
    expected_version: int,
    *,
    error_code: str,
    now: datetime,
) -> JobRecord:
    """Worker internal-failure terminalization: executing -> failed.

    transition_mutations.worker__executing_to_failed: set failed + error_code; null
    request_ref/result_ref/lease; THEN delete the request envelope.

    Rejects an error_code outside the schema enum (InvalidErrorCode) at the boundary."""
    _require_valid_error_code(error_code)
    record = jobs.get(job_id)
    request_ref = record.request_ref if record is not None else None
    mutated = _guarded_transition(
        jobs,
        job_id,
        actor=Actor.WORKER,
        to_state="failed",
        expected_version=expected_version,
        now=now,
        set_fields={
            "error_code": error_code,
            "request_ref": None,
            "result_ref": None,
            "lease_owner": None,
            "lease_expires_at": None,
        },
    )
    if request_ref is not None:
        envelopes.delete(request_ref)
    return mutated


def watchdog_executing_to_queued(
    jobs: JobStore, job_id: str, expected_version: int, *, now: datetime
) -> JobRecord:
    """Watchdog stale-lease re-dispatch: executing -> queued (attempt += 1).

    transition_mutations.watchdog__executing_to_queued: set queued, null lease,
    attempt+1, updated_at; request_ref preserved for retry. ONLY valid when the lease is
    STALE (lease_expires_at < now): a LIVE lease is never preempted (LivePreemption)."""
    record = jobs.get(job_id)
    if record is None:
        raise StaleVersion(f"job {job_id} not found (re-read required)")
    if record.state == "executing" and _lease_is_live(record, now):
        raise LivePreemption(
            f"job {job_id} has a live lease; the watchdog must not preempt it"
        )
    return _guarded_transition(
        jobs,
        job_id,
        actor=Actor.WATCHDOG,
        to_state="queued",
        expected_version=expected_version,
        now=now,
        set_fields={
            "lease_owner": None,
            "lease_expires_at": None,
            "attempt": record.attempt + 1,
        },
    )


def watchdog_executing_to_failed(
    jobs: JobStore,
    envelopes: RequestEnvelopeStore,
    job_id: str,
    expected_version: int,
    *,
    error_code: str = "execution_timeout",
    now: datetime,
) -> JobRecord:
    """Watchdog terminalizes a stale lease at the retry bound: executing -> failed.

    Uses the worker__executing_to_failed mutation set (the watchdog co-owns
    executing->failed): set failed + error_code (default execution_timeout); null
    request_ref/result_ref/lease; THEN delete the request envelope. ONLY valid when the
    lease is STALE — a LIVE lease is never preempted (LivePreemption).

    Rejects an error_code outside the schema enum (InvalidErrorCode) at the boundary."""
    _require_valid_error_code(error_code)
    record = jobs.get(job_id)
    if record is None:
        raise StaleVersion(f"job {job_id} not found (re-read required)")
    if record.state == "executing" and _lease_is_live(record, now):
        raise LivePreemption(
            f"job {job_id} has a live lease; the watchdog must not preempt it"
        )
    request_ref = record.request_ref
    mutated = _guarded_transition(
        jobs,
        job_id,
        actor=Actor.WATCHDOG,
        to_state="failed",
        expected_version=expected_version,
        now=now,
        set_fields={
            "error_code": error_code,
            "request_ref": None,
            "result_ref": None,
            "lease_owner": None,
            "lease_expires_at": None,
        },
    )
    if request_ref is not None:
        envelopes.delete(request_ref)
    return mutated


def reconciler_received_to_queued(
    jobs: JobStore, job_id: str, expected_version: int, *, now: datetime
) -> JobRecord:
    """Reconciler dispatch recovery for a stuck `received` job: received -> queued.

    transition_mutations.api__received_to_queued field set (state=queued, updated_at;
    request_ref preserved; lease stays null), actor RECONCILER. NOTE: the reconciler's
    own dispatch_attempt counter is incremented separately (increment_dispatch_attempt,
    a CAS while STILL received) BEFORE this re-dispatch — see the reconciler spec and
    recover_undispatched."""
    return _guarded_transition(
        jobs,
        job_id,
        actor=Actor.RECONCILER,
        to_state="queued",
        expected_version=expected_version,
        now=now,
    )


# --- dispatch_attempt counter (reconciler-owned, CAS while received) -----------


def increment_dispatch_attempt(
    jobs: JobStore, job_id: str, expected_version: int, *, now: datetime
) -> JobRecord:
    """Atomically increment the reconciler's dispatch_attempt while the job is STILL
    `received` (handoff.reconciler.dispatch_recovery_increment:
    atomic_cas_while_received). This is a received -> received self-edge: it does NOT
    change state and is distinct from the watchdog's execution `attempt` (pinned to 0
    while received). Concurrent reconcilers serialize on the version CAS; only one wins
    per generation, the loser observes StaleVersion and re-reads.

    Raises UnauthorizedActor if the job is not `received`; StaleVersion on a version
    mismatch."""
    record = jobs.get(job_id)
    if record is None:
        raise StaleVersion(f"job {job_id} not found (re-read required)")
    if record.version != expected_version:
        raise StaleVersion(
            f"expected version {expected_version}, stored version is {record.version}"
        )
    if record.state != "received":
        raise UnauthorizedActor(
            f"dispatch_attempt may only advance while received, not {record.state}"
        )
    mutated = replace(
        record,
        dispatch_attempt=record.dispatch_attempt + 1,
        updated_at=_iso_z(now),
        version=record.version + 1,
    )
    if not jobs.cas_update(mutated, expected_version):
        raise StaleVersion(
            f"CAS lost for job {job_id} at version {expected_version} (re-read required)"
        )
    return mutated


# --- Lease helpers ------------------------------------------------------------


def _lease_is_live(record: JobRecord, now: datetime) -> bool:
    """A lease is live iff it has an expiry in the future (lease_expires_at >= now). A
    record with no lease_expires_at has no live lease."""
    if record.lease_expires_at is None:
        return False
    return _parse_iso_z(record.lease_expires_at) >= now


# --- Watchdog + reconciler sweeps (operate over the JobStore) -----------------


def recover_stale_leases(
    jobs: JobStore, envelopes: RequestEnvelopeStore, now: datetime, attempt_max: int
) -> list[str]:
    """Watchdog sweep over the job store (execution_lease.stale_recovery).

    For each `executing` record with a STALE lease (lease_expires_at < now):
      - attempt < attempt_max -> watchdog_executing_to_queued (re-dispatch, attempt+1)
      - attempt >= attempt_max -> watchdog_executing_to_failed("execution_timeout")
    A LIVE lease (lease_expires_at >= now) is never touched. Returns the job_ids acted on.

    The request-envelope store is used for the terminalizing (executing->failed) edge so
    the envelope is physically deleted on terminalization per `deleted_on` (re-queue
    preserves the envelope for the retry). The sweep enumerates via the store's snapshot,
    so a stale-version CAS during the sweep is tolerated (skipped this pass, retried next).

    JOB-EXPIRY GUARD (Blocker 3): a record already past its own ``expires_at``
    (now >= job.expires_at) is SKIPPED — recovery must not resurrect an expired job; the
    time-based expiry/purge owns it (410 -> 404)."""
    acted: list[str] = []
    for record in _snapshot(jobs):
        if record.state != "executing" or _lease_is_live(record, now):
            continue
        if now >= _parse_iso_z(record.expires_at):
            # Past its TTL: let expiry/purge own it; do not re-dispatch an expired job.
            continue
        try:
            if record.attempt < attempt_max:
                watchdog_executing_to_queued(jobs, record.job_id, record.version, now=now)
            else:
                watchdog_executing_to_failed(
                    jobs, envelopes, record.job_id, record.version,
                    error_code="execution_timeout", now=now,
                )
            acted.append(record.job_id)
        except (StaleVersion, LivePreemption):
            # Lost a race or the lease became live between snapshot and CAS: skip; the
            # next sweep re-evaluates from a fresh read.
            continue
    return acted


def recover_undispatched(
    jobs: JobStore,
    now: datetime,
    dispatch_max: int,
    *,
    grace: object,
    enqueue: Callable[[str, int], bool],
) -> list[str]:
    """Reconciler sweep over the job store (handoff.reconciler dispatch recovery).

    TWO-PHASE DISPATCH (Blocker 2): the reconciler must NEVER flip received->queued without
    a SUCCESSFUL enqueue. For each `received` record older than a small grace
    (created_at + grace <= now) that is still `received`:
      1. ``increment_dispatch_attempt`` (CAS WHILE received) — names the fresh, never-yet-
         tombstoned recovery generation ({job_id}-r{dispatch_attempt}).
      2. call the injected ``enqueue(job_id, dispatch_attempt)`` — True means the task was
         enqueued (or a valid ALREADY_EXISTS for a still-pending task); False or a raised
         exception means the enqueue FAILED.
      3. ONLY on a successful/accepted-existing enqueue, ``reconciler_received_to_queued``
         (received->queued). On enqueue failure/exception the record is LEFT `received`
         (recoverable on the next sweep) and is NOT moved to queued — so a `queued` record
         always corresponds to a real enqueue.

    Bounds/skips:
      - dispatch_attempt >= dispatch_max -> STOP re-enqueueing (the job terminates by
        time-based expiry 410 -> 404; on_dispatch_exhausted). Left untouched.
      - now >= job.expires_at -> SKIP (Blocker 3): recovery must not resurrect an expired
        job; the time-based expiry/purge owns it.

    Returns the job_ids actually re-dispatched (enqueued AND CAS'd to queued).

    ``grace`` is a timedelta (typed loosely to avoid importing datetime symbols into the
    signature); a record is eligible once created_at + grace <= now. ``enqueue`` is injected
    so the queue adapter (Cloud Tasks, WP-02C) is decoupled from the record-CAS protocol;
    concurrent reconcilers serialize on the version CAS so exactly one wins a generation
    (the loser sees StaleVersion and is skipped without enqueueing or flipping state)."""
    acted: list[str] = []
    for record in _snapshot(jobs):
        if record.state != "received":
            continue
        if _parse_iso_z(record.created_at) + grace > now:  # type: ignore[operator]
            continue
        if now >= _parse_iso_z(record.expires_at):
            # Past its TTL: let expiry/purge own it; do not re-dispatch an expired job.
            continue
        if record.dispatch_attempt >= dispatch_max:
            # Exhausted: stop re-enqueueing; time-based expiry terminates the job.
            continue
        try:
            # Phase 1: CAS the dispatch_attempt while STILL received (fresh, never-
            # tombstoned generation). A concurrent reconciler that won this generation
            # makes this raise StaleVersion -> the loser is skipped (no enqueue, no flip).
            bumped = increment_dispatch_attempt(jobs, record.job_id, record.version, now=now)
        except (StaleVersion, UnauthorizedActor):
            # Another reconciler won this generation, or the job left `received` between
            # the snapshot and the CAS: skip; the next sweep re-evaluates.
            continue
        # Phase 2: attempt the actual enqueue. A False return OR any raised exception is a
        # failure: leave the record `received` (it stays recoverable) and do NOT queue it.
        try:
            enqueued = enqueue(record.job_id, bumped.dispatch_attempt)
        except Exception:
            # Enqueue raised: treat as a failed dispatch; the bumped dispatch_attempt
            # persists (so the next sweep uses a fresh generation name) but the record
            # remains `received`.
            continue
        if not enqueued:
            continue
        # Phase 3: enqueue succeeded (or accepted an existing pending task) -> only NOW
        # flip received->queued via the declared edge.
        try:
            reconciler_received_to_queued(jobs, record.job_id, bumped.version, now=now)
        except (StaleVersion, UnauthorizedActor):
            # The job left `received` between the enqueue and this CAS (e.g. a worker
            # recovered it): skip; the enqueued task is deduped by the worker's CAS.
            continue
        acted.append(record.job_id)
    return acted


# --- Internal sweep helpers ---------------------------------------------------


def _snapshot(jobs: JobStore) -> list[JobRecord]:
    """Return a stable list of the store's current records for a sweep pass.

    Each sweep mutation re-reads via ``jobs.get`` inside its guarded transition, so the
    snapshot is only an enumeration source — the CAS still runs against the freshest
    stored version (a record that changed between snapshot and CAS is skipped)."""
    return jobs.iter_records()
