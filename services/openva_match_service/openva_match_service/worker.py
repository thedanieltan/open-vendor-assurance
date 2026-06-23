"""Async verify worker + watchdog/reconciler wiring (WP-02C).

This is the provider-neutral execution layer that turns a delivered ``job_id`` into a
durable result, using ONLY the WP-02B lifecycle transitions (``job_lifecycle``), the
WP-02A/02B stores (``verify_transport``), the provider-neutral queue (``queue``), and the
SSRF-safe resolver (``tools.openva.vendor_resolution``). It ships NO cloud SDK, NO live
endpoint, and NO infrastructure; it is OFF by default (only constructed/run when the
verify transport is enabled — see ``app.create_app``).

Authoritative spec: docs/operations/contracts/hosted-deployment.yaml — ``handoff`` (worker
per-delivery algorithm, duplicate_delivery, reconciler), ``execution_lease`` (lease +
heartbeat + stale recovery), ``access_matrix.async_worker`` (owned CAS edges; the worker
holds ``github_app_key: none``), ``terminalization_order`` (write blob -> CAS
executing->completed -> delete envelope), ``verify_execution_budget`` /
``hosted_verify_limits`` (per-job budget, row caps, row concurrency).

Per-delivery algorithm (``handoff.worker``):
  1. Re-read the record. If terminal, or executing with a LIVE lease -> ack-and-drop
     (duplicate delivery). If ``received`` -> recovery CAS ``worker_received_to_queued``.
  2. CAS ``worker_queued_to_executing`` taking a strictly-future lease. A lost CAS
     (StaleVersion / not queued / live-preemption) -> ack-and-drop.
  3. Re-read the request envelope by ``request_ref``. Gone -> fail closed
     (``worker_executing_to_failed(internal_error)``).
  4. Execute the verify over the SSRF-safe resolver, bounded by ``hosted_verify_limits``
     and the per-job execution budget; heartbeat the lease during execution.
  5. Terminalize in contract order: write the result blob, then
     ``worker_executing_to_completed(result_ref)`` (atomic CAS that also nulls request_ref
     + lease), then the lifecycle deletes the envelope. On failure ->
     ``worker_executing_to_failed(error_code)``.

The worker NEVER reads or holds a GitHub credential and NEVER fetches an arbitrary URL: it
calls the resolver with the SSRF-safe ``default_fetcher_factory`` so every fetch goes
through the DNS-pinned, private/loopback-rejecting safe boundary.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from tools.openva.vendor_resolution import (
    SAFE_TIMEOUT_SECONDS,
    _DISCOVERY_PATHS,
    DEFAULT_CHANNEL,
    FRESHNESS_VERIFY,
    ResolutionCatalog,
    default_fetcher_factory,
    resolve_vendor_sources,
)

from . import job_lifecycle as jl
from .candidate_ingress import (
    CandidateProposer,
    captured_records,
    is_proposable_resolution,
    new_session_emitter,
)
from .config import VERIFY_RETAINED_WINDOW_HOURS
from .queue import Delivery, Queue
from .telemetry import NullTelemetry, Telemetry
from .verify_transport import (
    JobRecord,
    JobStore,
    RequestEnvelopeStore,
    ResultStore,
    new_ref,
    purge_expired_jobs,
)

# --- Verify execution budget (recomputed from the resolver constants) ----------
#
# Grounded in the resolver's REAL fetch behaviour, exactly as the contract drift test
# (tests/test_hosted_deployment_docs.py) recomputes it. We import the executable
# constants so the worker's enforced budget can never drift from the resolver or the
# contract. Per source type the resolver does 1 primary verify fetch + up to
# max(len(_DISCOVERY_PATHS)) serial discovery-fallback fetches, each bounded by
# SAFE_TIMEOUT_SECONDS; source types within a row are serial; rows run at
# verify_row_concurrency.
PER_FETCH_DEADLINE_SECONDS = int(SAFE_TIMEOUT_SECONDS)
NETWORK_OPS_PER_SOURCE_TYPE_WORST = 1 + max(len(paths) for paths in _DISCOVERY_PATHS.values())
HANDLER_OVERHEAD_SECONDS = 60

# Per-job execution budget: must be < the Cloud Tasks dispatch deadline so a job can never
# exceed it (the watchdog path applies on timeout). Mirrors
# platform_limits.baseline_per_job_budget_minutes (25m) < cloud_tasks_http_dispatch_deadline
# (30m). Kept as a module constant so it is a single, auditable source.
PER_JOB_BUDGET_SECONDS = 25 * 60

# Hosted live-verify limits (hosted_verify_limits) the worker enforces at execution time.
MAX_VERIFY_ROWS = 20
MAX_SOURCE_TYPES_PER_VERIFY_ROW = 4
VERIFY_ROW_CONCURRENCY = 10

# The core assurance source types the worker resolves when a request did not pin a subset
# (bounded by MAX_SOURCE_TYPES_PER_VERIFY_ROW). The resolver chooses what to FETCH from the
# catalogue/discovery for each; the caller never supplies a fetch-target URL.
DEFAULT_SOURCE_TYPES = ("dpa", "subprocessors_list", "privacy_notice", "security_page")


def worst_case_job_seconds(
    *,
    rows: int,
    source_types: int = MAX_SOURCE_TYPES_PER_VERIFY_ROW,
    row_concurrency: int = VERIFY_ROW_CONCURRENCY,
) -> int:
    """Recompute the worst-case wall time for a job, from the grounded resolver inputs.

    ``ceil(rows / row_concurrency) * source_types * network_ops_per_source_type_worst *
    per_fetch_deadline + handler_overhead`` — the same formula the contract records as
    ``worst_case_seconds_v1`` and the drift test recomputes. Used to assert the worker's
    enforced per-job budget bounds the true worst case."""
    waves = math.ceil(max(rows, 0) / row_concurrency) if rows > 0 else 0
    per_row = source_types * NETWORK_OPS_PER_SOURCE_TYPE_WORST * PER_FETCH_DEADLINE_SECONDS
    return waves * per_row + HANDLER_OVERHEAD_SECONDS


# --- Worker configuration ------------------------------------------------------


@dataclass(frozen=True)
class WorkerConfig:
    """Off-by-default worker settings. The worker is only CONSTRUCTED when the verify
    transport is enabled (see app.create_app); these tune lease/heartbeat/budget."""

    lease_owner: str = "worker-0"
    # Lease TTL: long enough to cover a wave of fetches; the worker heartbeats to extend it
    # while executing. A stale lease is recovered by the watchdog.
    lease_seconds: int = 120
    # Heartbeat when more than this fraction of the lease has elapsed (extend early).
    heartbeat_after_seconds: int = 60
    # Per-job hard execution budget (seconds). Defaults to the contract per-job budget so a
    # job can never exceed the dispatch deadline (the watchdog path applies on timeout).
    per_job_budget_seconds: int = PER_JOB_BUDGET_SECONDS
    # Watchdog execution-retry bound (watchdog re-dispatches stale leases until this, then
    # terminalizes execution_timeout). Distinct from the reconciler's dispatch bound.
    attempt_max: int = 5
    # Reconciler dispatch-recovery bound (handoff.reconciler.dispatch_recovery_max).
    dispatch_max: int = 10
    # Grace before the reconciler re-dispatches an un-dispatched `received` job.
    reconciler_grace_seconds: int = 30


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_proposer_if_enabled(config: Any) -> CandidateProposer | None:
    """Construct the off-by-default candidate proposer from a ServiceConfig.

    Returns the default durable-ingress proposer ONLY when BOTH the verify transport AND
    candidate ingress are explicitly enabled; otherwise None (the worker proposes nothing
    and behaves exactly as the WP-02C worker). This is the single place the off-by-default
    policy lives, so whatever explicitly constructs the worker (the worker is never
    constructed in ``app.create_app``) opts in identically. The proposer holds NO GitHub
    credential — it only stages into the existing durable ingress path."""
    if not (
        getattr(config, "verify_transport_enabled", False)
        and getattr(config, "candidate_ingress_enabled", False)
    ):
        return None
    # Import lazily so the default (off) path never touches the durable-ingress module.
    from .candidate_ingress import DurableIngressProposer

    return DurableIngressProposer()


# --- The async worker ----------------------------------------------------------


class VerifyWorker:
    """Per-delivery verify executor. Construct ONCE per worker process (off by default);
    call ``process(delivery)`` for each delivery the queue hands out, or ``run_once()`` to
    drain the queue in tests.

    Dependencies are injected so tests can supply a FAKE resolver/fetcher and a deterministic
    clock with NO real network. In production ``resolve`` defaults to the real SSRF-safe
    resolver (``resolve_vendor_sources`` with ``default_fetcher_factory``)."""

    def __init__(
        self,
        jobs: JobStore,
        envelopes: RequestEnvelopeStore,
        results: ResultStore,
        queue: Queue,
        *,
        catalog: ResolutionCatalog | None = None,
        config: WorkerConfig | None = None,
        resolve: Callable[..., Any] | None = None,
        fetcher_factory: Callable[[list[str]], Any] = default_fetcher_factory,
        now: Callable[[], datetime] | None = None,
        result_ttl_hours: int = 24,
        proposer: CandidateProposer | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.jobs = jobs
        self.envelopes = envelopes
        self.results = results
        self.queue = queue
        self.catalog = catalog
        self.config = config or WorkerConfig()
        # OPTIONAL, off-by-default discovery boundary (WP-02D). When None (default), the
        # worker behaves exactly as the WP-02C worker: it proposes NO candidates. When
        # present (only when the verify transport is enabled AND ingress is explicitly turned
        # on), genuinely newly-discovered public sources are proposed into the EXISTING
        # durable candidate ingress AFTER the job is terminalized — discovery is a side
        # output that never gates the verify result. The worker still holds NO GitHub
        # credential: the proposer only stages records into the existing ingress path.
        self._proposer = proposer
        # Provider-neutral telemetry (WP-02H). Defaults to the no-op sink so the worker's
        # behaviour is unchanged unless a sink is injected. Every emission is redacted by
        # the sink; the worker only ever passes job_id (a correlation id, not a credential)
        # and an outcome token — never identities, rows, or the request envelope.
        self.telemetry = telemetry or NullTelemetry()
        # The resolver entry point. Defaults to the real, SSRF-safe resolver; tests inject a
        # fake. The worker ALWAYS passes the SSRF-safe fetcher_factory (never an arbitrary
        # fetcher) so a malicious/loopback target is rejected at the safe boundary.
        self._resolve = resolve or resolve_vendor_sources
        self._fetcher_factory = fetcher_factory
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._result_ttl_hours = result_ttl_hours

    # -- public delivery entry point --------------------------------------------

    def process(self, delivery: Delivery) -> str:
        """Process one delivery. Returns a short outcome token (for tests/telemetry):
        ``completed`` | ``failed`` | ``dropped``. ALWAYS acks the delivery at the end
        (success, fail-closed, or ack-and-drop) so the task name is tombstoned — the
        reconciler re-dispatches under a fresh name if needed."""
        try:
            outcome = self._process(delivery)
            # Outcome counter keyed only on a bounded low-cardinality label, plus a
            # structured event with job_id (correlation id). No identities/rows ever.
            self.telemetry.increment("verify_jobs_total", outcome=outcome)
            self.telemetry.log("verify_job_processed", job_id=delivery.job_id, outcome=outcome)
            return outcome
        finally:
            # Ack-and-drop / terminalize both ack the task (handoff.duplicate_delivery:
            # ack_and_drop_if_cas_to_executing_fails; a 2xx handler return acks in Cloud
            # Tasks). The name is tombstoned; recovery uses a fresh -r{n} name.
            self.queue.ack(delivery)

    def _process(self, delivery: Delivery) -> str:
        job_id = delivery.job_id
        now = self._now()

        record = self.jobs.get(job_id)
        if record is None:
            # Purged/never existed: nothing to do (re-read semantics; never a 500).
            return "dropped"
        if record.is_terminal():
            # Already completed/failed -> duplicate delivery, ack-and-drop.
            return "dropped"
        if record.state == "executing" and jl._lease_is_live(record, now):
            # Executing with a LIVE lease -> duplicate delivery, never preempt; ack-and-drop.
            return "dropped"

        # Recovery: a delivered job still in `received` means the API crashed before its
        # own received->queued CAS. Promote it via the worker recovery edge.
        if record.state == "received":
            try:
                record = jl.worker_received_to_queued(self.jobs, job_id, record.version, now=now)
            except (jl.StaleVersion, jl.LifecycleError):
                # Lost the race (another actor advanced it) -> ack-and-drop.
                return "dropped"

        # Take the lease: queued -> executing. A lost CAS / not-queued / live-preemption
        # is a duplicate delivery -> ack-and-drop.
        if record.state != "queued":
            return "dropped"
        lease_expires_at = _iso_z(now + timedelta(seconds=self.config.lease_seconds))
        try:
            record = jl.worker_queued_to_executing(
                self.jobs,
                job_id,
                record.version,
                lease_owner=self.config.lease_owner,
                lease_expires_at=lease_expires_at,
                now=now,
            )
        except (jl.StaleVersion, jl.LivePreemption, jl.LifecycleError):
            return "dropped"

        # Re-read the request envelope (the queue never carried it). Gone -> fail closed.
        envelope = (
            self.envelopes.get(record.request_ref) if record.request_ref is not None else None
        )
        if envelope is None:
            return self._fail(job_id, record.version, "internal_error", now=now)

        rows, source_types = _envelope_request(envelope)
        if not rows:
            # Nothing executable in the envelope (minimised/empty): fail closed rather than
            # publish an empty/ambiguous result.
            return self._fail(job_id, record.version, "internal_error", now=now)

        # WP-02D: capture discovered candidate records during execution ONLY when a proposer
        # is wired (off by default). When off, the resolver is called exactly as in WP-02C
        # and nothing is captured; the verify result is byte-identical either way.
        capture = self._proposer is not None

        # Execute the verify bounded by the hosted limits + the per-job budget.
        try:
            result_payload, record, discovered = self._execute(
                record, rows, source_types, capture=capture
            )
        except _JobTimeout:
            # Over the per-job budget: leave the lease to expire and let the watchdog path
            # apply (executing->queued re-dispatch / executing->failed execution_timeout).
            # Do NOT terminalize here so the watchdog owns the timeout edge.
            return "dropped"
        except Exception:  # noqa: BLE001 - any execution error fails the job closed
            return self._fail(job_id, record.version, "internal_error", now=now)

        # Terminalize in the CONTRACT order: write blob -> CAS executing->completed -> the
        # lifecycle deletes the envelope. The result blob carries its own expiry so it is
        # reaped independently if the worker crashes before the CAS.
        result_ref = new_ref()
        terminal_now = self._now()
        result_expires_at = _iso_z(
            terminal_now + timedelta(hours=self._result_ttl_hours)
        )
        self.results.put(result_ref, result_payload, result_expires_at)
        try:
            jl.worker_executing_to_completed(
                self.jobs,
                self.envelopes,
                job_id,
                record.version,
                result_ref=result_ref,
                now=terminal_now,
            )
        except jl.LifecycleError:
            # Lost the terminal CAS (e.g. the watchdog requeued an expired lease, or the job
            # expired): drop the orphan result blob (its TTL also reaps it) and ack-and-drop.
            # No partial `completed` is ever written — the CAS is the single atomic step.
            self.results.delete(result_ref)
            return "dropped"

        # Discovery side output (WP-02D): the job is now terminal (completed). ONLY now —
        # never before, never as a precondition — propose any genuinely newly-discovered
        # public sources into the EXISTING durable candidate ingress. This NEVER changes the
        # verify result and a proposer failure NEVER fails the verify job (the result blob is
        # already written and the record is already `completed`).
        if self._proposer is not None:
            self._propose_discoveries(discovered, result_payload)
        return "completed"

    def _propose_discoveries(
        self, discovered: list[dict[str, Any]], result_payload: dict[str, Any]
    ) -> None:
        """Best-effort: stage discovered candidates into the existing durable ingress.

        Runs AFTER terminalization. Only when at least one row surfaced a genuinely-new
        discovery (an already-catalogued / current / not-found / ambiguous resolution
        proposes nothing) are the captured candidate records — the resolver's own
        deterministic builds — handed to the existing ingress. Every failure is swallowed:
        discovery is a side output that must never gate or fail the (already terminal) verify
        result. The worker holds no GitHub credential — the proposer only enqueues into the
        existing ingress path."""
        try:
            rows = result_payload.get("rows") if isinstance(result_payload, dict) else None
            if not isinstance(rows, list):
                return
            if not any(is_proposable_resolution(row) for row in rows):
                return
            if discovered:
                self._proposer.propose(discovered)
        except Exception:  # noqa: BLE001 - discovery must never fail a terminal verify job
            return

    # -- execution --------------------------------------------------------------

    def _execute(
        self,
        record: JobRecord,
        rows: list[dict[str, Any]],
        source_types: list[str],
        *,
        capture: bool = False,
    ) -> tuple[dict[str, Any], JobRecord, list[dict[str, Any]]]:
        """Resolve every row via the SSRF-safe resolver, bounded by the hosted limits and
        the per-job execution budget, heartbeating the lease throughout.

        Rows may run at ``verify_row_concurrency``; source types within a row are serial
        (the resolver iterates them serially). Returns
        ``(result_payload, latest_record, discovered_records)`` — ``discovered_records`` is
        the deduplicated set of candidate records the resolver built during execution (empty
        unless ``capture`` is set; WP-02D). Raises ``_JobTimeout`` if the per-job budget is
        exceeded (the watchdog path applies)."""
        # Enforce the row cap defensively (the API already rejects > max_verify_rows).
        if len(rows) > MAX_VERIFY_ROWS:
            raise ValueError(f"verify job has {len(rows)} rows; max is {MAX_VERIFY_ROWS}")
        bounded_source_types = list(source_types)[:MAX_SOURCE_TYPES_PER_VERIFY_ROW]

        deadline = time.monotonic() + self.config.per_job_budget_seconds
        last_heartbeat = time.monotonic()
        lease_owner = self.config.lease_owner

        def _resolve_row(row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            request = {
                "vendor": _identity_only(row),
                "required_source_types": bounded_source_types,
                "freshness_mode": FRESHNESS_VERIFY,
                "channel": DEFAULT_CHANNEL,
            }
            # WP-02D: a PER-ROW capture-only emitter (never shared across the concurrent
            # rows, so no cross-thread mutation of emitter state) lets the resolver build
            # candidate records in memory; durable staging happens later, AFTER
            # terminalization. Present only when a proposer is wired; otherwise the call is
            # exactly the WP-02C call and nothing is captured.
            emitter = new_session_emitter() if capture else None
            # SSRF boundary: the worker ALWAYS passes the safe fetcher_factory and NEVER an
            # arbitrary `fetcher`, so every fetch is DNS-pinned + private/loopback-rejecting.
            extra: dict[str, Any] = {"emitter": emitter} if emitter is not None else {}
            resolution = self._resolve(
                request,
                catalog=self.catalog,
                fetcher_factory=self._fetcher_factory,
                **extra,
            )
            captured = captured_records(emitter) if emitter is not None else []
            return _row_result(row, resolution), captured

        results: list[dict[str, Any]] = []
        discovered: dict[str, dict[str, Any]] = {}
        # Rows run at up to verify_row_concurrency (never more than the contract cap, never
        # more than the row count). A one-row job runs effectively serially.
        concurrency = max(1, min(VERIFY_ROW_CONCURRENCY, len(rows)))
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_resolve_row, row): row for row in rows}
            for future in as_completed(futures):
                if time.monotonic() > deadline:
                    raise _JobTimeout()
                row_result, captured = future.result()
                results.append(row_result)
                # Dedup captured candidates by deterministic candidate id across rows so a
                # discovery surfaced by two rows proposes one candidate (the durable ingress
                # also dedups; this keeps the proposed set minimal).
                for candidate in captured:
                    discovered[candidate["candidate_id"]] = candidate
                # Heartbeat the lease during long execution so the watchdog does not preempt
                # a live, progressing job.
                if time.monotonic() - last_heartbeat >= self.config.heartbeat_after_seconds:
                    record = self._heartbeat(record, lease_owner)
                    last_heartbeat = time.monotonic()

        if time.monotonic() > deadline:
            raise _JobTimeout()

        # Deterministic order: by the row's reported index/row_id then sequence.
        results.sort(key=lambda r: str(r.get("row_id") if r.get("row_id") is not None else ""))
        payload = {
            "schema_version": "0.1.0",
            "freshness_mode": FRESHNESS_VERIFY,
            "row_count": len(results),
            "rows": results,
            "not_advice": True,
        }
        # Deterministic candidate order (by candidate id) for the discovered set.
        discovered_records = [discovered[cid] for cid in sorted(discovered)]
        return payload, record, discovered_records

    def _heartbeat(self, record: JobRecord, lease_owner: str) -> JobRecord:
        """Extend the lease via the lifecycle heartbeat; re-read on a lost CAS so the next
        heartbeat uses the fresh version. Never raises into execution (a failed heartbeat
        just lets the lease run toward expiry, where the watchdog owns recovery)."""
        now = self._now()
        new_deadline = _iso_z(now + timedelta(seconds=self.config.lease_seconds))
        try:
            return jl.worker_heartbeat(
                self.jobs,
                record.job_id,
                record.version,
                lease_owner=lease_owner,
                new_lease_expires_at=new_deadline,
                now=now,
            )
        except jl.LifecycleError:
            fresh = self.jobs.get(record.job_id)
            return fresh if fresh is not None else record

    def _fail(self, job_id: str, expected_version: int, error_code: str, *, now: datetime) -> str:
        """Terminalize executing->failed with an allowed error code; the lifecycle deletes
        the envelope. A lost CAS (watchdog already acted / job expired) is dropped."""
        try:
            jl.worker_executing_to_failed(
                self.jobs, self.envelopes, job_id, expected_version, error_code=error_code, now=now
            )
            return "failed"
        except jl.LifecycleError:
            return "dropped"

    # -- queue draining (tests / a thin run loop) --------------------------------

    def run_once(self, *, max_deliveries: int = 1000) -> list[str]:
        """Drain up to ``max_deliveries`` from the queue, processing each. Returns the list
        of per-delivery outcome tokens. A thin, synchronous loop for tests and a simple
        run loop; a production loop would block-poll the provider queue."""
        outcomes: list[str] = []
        for _ in range(max_deliveries):
            delivery = self.queue.poll()
            if delivery is None:
                break
            outcomes.append(self.process(delivery))
        return outcomes


class _JobTimeout(Exception):
    """Internal: the per-job execution budget was exceeded; defer to the watchdog."""


# --- envelope / row shaping ----------------------------------------------------


def _envelope_request(envelope: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract the executable rows + source types from the transient request envelope.

    The worker reconstructs the request from the envelope (the queue never carried it). A
    minimised WP-02A envelope carries only ``row_count`` (no identities) and yields NO rows
    -> the worker fails closed. A WP-02B+ envelope carries ``rows`` (and optionally
    ``source_types``)."""
    if not isinstance(envelope, dict):
        return [], []
    raw_rows = envelope.get("rows")
    rows = [r for r in raw_rows if isinstance(r, dict)] if isinstance(raw_rows, list) else []
    raw_types = envelope.get("source_types")
    source_types = (
        [str(t) for t in raw_types if isinstance(t, str)]
        if isinstance(raw_types, list) and raw_types
        else list(DEFAULT_SOURCE_TYPES)
    )
    return rows, source_types


# Identity fields the resolver accepts; nothing else (no URL) is ever forwarded — the
# resolver chooses what to fetch (the SSRF + transient-input boundary).
_IDENTITY_FIELDS = ("vendor_name", "domain", "business_entity_name", "registration_number")


def _identity_only(row: dict[str, Any]) -> dict[str, Any]:
    """Project a row to its IDENTITY fields only (no url/candidate_url/source_url ever),
    so the worker can never be coerced into fetching a caller-supplied target."""
    return {field: row[field] for field in _IDENTITY_FIELDS if row.get(field) is not None}


def _row_result(row: dict[str, Any], resolution: Any) -> dict[str, Any]:
    """Shape one row's resolver output into the result payload. Accepts either a
    ``VendorResolution`` (has ``to_response``) or a plain dict (a fake resolver in tests)."""
    if hasattr(resolution, "to_response"):
        body = resolution.to_response()
    elif isinstance(resolution, dict):
        body = resolution
    else:
        body = {"resolution_status": str(resolution)}
    return {"row_id": row.get("row_id"), "resolution": body}


# --- Watchdog + reconciler wiring (thin loops over the existing sweeps) ---------


def run_watchdog(
    jobs: JobStore,
    envelopes: RequestEnvelopeStore,
    *,
    now: datetime,
    attempt_max: int,
) -> list[str]:
    """One watchdog pass (execution_lease.stale_recovery).

    Delegates to ``job_lifecycle.recover_stale_leases``: for each `executing` record with a
    STALE lease, re-dispatch (executing->queued, attempt++) while attempt < attempt_max,
    else terminalize executing->failed ``execution_timeout``. A LIVE lease is never
    preempted (enforced by the sweep). Returns the job_ids acted on."""
    return jl.recover_stale_leases(jobs, envelopes, now, attempt_max)


def run_reconciler(
    jobs: JobStore,
    queue: Queue,
    *,
    now: datetime,
    dispatch_max: int,
    grace: timedelta,
) -> list[str]:
    """One reconciler pass (handoff.reconciler dispatch recovery).

    Delegates to ``job_lifecycle.recover_undispatched`` with a queue-backed two-phase
    ``enqueue``: phase 1 ``increment_dispatch_attempt`` (CAS while received) names the fresh
    ``{job_id}-r{dispatch_attempt}`` recovery generation; phase 2 enqueues that named task
    (an ALREADY_EXISTS pending OR tombstoned name returns False -> the record stays
    `received` for the next pass under a fresh generation); phase 3 ``reconciler_received_to_queued``
    only on a successful enqueue. Bounded by ``dispatch_max``; a live lease is never
    preempted (the reconciler only touches `received` records). Returns the job_ids
    re-dispatched."""

    def _enqueue(job_id: str, dispatch_attempt: int) -> bool:
        # The recovery generation IS the dispatch_attempt; the queue names the task
        # {job_id}-r{dispatch_attempt}. A still-pending name (ALREADY_EXISTS) or a
        # tombstoned name returns False -> recover_undispatched leaves the record received.
        return queue.enqueue(job_id, dispatch_attempt=dispatch_attempt)

    return jl.recover_undispatched(
        jobs, now, dispatch_max, grace=grace, enqueue=_enqueue
    )


def purge_expired(
    jobs: JobStore,
    envelopes: RequestEnvelopeStore,
    results: ResultStore,
    *,
    now: datetime,
    retained_window: timedelta | None = None,
) -> list[str]:
    """Advance the three-phase TTL expiry on the stores (delegates to
    ``verify_transport.purge_expired_jobs``). A thin helper so a worker run loop can reap
    expired records/blobs alongside the watchdog/reconciler passes."""
    window = retained_window or timedelta(hours=VERIFY_RETAINED_WINDOW_HOURS)
    return purge_expired_jobs(jobs, envelopes, results, now, window)
