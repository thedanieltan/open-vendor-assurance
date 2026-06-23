"""WP-02C async worker + queue tests.

Exercises the provider-neutral queue (dedup/tombstone naming), the per-delivery worker
algorithm (recovery CAS, lease + heartbeat, terminalization order, duplicate-delivery
ack-and-drop, fail-closed on a missing envelope), the SSRF-safe boundary, the
verify-execution-budget consistency (recomputed from the imported resolver constants), and
the watchdog/reconciler wiring.

All tests are DETERMINISTIC with NO real network: the resolver/fetcher is a FAKE injected
into the worker, and time is a controllable clock. Parametrized over the in-memory and the
durable SQLite stores (like tests/test_hosted_job_lifecycle.py).

Authoritative spec: docs/operations/contracts/hosted-deployment.yaml (handoff,
execution_lease, access_matrix, terminalization_order, verify_execution_budget).
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service import job_lifecycle as jl  # noqa: E402
from openva_match_service import worker as wk  # noqa: E402
from openva_match_service.queue import Delivery, InMemoryQueue, task_name  # noqa: E402
from openva_match_service.sqlite_stores import (  # noqa: E402
    SqliteJobStore,
    SqliteRequestEnvelopeStore,
    SqliteResultStore,
)
from openva_match_service.verify_transport import (  # noqa: E402
    InMemoryJobStore,
    InMemoryRequestEnvelopeStore,
    InMemoryResultStore,
    JobRecord,
    new_job_id,
    new_job_token,
    new_ref,
    token_digest,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Store fixtures (parametrized over in-memory + durable SQLite) -------------


def _in_memory_stores():
    return InMemoryJobStore(), InMemoryRequestEnvelopeStore(), InMemoryResultStore()


def _sqlite_stores(tmp_path):
    db = str(tmp_path / "wp02c.db")
    return SqliteJobStore(db), SqliteRequestEnvelopeStore(db), SqliteResultStore(db)


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return _in_memory_stores()
    return _sqlite_stores(tmp_path)


def make_received(jobs, envelopes, *, now=None, expires_in=timedelta(hours=24), rows=None):
    """Create a fresh `received` record + an executable envelope (carrying identity rows so
    the worker can reconstruct the request) and return (record, token)."""
    now = now or _now()
    if rows is None:
        rows = [{"row_id": "1", "vendor_name": "Acme", "domain": "acme.test"}]
    token = new_job_token()
    request_ref = new_ref()
    expires_at = _iso(now + expires_in)
    record = JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(token),
        state="received",
        request_ref=request_ref,
        row_count=len(rows),
        created_at=_iso(now),
        updated_at=_iso(now),
        expires_at=expires_at,
    )
    jobs.create(record)
    envelopes.put(
        request_ref,
        {"row_count": len(rows), "rows": rows, "source_types": ["dpa", "privacy_notice"]},
        expires_at,
    )
    return record, token


def to_queued(jobs, record, *, now=None):
    """Advance a fresh `received` record to `queued` via the API edge (the normal path)."""
    now = now or _now()
    return jl.api_received_to_queued(jobs, record.job_id, record.version, now=now)


# --- Fake resolver -------------------------------------------------------------


class FakeResolver:
    """A deterministic stand-in for vendor_resolution.resolve_vendor_sources.

    Records every call so a test can assert the worker ALWAYS passed the SSRF-safe
    fetcher_factory (never an arbitrary fetcher) and never a fetch-target URL. Returns a
    plain dict (the worker shapes either a VendorResolution or a dict)."""

    def __init__(self):
        self.calls = []

    def __call__(self, request, *, catalog=None, fetcher_factory=None, **kwargs):
        self.calls.append(
            {"request": request, "fetcher_factory": fetcher_factory, "kwargs": kwargs}
        )
        vendor = request.get("vendor", {})
        return {
            "resolution_status": "catalog_current",
            "vendor": vendor,
            "not_advice": True,
        }


def make_worker(stores, queue, *, resolver=None, config=None, now=None, fetcher_factory=None):
    jobs, envelopes, results = stores
    return wk.VerifyWorker(
        jobs,
        envelopes,
        results,
        queue,
        catalog=None,
        config=config or wk.WorkerConfig(),
        resolve=resolver or FakeResolver(),
        fetcher_factory=fetcher_factory if fetcher_factory is not None else wk.default_fetcher_factory,
        now=now or _now,
    )


# --- queue: naming, dedup, tombstone ------------------------------------------


def test_queue_generation_0_uses_bare_job_id_and_recovery_uses_suffix():
    assert task_name("uuid", 0) == "uuid"
    assert task_name("uuid", 1) == "uuid-r1"
    assert task_name("uuid", 7) == "uuid-r7"


def test_queue_dedup_pending_and_tombstone_after_ack():
    q = InMemoryQueue()
    # First create -> a new task.
    assert q.enqueue("job", dispatch_attempt=0) is True
    # Re-create the SAME pending name -> ALREADY_EXISTS dedup, no new task.
    assert q.enqueue("job", dispatch_attempt=0) is False
    assert q.pending_names() == frozenset({"job"})
    delivery = q.poll()
    assert delivery is not None and delivery.job_id == "job" and delivery.task_name == "job"
    q.ack(delivery)
    # The acked name is tombstoned and cannot be recreated.
    assert q.enqueue("job", dispatch_attempt=0) is False
    assert q.poll() is None
    # A FRESH recovery generation name is creatable (the reconciler's recovery path).
    assert q.enqueue("job", dispatch_attempt=1) is True
    assert q.poll().task_name == "job-r1"


# --- worker happy path: execute, write blob, complete, delete envelope ---------


def test_worker_executes_via_resolver_completes_and_deletes_envelope(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    record, _ = make_received(jobs, envelopes)
    to_queued(jobs, record)
    q.enqueue(record.job_id, dispatch_attempt=0)
    resolver = FakeResolver()
    worker = make_worker(stores, q, resolver=resolver)

    outcomes = worker.run_once()
    assert outcomes == ["completed"]

    final = jobs.get(record.job_id)
    assert final.state == "completed"
    assert final.result_ref is not None
    # No partial completed: request_ref + lease nulled by the single atomic CAS.
    assert final.request_ref is None
    assert final.lease_owner is None and final.lease_expires_at is None
    # The result blob is present and content-shaped.
    blob = results.get(final.result_ref)
    assert blob is not None and blob["row_count"] == 1
    assert blob["rows"][0]["resolution"]["resolution_status"] == "catalog_current"
    # The request envelope was deleted on terminalization.
    assert envelopes.get(record.request_ref) is None
    # The resolver was actually invoked for the row.
    assert len(resolver.calls) == 1


# --- SSRF-negative: worker uses the safe fetcher boundary, refuses caller URLs --


def test_worker_always_uses_safe_fetcher_factory_and_never_a_fetch_target_url(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    # A row that maliciously carries a loopback/private URL alongside identity fields.
    rows = [
        {
            "row_id": "1",
            "vendor_name": "Acme",
            "domain": "acme.test",
            "url": "http://127.0.0.1/admin",
            "candidate_url": "http://169.254.169.254/latest/meta-data/",
        }
    ]
    record, _ = make_received(jobs, envelopes, rows=rows)
    to_queued(jobs, record)
    q.enqueue(record.job_id, dispatch_attempt=0)
    resolver = FakeResolver()
    worker = make_worker(stores, q, resolver=resolver)

    worker.run_once()

    assert len(resolver.calls) == 1
    call = resolver.calls[0]
    # The worker passes the SSRF-safe fetcher_factory (the safe boundary), NOT an arbitrary
    # `fetcher`; resolution therefore goes through DNS-pinned, private/loopback-rejecting
    # fetches only.
    assert call["fetcher_factory"] is wk.default_fetcher_factory
    assert "fetcher" not in call["kwargs"]
    # The malicious URLs are stripped: only identity fields reach the resolver, so the
    # worker can never be coerced into fetching a caller-supplied loopback/private target.
    vendor = call["request"]["vendor"]
    assert "url" not in vendor and "candidate_url" not in vendor
    assert vendor == {"vendor_name": "Acme", "domain": "acme.test"}


def test_safe_fetcher_factory_rejects_loopback_and_private_targets():
    # The default fetcher the worker uses is the resolver's SSRF-safe factory. Bind it to a
    # vendor authority and confirm a loopback / link-local target is NOT a candidate (the
    # safe boundary surfaces http_status=None rather than fetching it).
    fetcher = wk.default_fetcher_factory(["acme.test"])
    for target in ("http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data/"):
        result = fetcher(target)
        assert result.http_status is None  # refused at the safe boundary, never fetched


# --- verify_execution_budget recomputed from imported resolver constants -------


def test_worker_budget_consistent_with_resolver_constants_and_contract():
    from tools.openva.vendor_resolution import SAFE_TIMEOUT_SECONDS, _DISCOVERY_PATHS

    # per_fetch deadline == the resolver's real timeout.
    assert wk.PER_FETCH_DEADLINE_SECONDS == int(SAFE_TIMEOUT_SECONDS)
    assert SAFE_TIMEOUT_SECONDS == 20.0
    # network ops per source type == 1 verify + max discovery-fallback paths.
    max_discovery_paths = max(len(paths) for paths in _DISCOVERY_PATHS.values())
    assert wk.NETWORK_OPS_PER_SOURCE_TYPE_WORST == 1 + max_discovery_paths

    # Recompute the worst case the worker's helper produces and check it matches the
    # contract's grounded formula and figure (700s for the v1 limits).
    waves = math.ceil(wk.MAX_VERIFY_ROWS / wk.VERIFY_ROW_CONCURRENCY)
    expected = (
        waves
        * wk.MAX_SOURCE_TYPES_PER_VERIFY_ROW
        * wk.NETWORK_OPS_PER_SOURCE_TYPE_WORST
        * wk.PER_FETCH_DEADLINE_SECONDS
        + wk.HANDLER_OVERHEAD_SECONDS
    )
    assert wk.worst_case_job_seconds(rows=wk.MAX_VERIFY_ROWS) == expected
    assert expected == 700

    # Ordering invariant the worker ENFORCES: worst case < per-job budget < dispatch deadline.
    worst_seconds = wk.worst_case_job_seconds(rows=wk.MAX_VERIFY_ROWS)
    per_job_budget = wk.PER_JOB_BUDGET_SECONDS
    dispatch_deadline = 30 * 60
    assert worst_seconds < per_job_budget < dispatch_deadline


def test_worker_per_job_budget_timeout_defers_to_watchdog(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    record, _ = make_received(jobs, envelopes)
    to_queued(jobs, record)
    q.enqueue(record.job_id, dispatch_attempt=0)

    # A resolver that "takes too long" relative to a 0s budget: the worker raises its
    # internal timeout and leaves the lease to expire (the watchdog owns the timeout edge).
    def slow_resolver(request, *, catalog=None, fetcher_factory=None, **kwargs):
        return {"resolution_status": "catalog_current"}

    worker = make_worker(stores, q, resolver=slow_resolver, config=wk.WorkerConfig(per_job_budget_seconds=0))
    outcomes = worker.run_once()
    assert outcomes == ["dropped"]
    # The job stays executing with its (now soon-to-be-stale) lease; NOT terminalized by the
    # worker — the watchdog will recover it.
    after = jobs.get(record.job_id)
    assert after.state == "executing"
    assert after.lease_owner is not None


# --- lease heartbeat extends a live lease --------------------------------------


def test_heartbeat_extends_a_live_lease(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    record, _ = make_received(jobs, envelopes)
    queued = to_queued(jobs, record)
    base = _now()
    executing = jl.worker_queued_to_executing(
        jobs, record.job_id, queued.version,
        lease_owner="worker-0", lease_expires_at=_iso(base + timedelta(seconds=60)), now=base,
    )
    worker = make_worker(stores, q, now=lambda: base + timedelta(seconds=30))
    extended = worker._heartbeat(executing, "worker-0")
    # The lease deadline moved strictly forward and the version bumped.
    assert jl._parse_lease(extended.lease_expires_at, what="x") > jl._parse_lease(
        executing.lease_expires_at, what="x"
    )
    assert extended.version == executing.version + 1
    assert extended.state == "executing"


# --- watchdog recovers a stale lease; live lease never preempted ---------------


def test_watchdog_redispatches_stale_lease_then_fails_at_bound(stores):
    jobs, envelopes, results = stores
    base = _now()
    record, _ = make_received(jobs, envelopes, now=base)
    queued = to_queued(jobs, record, now=base)
    # Acquire a lease that will be stale relative to a later `now`.
    jl.worker_queued_to_executing(
        jobs, record.job_id, queued.version,
        lease_owner="w", lease_expires_at=_iso(base + timedelta(seconds=30)), now=base,
    )
    later = base + timedelta(seconds=120)  # lease (base+30s) is now stale
    acted = wk.run_watchdog(jobs, envelopes, now=later, attempt_max=2)
    assert record.job_id in acted
    requeued = jobs.get(record.job_id)
    assert requeued.state == "queued"  # re-dispatched
    assert requeued.attempt == 1
    assert requeued.lease_owner is None

    # Re-acquire + go stale repeatedly. The watchdog re-dispatches (attempt++) while
    # attempt < attempt_max, then terminalizes executing->failed at the bound. Drive cycles
    # until the job is terminal (bounded loop so a regression cannot hang).
    t = later
    for _ in range(10):
        rec = jobs.get(record.job_id)
        if rec.state == "failed":
            break
        # If currently queued, re-acquire a lease that will then go stale.
        if rec.state == "queued":
            jl.worker_queued_to_executing(
                jobs, record.job_id, rec.version,
                lease_owner="w", lease_expires_at=_iso(t + timedelta(seconds=30)), now=t,
            )
        t = t + timedelta(seconds=120)
        wk.run_watchdog(jobs, envelopes, now=t, attempt_max=2)
    final = jobs.get(record.job_id)
    assert final.state == "failed"
    assert final.error_code == "execution_timeout"


def test_watchdog_never_preempts_a_live_lease(stores):
    jobs, envelopes, results = stores
    base = _now()
    record, _ = make_received(jobs, envelopes, now=base)
    queued = to_queued(jobs, record, now=base)
    jl.worker_queued_to_executing(
        jobs, record.job_id, queued.version,
        lease_owner="w", lease_expires_at=_iso(base + timedelta(seconds=300)), now=base,
    )
    # `now` is well within the live lease -> the watchdog acts on nothing.
    acted = wk.run_watchdog(jobs, envelopes, now=base + timedelta(seconds=60), attempt_max=5)
    assert acted == []
    assert jobs.get(record.job_id).state == "executing"


# --- recovery CAS path: delivered job still in `received` ----------------------


def test_worker_recovers_received_then_executes(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    # The API crashed before its received->queued CAS: the job is delivered still `received`.
    record, _ = make_received(jobs, envelopes)
    q.enqueue(record.job_id, dispatch_attempt=0)
    worker = make_worker(stores, q, resolver=FakeResolver())
    outcomes = worker.run_once()
    assert outcomes == ["completed"]
    final = jobs.get(record.job_id)
    assert final.state == "completed"  # received -> queued -> executing -> completed


# --- duplicate delivery: second delivery acked-and-dropped, no double execution -


def test_duplicate_delivery_is_acked_and_dropped(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    record, _ = make_received(jobs, envelopes)
    to_queued(jobs, record)
    q.enqueue(record.job_id, dispatch_attempt=0)
    resolver = FakeResolver()
    worker = make_worker(stores, q, resolver=resolver)

    # First delivery completes the job.
    first = q.poll()
    assert worker.process(first) == "completed"
    assert len(resolver.calls) == 1

    # A redelivery of the SAME (now terminal) job: the CAS to executing cannot win; the
    # worker acks-and-drops without re-executing.
    second = Delivery(job_id=record.job_id, task_name=first.task_name, dispatch_attempt=0)
    assert worker.process(second) == "dropped"
    assert len(resolver.calls) == 1  # NO double execution
    assert jobs.get(record.job_id).state == "completed"


def test_duplicate_delivery_while_executing_with_live_lease_is_dropped(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    base = _now()
    record, _ = make_received(jobs, envelopes, now=base)
    queued = to_queued(jobs, record, now=base)
    jl.worker_queued_to_executing(
        jobs, record.job_id, queued.version,
        lease_owner="other-worker", lease_expires_at=_iso(base + timedelta(seconds=300)), now=base,
    )
    resolver = FakeResolver()
    worker = make_worker(stores, q, resolver=resolver, now=lambda: base + timedelta(seconds=10))
    delivery = Delivery(job_id=record.job_id, task_name=record.job_id, dispatch_attempt=0)
    # Executing with a LIVE lease held by another worker -> ack-and-drop, never preempt.
    assert worker.process(delivery) == "dropped"
    assert resolver.calls == []
    assert jobs.get(record.job_id).state == "executing"


# --- fail-closed on a missing request envelope --------------------------------


def test_worker_fails_closed_when_envelope_missing(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    record, _ = make_received(jobs, envelopes)
    to_queued(jobs, record)
    # Delete the envelope so the worker cannot reconstruct the request.
    envelopes.delete(record.request_ref)
    q.enqueue(record.job_id, dispatch_attempt=0)
    resolver = FakeResolver()
    worker = make_worker(stores, q, resolver=resolver)
    outcomes = worker.run_once()
    assert outcomes == ["failed"]
    final = jobs.get(record.job_id)
    assert final.state == "failed"
    assert final.error_code == "internal_error"
    assert resolver.calls == []  # never executed


def test_worker_fails_closed_on_minimised_envelope_without_rows(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    # A WP-02A-style minimised envelope: row_count only, no identities -> no executable rows.
    record, _ = make_received(jobs, envelopes)
    envelopes.delete(record.request_ref)
    envelopes.put(record.request_ref, {"row_count": 1}, record.expires_at)
    to_queued(jobs, record)
    q.enqueue(record.job_id, dispatch_attempt=0)
    worker = make_worker(stores, q, resolver=FakeResolver())
    assert worker.run_once() == ["failed"]
    assert jobs.get(record.job_id).error_code == "internal_error"


# --- reconciler re-enqueue uses {job_id}-r{n} names, bounded by dispatch_max ----


def test_reconciler_redispatches_with_recovery_generation_names(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    base = _now()
    # An un-dispatched `received` job older than the grace window (the API crashed after
    # creating the record but before enqueueing).
    record, _ = make_received(jobs, envelopes, now=base - timedelta(minutes=5))
    later = base
    grace = timedelta(seconds=30)

    acted = wk.run_reconciler(jobs, q, now=later, dispatch_max=10, grace=grace)
    assert acted == [record.job_id]
    bumped = jobs.get(record.job_id)
    assert bumped.state == "queued"
    assert bumped.dispatch_attempt == 1  # first recovery generation is 1, never r0
    # The task was enqueued under the recovery-generation name {job_id}-r1.
    assert f"{record.job_id}-r1" in q.pending_names()


def test_reconciler_is_bounded_by_dispatch_recovery_max(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    base = _now()
    record, _ = make_received(jobs, envelopes, now=base)
    # Drive dispatch_attempt to the bound while still `received` (simulating exhausted
    # recovery): once dispatch_attempt >= dispatch_max the reconciler stops re-enqueueing.
    rec = record
    t = base
    for _ in range(3):
        rec = jl.increment_dispatch_attempt(jobs, record.job_id, rec.version, now=t)
        t = t + timedelta(minutes=1)
    assert jobs.get(record.job_id).dispatch_attempt == 3
    # With dispatch_max=3 the job is exhausted -> no further re-dispatch, no new task.
    acted = wk.run_reconciler(
        jobs, q, now=t + timedelta(minutes=1), dispatch_max=3, grace=timedelta(seconds=30)
    )
    assert acted == []
    assert q.pending_names() == frozenset()
    # The job is left `received` (it terminates by time-based expiry, not a persisted state).
    assert jobs.get(record.job_id).state == "received"


def test_reconciler_tombstoned_name_recovers_under_fresh_generation(stores):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    base = _now()
    record, _ = make_received(jobs, envelopes, now=base - timedelta(minutes=5))
    # Tombstone the r0 (bare job_id) name as if the original API task completed/was deleted.
    q.enqueue(record.job_id, dispatch_attempt=0)
    q.ack(q.poll())
    assert q.enqueue(record.job_id, dispatch_attempt=0) is False  # tombstoned

    # The reconciler re-dispatches under a FRESH r1 name (never the tombstoned r0).
    acted = wk.run_reconciler(
        jobs, q, now=base, dispatch_max=10, grace=timedelta(seconds=30)
    )
    assert acted == [record.job_id]
    assert f"{record.job_id}-r1" in q.pending_names()
    assert jobs.get(record.job_id).dispatch_attempt == 1


# --- off-by-default wiring -----------------------------------------------------


def test_queue_created_only_when_verify_transport_enabled():
    from fastapi.testclient import TestClient

    from openva_match_service.app import create_app
    from openva_match_service.config import ServiceConfig

    # Flag OFF (default): no queue on app.state.
    off = create_app(ServiceConfig(pack_path=Path("."), api_key="k"))
    with TestClient(off) as client:
        client.get("/healthz")
        assert not hasattr(off.state, "verify_queue")

    # Flag ON: the provider-neutral queue is created.
    on = create_app(
        ServiceConfig(pack_path=Path("."), api_key="k", verify_transport_enabled=True)
    )
    with TestClient(on) as client:
        client.get("/healthz")
        assert isinstance(on.state.verify_queue, InMemoryQueue)
