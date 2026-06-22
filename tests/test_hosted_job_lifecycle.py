"""WP-02B hosted job-lifecycle + persistence tests.

This is the heart of WP-02B: the actor-scoped, version-CAS lifecycle library
(job_lifecycle), the watchdog/reconciler sweeps, the three-phase TTL expiry + terminal
envelope deletion, the durable SQLite reference backend, and the schema's state-dependent
invariants (positive + NEGATIVE cases).

Authoritative spec: docs/operations/contracts/hosted-deployment.yaml (transitions,
execution_lease, handoff, access_matrix, transition_mutations, expiry) and
schemas/openva/hosted-job-record.schema.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service import job_lifecycle as jl  # noqa: E402
from openva_match_service.job_lifecycle import (  # noqa: E402
    Actor,
    IllegalTransition,
    InvalidErrorCode,
    InvalidLease,
    LifecycleError,
    LivePreemption,
    StaleVersion,
    UnauthorizedActor,
    api_received_to_failed,
    api_received_to_queued,
    increment_dispatch_attempt,
    reconciler_received_to_queued,
    recover_stale_leases,
    recover_undispatched,
    worker_executing_to_completed,
    worker_executing_to_failed,
    worker_heartbeat,
    worker_queued_to_executing,
    worker_received_to_queued,
    watchdog_executing_to_failed,
    watchdog_executing_to_queued,
)
from openva_match_service.sqlite_stores import (  # noqa: E402
    SqliteJobStore,
    SqliteRequestEnvelopeStore,
    SqliteResultStore,
)
from openva_match_service.verify_transport import (  # noqa: E402
    InMemoryJobStore,
    InMemoryRequestEnvelopeStore,
    InMemoryResultStore,
    InvalidRecord,
    JobRecord,
    _parse_iso_z as _vt_parse_iso_z,
    load_packaged_schema,
    new_job_id,
    new_job_token,
    new_ref,
    purge_expired_jobs,
    token_digest,
)

JOB_RECORD_SCHEMA = json.loads(
    Path("schemas/openva/hosted-job-record.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft202012Validator(
    JOB_RECORD_SCHEMA, format_checker=jsonschema.FormatChecker()
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Store fixtures (parametrized over in-memory + durable SQLite) -------------


def _in_memory_stores():
    return InMemoryJobStore(), InMemoryRequestEnvelopeStore(), InMemoryResultStore()


def _sqlite_stores(tmp_path):
    db = str(tmp_path / "wp02b.db")
    return SqliteJobStore(db), SqliteRequestEnvelopeStore(db), SqliteResultStore(db)


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    """Yield (jobs, envelopes, results) for both the in-memory and durable backends so
    the lifecycle transitions are exercised identically across both."""
    if request.param == "memory":
        return _in_memory_stores()
    return _sqlite_stores(tmp_path)


def make_received(jobs, envelopes, *, now=None, expires_in=timedelta(hours=24), rows=1):
    """Create a fresh `received` record + its envelope and return (record, token)."""
    now = now or _now()
    token = new_job_token()
    request_ref = new_ref()
    expires_at = _iso(now + expires_in)
    record = JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(token),
        state="received",
        request_ref=request_ref,
        row_count=rows,
        created_at=_iso(now),
        updated_at=_iso(now),
        expires_at=expires_at,
    )
    jobs.create(record)
    # The envelope carries the job's own expires_at so it is independently lifecycle-
    # addressable (Blocker 1): purge_expired reaps it even with no referencing record.
    envelopes.put(request_ref, {"row_count": rows, "rows": [{"vendor_name": "Acme"}]}, expires_at)
    return record, token


def _validate(record: JobRecord) -> None:
    errors = [e.message for e in VALIDATOR.iter_errors(record.to_record_dict())]
    assert errors == [], errors


# --- Schema validation: positive + NEGATIVE state-invariant cases -------------


def test_schema_negative_state_invariants_are_rejected():
    base = JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(new_job_token()),
        state="received",
        request_ref=new_ref(),
        row_count=1,
        created_at=_iso(_now()),
        updated_at=_iso(_now()),
        expires_at=_iso(_now() + timedelta(hours=24)),
    )

    def fails(record_dict) -> bool:
        return bool(list(VALIDATOR.iter_errors(record_dict)))

    # A valid received record passes.
    assert not fails(base.to_record_dict())

    # completed without result_ref must fail.
    d = base.to_record_dict()
    d.update({"state": "completed", "request_ref": None, "result_ref": None, "error_code": None})
    assert fails(d)

    # failed without error_code must fail.
    d = base.to_record_dict()
    d.update({"state": "failed", "request_ref": None, "result_ref": None, "error_code": None})
    assert fails(d)

    # terminal (completed) retaining request_ref must fail.
    d = base.to_record_dict()
    d.update({"state": "completed", "result_ref": "result/x"})  # request_ref still set
    assert fails(d)

    # non-terminal (received) without a request envelope must fail.
    d = base.to_record_dict()
    d["request_ref"] = None
    assert fails(d)

    # executing without a lease must fail.
    d = base.to_record_dict()
    d.update({"state": "executing", "lease_owner": None, "lease_expires_at": None})
    assert fails(d)

    # a lease set in a non-executing state (received) must fail.
    d = base.to_record_dict()
    d["lease_owner"] = "worker-1"
    assert fails(d)


def test_schema_version_field_is_optional_and_wp02a_records_still_validate():
    # version is OPTIONAL (not in required) so a WP-02A record (no version) validates.
    record = JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(new_job_token()),
        state="received",
        request_ref=new_ref(),
        row_count=1,
        created_at=_iso(_now()),
        updated_at=_iso(_now()),
        expires_at=_iso(_now() + timedelta(hours=24)),
    )
    d = record.to_record_dict()
    assert d["version"] == 0
    assert not list(VALIDATOR.iter_errors(d))
    # Dropping version entirely (a WP-02A-shaped record) still validates.
    del d["version"]
    assert not list(VALIDATOR.iter_errors(d))
    # A negative version is rejected (minimum 0).
    d2 = record.to_record_dict()
    d2["version"] = -1
    assert list(VALIDATOR.iter_errors(d2))


# --- Illegal transition + unauthorized actor ----------------------------------


def test_illegal_transition_queued_to_failed_rejected(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    # There is NO queued->failed edge for ANY actor.
    with pytest.raises(IllegalTransition):
        worker_executing_to_failed(
            jobs, envelopes, record.job_id, queued.version, error_code="internal_error", now=_now()
        )


def test_illegal_transition_received_to_executing_direct_rejected(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    # received -> executing is not a declared edge (the worker recovers via queued).
    with pytest.raises(IllegalTransition):
        worker_queued_to_executing(
            jobs, record.job_id, 0, lease_owner="w1", lease_expires_at=_iso(_now() + timedelta(minutes=5)), now=_now()
        )


def test_unauthorized_api_cannot_do_queued_to_executing(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    api_received_to_queued(jobs, record.job_id, 0, now=_now())
    # The API has no queued->executing authority (worker-only edge). Drive the guarded
    # mutate directly with actor=API to prove the actor gate (not the lease check) fires.
    with pytest.raises(UnauthorizedActor):
        jl._guarded_transition(
            jobs, record.job_id, actor=Actor.API, to_state="executing", expected_version=1, now=_now(),
            set_fields={"lease_owner": "w1", "lease_expires_at": _iso(_now() + timedelta(minutes=5))},
        )


def test_unauthorized_reconciler_cannot_do_executing_edges(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(_now() + timedelta(minutes=5)), now=_now(),
    )
    # The reconciler owns ONLY received->queued; executing->queued is the watchdog's.
    with pytest.raises(UnauthorizedActor):
        jl._guarded_transition(
            jobs, record.job_id, actor=Actor.RECONCILER, to_state="queued",
            expected_version=executing.version, now=_now(),
            set_fields={"lease_owner": None, "lease_expires_at": None, "attempt": executing.attempt + 1},
        )


def test_unauthorized_worker_cannot_preempt_a_live_lease_via_watchdog_edge(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(_now() + timedelta(minutes=10)), now=_now(),
    )
    # The watchdog edge on a LIVE lease is refused (LivePreemption) — the watchdog never
    # preempts; a redelivered worker task acks-and-drops.
    with pytest.raises(LivePreemption):
        watchdog_executing_to_queued(jobs, record.job_id, executing.version, now=_now())


# --- Version CAS --------------------------------------------------------------


def test_stale_version_cas_raises_and_does_not_mutate(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    # First CAS succeeds: version 0 -> 1.
    api_received_to_queued(jobs, record.job_id, 0, now=_now())
    # A second mutation with the now-stale expected_version 0 must raise and not mutate.
    with pytest.raises(StaleVersion):
        api_received_to_queued(jobs, record.job_id, 0, now=_now())
    stored = jobs.get(record.job_id)
    assert stored.version == 1
    assert stored.state == "queued"


def test_successful_cas_increments_version(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    assert jobs.get(record.job_id).version == 0
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    assert queued.version == 1
    assert jobs.get(record.job_id).version == 1


# --- Lease: acquire, live not preempted, heartbeat owner-only -----------------


def test_queued_to_executing_takes_a_lease_and_validates(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    deadline = _iso(_now() + timedelta(minutes=5))
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="worker-1", lease_expires_at=deadline, now=_now()
    )
    assert executing.state == "executing"
    assert executing.lease_owner == "worker-1"
    assert executing.lease_expires_at == deadline
    assert executing.request_ref is not None  # preserved
    _validate(executing)


def test_live_lease_duplicate_delivery_is_not_preempted(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="worker-1",
        lease_expires_at=_iso(_now() + timedelta(minutes=10)), now=_now(),
    )
    # A duplicate delivery tries to win the same job: already executing with a LIVE lease
    # -> LivePreemption (caller acks-and-drops).
    with pytest.raises(LivePreemption):
        worker_queued_to_executing(
            jobs, record.job_id, queued.version + 1, lease_owner="worker-2",
            lease_expires_at=_iso(_now() + timedelta(minutes=10)), now=_now(),
        )


def test_expired_lease_redelivery_defers_to_watchdog_not_preempt(stores):
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    # Acquire a lease that is LIVE at acquisition (the acquisition guard requires a strictly
    # future deadline), then evaluate the redelivery at a LATER `now` where it has gone stale.
    worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="worker-1",
        lease_expires_at=_iso(now + timedelta(minutes=1)), now=now,
    )
    later = now + timedelta(minutes=2)  # the worker-1 lease is now expired
    # A redelivery whose record is executing with an EXPIRED lease must NOT preempt; it
    # defers to the watchdog (still LivePreemption from the worker's perspective).
    with pytest.raises(LivePreemption):
        worker_queued_to_executing(
            jobs, record.job_id, queued.version + 1, lease_owner="worker-2",
            lease_expires_at=_iso(later + timedelta(minutes=5)), now=later,
        )


def test_heartbeat_extends_only_for_the_owner(stores):
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="worker-1",
        lease_expires_at=_iso(now + timedelta(minutes=1)), now=now,
    )
    # The owner extends the lease (version still CAS-bumped, state unchanged).
    new_deadline = _iso(now + timedelta(minutes=10))
    extended = worker_heartbeat(
        jobs, record.job_id, executing.version, lease_owner="worker-1",
        new_lease_expires_at=new_deadline, now=now,
    )
    assert extended.state == "executing"
    assert extended.lease_expires_at == new_deadline
    assert extended.version == executing.version + 1
    # A non-owner heartbeat is refused.
    with pytest.raises(UnauthorizedActor):
        worker_heartbeat(
            jobs, record.job_id, extended.version, lease_owner="worker-2",
            new_lease_expires_at=_iso(now + timedelta(minutes=20)), now=now,
        )


def test_heartbeat_only_valid_while_executing(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    # A queued (not executing) job cannot be heartbeat.
    with pytest.raises(UnauthorizedActor):
        worker_heartbeat(
            jobs, record.job_id, queued.version, lease_owner="worker-1",
            new_lease_expires_at=_iso(_now() + timedelta(minutes=5)), now=_now(),
        )


# --- Terminal transitions delete the request envelope -------------------------


def test_executing_to_completed_deletes_envelope_and_validates(stores):
    jobs, envelopes, results = stores
    record, _ = make_received(jobs, envelopes)
    request_ref = record.request_ref
    assert envelopes.get(request_ref) is not None
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(_now() + timedelta(minutes=5)), now=_now(),
    )
    # Terminalization order: write result blob first, then CAS, then envelope delete.
    result_ref = new_ref()
    results.put(result_ref, {"rows": [{"status": "ok"}]}, _iso(_now() + timedelta(hours=24)))
    completed = worker_executing_to_completed(
        jobs, envelopes, record.job_id, executing.version, result_ref=result_ref, now=_now()
    )
    assert completed.state == "completed"
    assert completed.result_ref == result_ref
    assert completed.request_ref is None
    assert completed.lease_owner is None
    # The envelope is physically deleted on the terminal transition.
    assert envelopes.get(request_ref) is None
    _validate(completed)


def test_executing_to_failed_deletes_envelope_and_validates(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    request_ref = record.request_ref
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(_now() + timedelta(minutes=5)), now=_now(),
    )
    failed = worker_executing_to_failed(
        jobs, envelopes, record.job_id, executing.version, error_code="upstream_unavailable", now=_now()
    )
    assert failed.state == "failed"
    assert failed.error_code == "upstream_unavailable"
    assert failed.request_ref is None
    assert envelopes.get(request_ref) is None
    _validate(failed)


def test_api_received_to_failed_deletes_envelope(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    request_ref = record.request_ref
    failed = api_received_to_failed(
        jobs, envelopes, record.job_id, 0, error_code="internal_error", now=_now()
    )
    assert failed.state == "failed"
    assert failed.error_code == "internal_error"
    assert envelopes.get(request_ref) is None
    _validate(failed)


# --- Worker recovery edge (received->queued by worker) -------------------------


def test_worker_received_to_queued_recovery(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    # API crashed before its CAS; the worker recovers received -> queued.
    queued = worker_received_to_queued(jobs, record.job_id, 0, now=_now())
    assert queued.state == "queued"
    assert queued.request_ref is not None  # preserved
    _validate(queued)


# --- Watchdog: stale lease -> queued (attempt+1) / -> failed at bound ----------


def test_watchdog_requeues_stale_lease_with_attempt_increment(stores):
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    # Acquire a live lease, then run the watchdog at a later `now` where it has gone stale
    # (acquisition requires a strictly-future deadline; staleness is a function of elapsed time).
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(seconds=1)), now=now,
    )
    assert executing.attempt == 0
    later = now + timedelta(seconds=2)  # the lease is now stale
    requeued = watchdog_executing_to_queued(jobs, record.job_id, executing.version, now=later)
    assert requeued.state == "queued"
    assert requeued.attempt == 1
    assert requeued.lease_owner is None
    assert requeued.request_ref is not None  # preserved for retry
    _validate(requeued)


def test_watchdog_terminalizes_at_attempt_max(stores):
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    request_ref = record.request_ref
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(seconds=1)), now=now,
    )
    later = now + timedelta(seconds=2)  # the lease is now stale
    failed = watchdog_executing_to_failed(jobs, envelopes, record.job_id, executing.version, now=later)
    assert failed.state == "failed"
    assert failed.error_code == "execution_timeout"
    assert envelopes.get(request_ref) is None
    _validate(failed)


def test_watchdog_never_touches_a_live_lease(stores):
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(minutes=10)), now=now,  # LIVE
    )
    with pytest.raises(LivePreemption):
        watchdog_executing_to_queued(jobs, record.job_id, executing.version, now=now)
    with pytest.raises(LivePreemption):
        watchdog_executing_to_failed(jobs, envelopes, record.job_id, executing.version, now=now)


def test_recover_stale_leases_sweep(stores):
    jobs, envelopes, _results = stores
    now = _now()
    # All leases are acquired LIVE (acquisition requires a strictly-future deadline) and the
    # sweep runs at `later`, by which point A's and B's short leases have gone stale while
    # C's long lease is still live. `later` stays well inside every job's expires_at (24h),
    # so the sweep's job-expiry skip (Blocker 3) does not apply here.
    short = _iso(now + timedelta(seconds=1))
    # job A: stale lease, attempt < max -> re-queued (attempt+1)
    a, _ = make_received(jobs, envelopes, now=now)
    qa = api_received_to_queued(jobs, a.job_id, 0, now=now)
    worker_queued_to_executing(
        jobs, a.job_id, qa.version, lease_owner="w1", lease_expires_at=short, now=now
    )
    # job B: stale lease, attempt already at max -> failed(execution_timeout)
    b, _ = make_received(jobs, envelopes, now=now)
    qb = api_received_to_queued(jobs, b.job_id, 0, now=now)
    eb = worker_queued_to_executing(
        jobs, b.job_id, qb.version, lease_owner="w1", lease_expires_at=short, now=now
    )
    # Drive attempt up to the max: a watchdog requeue (at a later instant so the lease is
    # stale) then re-execute once so attempt==1, and use attempt_max=1.
    requeue_at = now + timedelta(seconds=2)
    rb = watchdog_executing_to_queued(jobs, b.job_id, eb.version, now=requeue_at)  # attempt -> 1
    web = worker_queued_to_executing(
        jobs, b.job_id, rb.version, lease_owner="w1",
        lease_expires_at=_iso(requeue_at + timedelta(seconds=1)), now=requeue_at,
    )
    assert web.attempt == 1
    # job C: LIVE lease (still live at the sweep instant) -> untouched
    c, _ = make_received(jobs, envelopes, now=now)
    qc = api_received_to_queued(jobs, c.job_id, 0, now=now)
    worker_queued_to_executing(
        jobs, c.job_id, qc.version, lease_owner="w1", lease_expires_at=_iso(now + timedelta(minutes=10)), now=now
    )

    later = now + timedelta(seconds=5)  # A and B leases stale; C still live
    b_ref = jobs.get(b.job_id).request_ref  # capture before terminalization nulls it
    acted = recover_stale_leases(jobs, envelopes, later, attempt_max=1)
    assert set(acted) == {a.job_id, b.job_id}
    assert jobs.get(a.job_id).state == "queued" and jobs.get(a.job_id).attempt == 1
    assert jobs.get(b.job_id).state == "failed" and jobs.get(b.job_id).error_code == "execution_timeout"
    # Terminalization physically deletes the request envelope (deleted_on: failure).
    assert b_ref is not None and envelopes.get(b_ref) is None
    assert jobs.get(c.job_id).state == "executing"  # live lease untouched


# --- Reconciler: stuck received -> queued (dispatch_attempt+1), bounded --------


def test_reconciler_recovers_stuck_received_with_dispatch_increment(stores):
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))
    # Increment dispatch_attempt while STILL received, then re-dispatch.
    bumped = increment_dispatch_attempt(jobs, record.job_id, 0, now=now)
    assert bumped.state == "received"
    assert bumped.dispatch_attempt == 1
    assert bumped.attempt == 0  # execution counter pinned to 0 while received
    queued = reconciler_received_to_queued(jobs, record.job_id, bumped.version, now=now)
    assert queued.state == "queued"
    assert queued.dispatch_attempt == 1
    _validate(queued)


def test_increment_dispatch_attempt_rejected_when_not_received(stores):
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=_now())
    with pytest.raises(UnauthorizedActor):
        increment_dispatch_attempt(jobs, record.job_id, queued.version, now=_now())


def test_recover_undispatched_sweep_is_bounded(stores):
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=1)
    # An OLD received job (older than grace) is recovered.
    old, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))
    # A FRESH received job (within grace) is NOT yet recovered.
    fresh, _ = make_received(jobs, envelopes, now=now)
    # An EXHAUSTED job at dispatch_max is left untouched (terminates by expiry).
    exhausted, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))
    exhausted_record = jobs.get(exhausted.job_id)
    # Bump its dispatch_attempt to the max directly via repeated CAS.
    v = exhausted_record.version
    for _ in range(2):
        bumped = increment_dispatch_attempt(jobs, exhausted.job_id, v, now=now)
        v = bumped.version
    assert jobs.get(exhausted.job_id).dispatch_attempt == 2

    # Injected enqueue succeeds (records the recovery generation it was called with).
    enqueue_calls: list[tuple[str, int]] = []

    def enqueue(job_id, dispatch_attempt):
        enqueue_calls.append((job_id, dispatch_attempt))
        return True

    acted = recover_undispatched(jobs, now, dispatch_max=2, grace=grace, enqueue=enqueue)
    assert acted == [old.job_id]
    assert jobs.get(old.job_id).state == "queued"
    assert jobs.get(old.job_id).dispatch_attempt == 1
    assert jobs.get(fresh.job_id).state == "received"  # still within grace
    assert jobs.get(exhausted.job_id).state == "received"  # exhausted, not re-dispatched
    # Only the eligible job was enqueued, named with its fresh recovery generation (r1).
    assert enqueue_calls == [(old.job_id, 1)]


# --- Three-phase TTL expiry + terminal deletion -------------------------------


def test_three_phase_expiry_pre_expiry_retained_then_physical(stores):
    jobs, envelopes, results = stores
    now = _now()
    retained_window = timedelta(hours=1)

    # (a) pre-expiry: untouched by the purge.
    live, _ = make_received(jobs, envelopes, now=now, expires_in=timedelta(hours=24))
    import dataclasses

    # (b) expired-but-retained: envelope deleted at TTL (minimisation), record retained.
    retained, _ = make_received(jobs, envelopes, now=now - timedelta(hours=2))
    # set its expiry to 5 min ago (within the retained window)
    rr = jobs.get(retained.job_id)
    jobs.cas_update(
        dataclasses.replace(rr, expires_at=_iso(now - timedelta(minutes=5)), version=rr.version + 1),
        rr.version,
    )
    retained_ref = retained.request_ref
    # (c) past retained window: a COMPLETED job (carries a result_ref; its envelope was
    # already deleted on the terminal transition) is physically deleted (record + result
    # gone). Build it through the lifecycle, then age its expires_at past the window.
    deleted, _ = make_received(jobs, envelopes, now=now - timedelta(hours=5))
    deleted_ref = deleted.request_ref
    dq = api_received_to_queued(jobs, deleted.job_id, 0, now=now - timedelta(hours=5))
    de = worker_queued_to_executing(
        jobs, deleted.job_id, dq.version, lease_owner="w1",
        lease_expires_at=_iso(now - timedelta(hours=4)), now=now - timedelta(hours=5),
    )
    deleted_result_ref = new_ref()
    results.put(deleted_result_ref, {"rows": []}, _iso(now - timedelta(hours=2)))
    dc = worker_executing_to_completed(
        jobs, envelopes, deleted.job_id, de.version, result_ref=deleted_result_ref, now=now - timedelta(hours=5)
    )
    # Envelope already gone (terminal deletion); now age expires_at past the window.
    jobs.cas_update(
        dataclasses.replace(dc, expires_at=_iso(now - timedelta(hours=2)), version=dc.version + 1),
        dc.version,
    )

    purged = purge_expired_jobs(jobs, envelopes, results, now, retained_window)

    # pre-expiry: still fully present.
    assert jobs.get(live.job_id) is not None
    assert envelopes.get(live.request_ref) is not None
    # expired-but-retained: record present, but ENVELOPE deleted at TTL (minimisation).
    assert jobs.get(retained.job_id) is not None
    assert envelopes.get(retained_ref) is None
    # past retained window: record physically gone, envelope + result gone.
    assert deleted.job_id in purged
    assert jobs.get(deleted.job_id) is None
    assert envelopes.get(deleted_ref) is None
    assert results.get(deleted_result_ref) is None


# --- New-job-per-request: no dedup --------------------------------------------


def test_new_job_per_request_no_dedup(stores):
    jobs, envelopes, _results = stores
    now = _now()
    a, ta = make_received(jobs, envelopes, now=now)
    b, tb = make_received(jobs, envelopes, now=now)
    # Two identical requests yield distinct job_ids, request_refs, and tokens.
    assert a.job_id != b.job_id
    assert a.request_ref != b.request_ref
    assert ta != tb
    assert jobs.get(a.job_id) is not None and jobs.get(b.job_id) is not None


# --- SQLite provider: round-trip + version-CAS + durability -------------------


def test_sqlite_round_trips_record_envelope_result(tmp_path):
    jobs, envelopes, results = _sqlite_stores(tmp_path)
    record, token = make_received(jobs, envelopes)
    fetched = jobs.get(record.job_id)
    assert fetched is not None
    assert fetched.job_id == record.job_id
    assert fetched.job_token_digest == token_digest(token)
    assert fetched.version == 0
    assert envelopes.get(record.request_ref)["rows"][0]["vendor_name"] == "Acme"
    results.put("result/1", {"ok": True}, _iso(_now() + timedelta(hours=24)))
    assert results.get("result/1") == {"ok": True}
    # Round-trips through to_record_dict + schema.
    _validate(fetched)


def test_sqlite_version_cas_rejects_stale_update(tmp_path):
    import dataclasses

    jobs, envelopes, _results = _sqlite_stores(tmp_path)
    record, _ = make_received(jobs, envelopes)
    # A CAS at the correct version wins; the same (now stale) expected_version then loses.
    # Both target records are schema-VALID (queued preserves request_ref, no lease) so the
    # CAS-version check — not the persistence validation — is what decides win vs lose.
    won = jobs.cas_update(dataclasses.replace(record, state="queued", version=1), 0)
    assert won is True
    lost = jobs.cas_update(
        dataclasses.replace(record, state="queued", row_count=2, version=1), 0
    )
    assert lost is False
    assert jobs.get(record.job_id).state == "queued"
    assert jobs.get(record.job_id).row_count == record.row_count  # losing write did not land


def test_sqlite_durable_across_reopen(tmp_path):
    db = str(tmp_path / "persist.db")
    jobs = SqliteJobStore(db)
    envelopes = SqliteRequestEnvelopeStore(db)
    record, _ = make_received(jobs, envelopes)
    job_id = record.job_id
    jobs.close()
    envelopes.close()
    # Re-open a fresh connection to the SAME file: the record + envelope survive.
    jobs2 = SqliteJobStore(db)
    envelopes2 = SqliteRequestEnvelopeStore(db)
    assert jobs2.get(job_id) is not None
    assert envelopes2.get(record.request_ref) is not None


def test_sqlite_full_lifecycle_matches_in_memory(tmp_path):
    # The SQLite backend behaves identically through a full happy-path lifecycle.
    jobs, envelopes, results = _sqlite_stores(tmp_path)
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(minutes=5)), now=now,
    )
    result_ref = new_ref()
    results.put(result_ref, {"rows": [{"status": "ok"}]}, _iso(now + timedelta(hours=24)))
    completed = worker_executing_to_completed(
        jobs, envelopes, record.job_id, executing.version, result_ref=result_ref, now=now
    )
    assert completed.state == "completed"
    assert completed.version == 3  # 0 received -> queued -> executing -> completed
    assert envelopes.get(record.request_ref) is None
    _validate(completed)


# --- Minimisation: identities never in the record or sweeps' record output -----


def test_identities_never_appear_in_the_job_record(stores):
    jobs, envelopes, _results = stores
    # The envelope MAY carry identities (the worker reads them); the RECORD must not.
    record, _ = make_received(jobs, envelopes)
    record_dict = jobs.get(record.job_id).to_record_dict()
    serialized = json.dumps(record_dict)
    assert "Acme" not in serialized
    assert "vendor_name" not in serialized
    # The envelope is where identities live (WP-02B durable persistence).
    assert envelopes.get(record.request_ref)["rows"][0]["vendor_name"] == "Acme"


# --- LifecycleError hierarchy --------------------------------------------------


def test_lifecycle_error_hierarchy():
    for exc in (
        IllegalTransition,
        UnauthorizedActor,
        StaleVersion,
        LivePreemption,
        InvalidLease,
        InvalidErrorCode,
    ):
        assert issubclass(exc, LifecycleError)


# =============================================================================
# Blocker remediation tests (PR #410 protocol-correctness)
# =============================================================================

import dataclasses  # noqa: E402
import threading  # noqa: E402


# --- Blocker 1: independent orphan blob cleanup (envelope + result) ------------


def test_orphan_envelope_with_no_job_record_is_reaped(stores):
    """(a) An envelope written but whose job record was never created (the
    after-envelope-before-job crash point) is reaped by its OWN expires_at via
    purge_expired — independent of any record."""
    jobs, envelopes, results = stores
    now = _now()
    orphan_ref = new_ref()
    envelopes.put(orphan_ref, {"row_count": 1}, _iso(now - timedelta(minutes=1)))  # already expired
    assert envelopes.get(orphan_ref) is not None
    # No job record references this envelope at all.
    assert jobs.iter_records() == []
    reaped = envelopes.purge_expired(now)
    assert orphan_ref in reaped
    assert envelopes.get(orphan_ref) is None
    # A not-yet-expired orphan survives the same sweep.
    live_ref = new_ref()
    envelopes.put(live_ref, {"row_count": 1}, _iso(now + timedelta(hours=1)))
    assert envelopes.purge_expired(now) == []
    assert envelopes.get(live_ref) is not None


def test_orphan_result_with_no_referencing_record_is_reaped(stores):
    """(b) A result blob written before any terminal record references it is reaped by its
    own expires_at, independent of a record."""
    jobs, envelopes, results = stores
    now = _now()
    orphan_result = new_ref()
    results.put(orphan_result, {"rows": []}, _iso(now - timedelta(minutes=1)))
    assert results.get(orphan_result) is not None
    reaped = results.purge_expired(now)
    assert orphan_result in reaped
    assert results.get(orphan_result) is None


def test_terminal_record_skipped_envelope_delete_orphan_still_reaped(stores):
    """(c) A record is terminalized (request_ref cleared) but the physical envelope delete
    was SKIPPED (worker crashed between the CAS and the delete). The orphan envelope has no
    in-record pointer, yet purge_expired_jobs' orphan sweep still reaps it by its own
    expires_at."""
    jobs, envelopes, results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    skipped_ref = record.request_ref
    # Re-seed the envelope's expiry to the job's expiry so it is past-TTL at `now+later`.
    envelopes.put(skipped_ref, {"row_count": 1}, _iso(now - timedelta(minutes=1)))
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(minutes=5)), now=now,
    )
    result_ref = new_ref()
    results.put(result_ref, {"rows": []}, _iso(now + timedelta(hours=24)))
    # Terminalize via a CAS that clears request_ref but DO NOT delete the physical envelope
    # (simulate the skipped/ failed delete). We CAS directly to a valid completed record.
    completed = dataclasses.replace(
        executing,
        state="completed",
        request_ref=None,
        result_ref=result_ref,
        lease_owner=None,
        lease_expires_at=None,
        error_code=None,
        version=executing.version + 1,
    )
    assert jobs.cas_update(completed, executing.version) is True
    # The record no longer points at the envelope, yet the physical blob is still present.
    assert jobs.get(record.job_id).request_ref is None
    assert envelopes.get(skipped_ref) is not None
    # The orphan sweep inside purge_expired_jobs reaps it by its OWN expires_at.
    purge_expired_jobs(jobs, envelopes, results, now, timedelta(hours=1))
    assert envelopes.get(skipped_ref) is None


# --- Blocker 2: reconciler two-phase dispatch (no queued without an enqueue) ----


def test_recover_undispatched_enqueue_success_moves_to_queued(stores):
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=1)
    job, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))
    calls: list[tuple[str, int]] = []

    def enqueue(job_id, dispatch_attempt):
        calls.append((job_id, dispatch_attempt))
        return True

    acted = recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue)
    assert acted == [job.job_id]
    stored = jobs.get(job.job_id)
    assert stored.state == "queued"
    assert stored.dispatch_attempt == 1  # bumped before the enqueue
    assert calls == [(job.job_id, 1)]


def test_recover_undispatched_enqueue_failure_stays_received(stores):
    """A False return from enqueue must leave the record `received` (recoverable) with the
    dispatch_attempt bumped — NEVER queued."""
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=1)
    job, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))

    def enqueue(job_id, dispatch_attempt):
        return False  # enqueue failed

    acted = recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue)
    assert acted == []
    stored = jobs.get(job.job_id)
    assert stored.state == "received"  # NOT queued
    assert stored.dispatch_attempt == 1  # the generation bump persists for the next sweep


def test_recover_undispatched_enqueue_raising_stays_received(stores):
    """A RAISING enqueue is also a failure: the record stays `received`, never queued."""
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=1)
    job, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))

    def enqueue(job_id, dispatch_attempt):
        raise RuntimeError("queue unavailable")

    acted = recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue)
    assert acted == []
    stored = jobs.get(job.job_id)
    assert stored.state == "received"
    assert stored.dispatch_attempt == 1


def test_recover_undispatched_enqueue_never_called_when_exhausted(stores):
    """A job at dispatch_max is not enqueued and is not moved to queued."""
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=1)
    job, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))
    v = jobs.get(job.job_id).version
    for _ in range(2):
        bumped = increment_dispatch_attempt(jobs, job.job_id, v, now=now)
        v = bumped.version
    calls: list[tuple[str, int]] = []

    def enqueue(job_id, dispatch_attempt):
        calls.append((job_id, dispatch_attempt))
        return True

    acted = recover_undispatched(jobs, now, dispatch_max=2, grace=grace, enqueue=enqueue)
    assert acted == []
    assert calls == []  # exhausted -> enqueue never attempted
    assert jobs.get(job.job_id).state == "received"


def test_recover_undispatched_concurrent_reconcilers_one_wins(stores):
    """Two reconcilers sweeping the same stuck job: exactly one wins a generation; the loser
    sees StaleVersion on the dispatch_attempt CAS and is skipped (no enqueue, no flip)."""
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=1)
    job, _ = make_received(jobs, envelopes, now=now - timedelta(minutes=10))

    def enqueue(job_id, dispatch_attempt):
        return True

    # Both reconcilers enumerate the SAME version-0 snapshot, then race the CAS. Run them
    # sequentially against the shared store: the first wins (received->queued), the second
    # finds the job no longer `received` (or version-advanced) and acts on nothing.
    acted_a = recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue)
    acted_b = recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue)
    assert acted_a == [job.job_id]
    assert acted_b == []  # the job already left `received`
    assert jobs.get(job.job_id).state == "queued"
    assert jobs.get(job.job_id).dispatch_attempt == 1  # exactly one generation bump


# --- Blocker 3: lease + job-expiry guards --------------------------------------


def test_acquire_lease_rejects_non_future_deadline(stores):
    jobs, envelopes, _results = stores
    now = _now()
    # Expired deadline.
    a, _ = make_received(jobs, envelopes, now=now)
    qa = api_received_to_queued(jobs, a.job_id, 0, now=now)
    with pytest.raises(InvalidLease):
        worker_queued_to_executing(
            jobs, a.job_id, qa.version, lease_owner="w1",
            lease_expires_at=_iso(now - timedelta(seconds=1)), now=now,
        )
    # Exactly now (not STRICTLY future) is rejected.
    with pytest.raises(InvalidLease):
        worker_queued_to_executing(
            jobs, a.job_id, qa.version, lease_owner="w1",
            lease_expires_at=_iso(now), now=now,
        )
    # Malformed deadline is rejected.
    with pytest.raises(InvalidLease):
        worker_queued_to_executing(
            jobs, a.job_id, qa.version, lease_owner="w1",
            lease_expires_at="not-a-timestamp", now=now,
        )
    # The job is still queued (no partial acquisition landed).
    assert jobs.get(a.job_id).state == "queued"


def test_heartbeat_rejects_expired_lease(stores):
    """An already-expired lease cannot be revived by a heartbeat."""
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(seconds=1)), now=now,
    )
    later = now + timedelta(seconds=2)  # the lease is now expired
    with pytest.raises(InvalidLease):
        worker_heartbeat(
            jobs, record.job_id, executing.version, lease_owner="w1",
            new_lease_expires_at=_iso(later + timedelta(minutes=5)), now=later,
        )


def test_heartbeat_rejects_non_advancing_deadline(stores):
    """A heartbeat must push the deadline strictly forward past both now and the existing
    deadline: an earlier/equal/past-dated new deadline is rejected."""
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    existing_deadline = now + timedelta(minutes=5)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(existing_deadline), now=now,
    )
    # Equal to the existing deadline -> rejected (no extension).
    with pytest.raises(InvalidLease):
        worker_heartbeat(
            jobs, record.job_id, executing.version, lease_owner="w1",
            new_lease_expires_at=_iso(existing_deadline), now=now,
        )
    # Earlier than the existing deadline (shortening) -> rejected.
    with pytest.raises(InvalidLease):
        worker_heartbeat(
            jobs, record.job_id, executing.version, lease_owner="w1",
            new_lease_expires_at=_iso(existing_deadline - timedelta(minutes=1)), now=now,
        )
    # In the past relative to now -> rejected.
    with pytest.raises(InvalidLease):
        worker_heartbeat(
            jobs, record.job_id, executing.version, lease_owner="w1",
            new_lease_expires_at=_iso(now - timedelta(minutes=1)), now=now,
        )
    # Malformed -> rejected.
    with pytest.raises(InvalidLease):
        worker_heartbeat(
            jobs, record.job_id, executing.version, lease_owner="w1",
            new_lease_expires_at="garbage", now=now,
        )


def test_heartbeat_owner_strictly_later_deadline_ok(stores):
    """The owner heartbeating a LIVE lease with a strictly-later deadline succeeds."""
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(minutes=1)), now=now,
    )
    new_deadline = _iso(now + timedelta(minutes=10))
    extended = worker_heartbeat(
        jobs, record.job_id, executing.version, lease_owner="w1",
        new_lease_expires_at=new_deadline, now=now,
    )
    assert extended.lease_expires_at == new_deadline
    assert extended.version == executing.version + 1
    _validate(extended)


def test_recovery_sweeps_skip_jobs_past_expires_at(stores):
    """A record past its own expires_at is skipped by BOTH recovery sweeps — recovery must
    not resurrect an expired job; time-based expiry/purge owns it."""
    jobs, envelopes, _results = stores
    now = _now()
    # An executing job with a stale lease BUT past its expires_at: the stale-lease sweep
    # skips it.
    stale_expired, _ = make_received(jobs, envelopes, now=now - timedelta(hours=2), expires_in=timedelta(hours=1))
    qse = api_received_to_queued(jobs, stale_expired.job_id, 0, now=now - timedelta(hours=2))
    worker_queued_to_executing(
        jobs, stale_expired.job_id, qse.version, lease_owner="w1",
        lease_expires_at=_iso(now - timedelta(minutes=30)), now=now - timedelta(hours=2),
    )
    # now (the sweep instant) is past expires_at (= created + 1h).
    assert now >= _parse_iso(jobs.get(stale_expired.job_id).expires_at)
    acted_leases = recover_stale_leases(jobs, envelopes, now, attempt_max=5)
    assert stale_expired.job_id not in acted_leases
    assert jobs.get(stale_expired.job_id).state == "executing"  # untouched

    # A received job older than grace BUT past its expires_at: the dispatch sweep skips it.
    recv_expired, _ = make_received(
        jobs, envelopes, now=now - timedelta(hours=2), expires_in=timedelta(hours=1)
    )
    enqueue_calls: list[str] = []

    def enqueue(job_id, dispatch_attempt):
        enqueue_calls.append(job_id)
        return True

    acted_dispatch = recover_undispatched(
        jobs, now, dispatch_max=10, grace=timedelta(minutes=1), enqueue=enqueue
    )
    assert recv_expired.job_id not in acted_dispatch
    assert recv_expired.job_id not in enqueue_calls  # enqueue not even attempted
    assert jobs.get(recv_expired.job_id).state == "received"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- Blocker 4: schema-enforced persistence boundary (faithful, not projected) -


def _valid_received(now=None) -> JobRecord:
    now = now or _now()
    return JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(new_job_token()),
        state="received",
        request_ref=new_ref(),
        row_count=1,
        created_at=_iso(now),
        updated_at=_iso(now),
        expires_at=_iso(now + timedelta(hours=24)),
    )


def test_create_rejects_terminal_record_still_carrying_request_ref(stores):
    """A completed record that still carries a RAW request_ref violates the schema's
    terminal invariant and is rejected at persistence (the faithful serializer is validated,
    not the state-normalised projection)."""
    jobs, _envelopes, _results = stores
    bad = dataclasses.replace(
        _valid_received(), state="completed", result_ref=new_ref()
    )  # request_ref still set (raw)
    assert bad.request_ref is not None
    with pytest.raises(InvalidRecord):
        jobs.create(bad)


def test_create_rejects_received_record_with_a_raw_lease(stores):
    """A received record carrying a raw lease is rejected at persistence."""
    jobs, _envelopes, _results = stores
    bad = dataclasses.replace(
        _valid_received(), lease_owner="w1", lease_expires_at=_iso(_now() + timedelta(minutes=5))
    )
    with pytest.raises(InvalidRecord):
        jobs.create(bad)


def test_create_rejects_arbitrary_error_code(stores):
    """An error_code outside the schema enum is rejected at persistence."""
    jobs, _envelopes, _results = stores
    bad = dataclasses.replace(
        _valid_received(),
        state="failed",
        request_ref=None,
        result_ref=None,
        error_code="teapot",  # not in the enum
    )
    with pytest.raises(InvalidRecord):
        jobs.create(bad)


def test_create_rejects_malformed_timestamp(stores):
    """A malformed date-time field is rejected at persistence."""
    jobs, _envelopes, _results = stores
    bad = dataclasses.replace(_valid_received(), created_at="not-a-date")
    with pytest.raises(InvalidRecord):
        jobs.create(bad)


def test_cas_update_rejects_invalid_record(stores):
    """cas_update applies the SAME persistence validation as create: a CAS that would write
    a schema-invalid record (terminal w/ request_ref) is rejected, not silently normalised."""
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    bad = dataclasses.replace(
        record, state="completed", result_ref=new_ref(), version=record.version + 1
    )  # request_ref still set
    with pytest.raises(InvalidRecord):
        jobs.cas_update(bad, record.version)
    # The stored record is unchanged (still the valid received record).
    assert jobs.get(record.job_id).state == "received"


def test_transition_helpers_reject_error_code_outside_enum(stores):
    """Defence in depth: the transition helpers reject a bad error_code at the boundary
    (InvalidErrorCode) before any persistence."""
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    with pytest.raises(InvalidErrorCode):
        api_received_to_failed(
            jobs, envelopes, record.job_id, 0, error_code="teapot", now=_now()
        )
    # The job is untouched.
    assert jobs.get(record.job_id).state == "received"


def test_valid_transition_still_round_trips(stores):
    """A valid lifecycle transition still persists and round-trips (the validation is a
    backstop, not a regression to the happy path)."""
    jobs, envelopes, results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(minutes=5)), now=now,
    )
    result_ref = new_ref()
    results.put(result_ref, {"rows": [{"status": "ok"}]}, _iso(now + timedelta(hours=24)))
    completed = worker_executing_to_completed(
        jobs, envelopes, record.job_id, executing.version, result_ref=result_ref, now=now
    )
    assert completed.state == "completed"
    _validate(completed)
    assert jobs.get(record.job_id).state == "completed"


# --- Blocker 5: atomic in-memory CAS (thread safety) ---------------------------


def test_in_memory_cas_exactly_one_concurrent_winner():
    """Two threads doing cas_update at the SAME expected_version concurrently: EXACTLY ONE
    returns True, the other False (the read-check-write is guarded by a lock)."""
    jobs = InMemoryJobStore()
    envelopes = InMemoryRequestEnvelopeStore()
    record, _ = make_received(jobs, envelopes)
    base = jobs.get(record.job_id)
    assert base.version == 0

    barrier = threading.Barrier(2)
    results_map: dict[str, bool] = {}

    def attempt(name, row_count):
        candidate = dataclasses.replace(base, row_count=row_count, version=1)
        barrier.wait()  # maximise the race on the read-check-write
        results_map[name] = jobs.cas_update(candidate, 0)

    threads = [
        threading.Thread(target=attempt, args=("a", 5)),
        threading.Thread(target=attempt, args=("b", 9)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results_map.values()) == [False, True]  # exactly one winner
    assert jobs.get(record.job_id).version == 1


def test_sqlite_cas_exactly_one_winner_two_connections(tmp_path):
    """The SQLite equivalent: TWO independent SqliteJobStore connections against the SAME
    db file race a CAS at the same expected_version; exactly one wins (WHERE version=? +
    rowcount)."""
    db = str(tmp_path / "cas_race.db")
    writer = SqliteJobStore(db)
    envelopes = SqliteRequestEnvelopeStore(db)
    record, _ = make_received(writer, envelopes)
    base = writer.get(record.job_id)
    assert base.version == 0

    # Two independent connections to the SAME file.
    conn_a = SqliteJobStore(db)
    conn_b = SqliteJobStore(db)
    won_a = conn_a.cas_update(dataclasses.replace(base, row_count=5, version=1), 0)
    won_b = conn_b.cas_update(dataclasses.replace(base, row_count=9, version=1), 0)
    assert sorted([won_a, won_b]) == [False, True]  # exactly one CAS landed
    assert writer.get(record.job_id).version == 1


# =============================================================================
# PR #410 round-2 blocker remediation tests (protocol-critical)
# =============================================================================

import importlib.resources  # noqa: E402


# --- Blocker 1: packaged schema (drift-lock + importlib.resources isolation) ----


def test_packaged_schema_is_drift_locked_to_canonical():
    """The schema shipped AS SERVICE PACKAGE DATA must be json-equal to the canonical
    schemas/openva/hosted-job-record.schema.json. A drift between the two would let the
    packaged service validate records against a different contract than the repo's source of
    truth — so this lock fails the moment they diverge."""
    canonical = json.loads(
        Path("schemas/openva/hosted-job-record.schema.json").read_text(encoding="utf-8")
    )
    packaged = load_packaged_schema()
    assert packaged == canonical
    # Byte-identical too (the copy is a verbatim copy, not a re-serialization), so a
    # whitespace/ordering drift is also caught.
    canonical_bytes = Path(
        "schemas/openva/hosted-job-record.schema.json"
    ).read_bytes()
    packaged_bytes = (
        importlib.resources.files("openva_match_service")
        .joinpath("schemas/hosted-job-record.schema.json")
        .read_bytes()
    )
    assert packaged_bytes == canonical_bytes


def test_persistence_validation_loads_schema_without_repo_tree(monkeypatch, tmp_path):
    """Package-isolation proof: the persistence validation loads its schema via
    importlib.resources from the INSTALLED package, NOT a repository-root ``schemas/`` tree.

    We run from a clean cwd with no ``schemas/`` directory on disk and clear the cached
    validator, then exercise InMemoryJobStore.create(valid_record). If the loader still
    depended on a ``parents[N]`` repo path it would raise FileNotFoundError here; instead it
    resolves the packaged copy and the create succeeds. This is the in-repo stand-in for the
    clean-wheel/Docker build (a CI-infra concern)."""
    import openva_match_service.verify_transport as vt

    # Prove the loader itself works with no repository schemas/ tree reachable from cwd.
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "schemas").exists()
    # Drop the cached validator so it is rebuilt via the importlib.resources loader now.
    vt._record_validator.cache_clear()

    schema = vt.load_packaged_schema()
    assert schema["title"] == "OpenVA Hosted Job Record"

    jobs = InMemoryJobStore()
    record = _valid_received()
    jobs.create(record)  # exercises validate_record_for_persistence -> packaged schema
    assert jobs.get(record.job_id) is not None
    # Restore the cache for the rest of the session (cleanly rebuilt).
    vt._record_validator.cache_clear()


# --- Blocker 2: monotonic one-winner version CAS (both backends) ----------------


def test_create_rejects_nonzero_version(stores):
    """create must require version == 0 (the CAS counter's genesis); any other version is a
    forged record and is rejected in BOTH backends."""
    jobs, _envelopes, _results = stores
    bad = dataclasses.replace(_valid_received(), version=3)
    with pytest.raises(InvalidRecord):
        jobs.create(bad)
    # version 0 still creates cleanly.
    ok = _valid_received()
    assert ok.version == 0
    jobs.create(ok)
    assert jobs.get(ok.job_id).version == 0


def test_cas_update_requires_exactly_expected_plus_one(stores):
    """cas_update must advance the version by EXACTLY one past expected_version, BEFORE the
    stored-version guard, in BOTH backends: unchanged / decreased / skipped are rejected;
    expected+1 is accepted."""
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)  # version 0 stored
    base = jobs.get(record.job_id)
    assert base.version == 0

    # candidate.version == expected (unchanged) -> rejected.
    with pytest.raises(InvalidRecord):
        jobs.cas_update(dataclasses.replace(base, state="queued", version=0), 0)
    # candidate.version < expected (decreased) -> rejected. Use expected=1 so the candidate
    # version 0 is strictly below it; the stored version is still 0 (the monotonic check
    # fires first, before the stored-version guard ever runs).
    with pytest.raises(InvalidRecord):
        jobs.cas_update(dataclasses.replace(base, state="queued", version=0), 1)
    # candidate.version == expected + 2 (skipped) -> rejected.
    with pytest.raises(InvalidRecord):
        jobs.cas_update(dataclasses.replace(base, state="queued", version=2), 0)
    # Nothing landed: the stored record is still the version-0 received record.
    assert jobs.get(record.job_id).state == "received"
    assert jobs.get(record.job_id).version == 0

    # candidate.version == expected + 1 -> accepted (and lands).
    won = jobs.cas_update(dataclasses.replace(base, state="queued", version=1), 0)
    assert won is True
    assert jobs.get(record.job_id).state == "queued"
    assert jobs.get(record.job_id).version == 1


def test_monotonic_cas_two_writes_same_expected_cannot_both_land(stores):
    """Direct-store concurrency proof: two candidates at the SAME expected_version (each a
    valid expected+1 advance) cannot both land — the first wins the stored-version CAS, the
    second loses (stored version already advanced). Combined with the monotonic guard, the
    version is a strictly monotonic one-winner counter in BOTH backends."""
    jobs, envelopes, _results = stores
    record, _ = make_received(jobs, envelopes)
    base = jobs.get(record.job_id)
    assert base.version == 0

    # Run sequentially against the shared store: the FIRST wins the stored-version CAS
    # (lands row_count=5 at version 1); the SECOND, at the same now-stale expected_version 0,
    # loses (stored version already advanced to 1). Both are valid expected+1 candidates, so
    # it is the stored-version guard — not the monotonic check — that decides win vs lose here.
    first = jobs.cas_update(dataclasses.replace(base, state="queued", row_count=5, version=1), 0)
    second = jobs.cas_update(dataclasses.replace(base, state="queued", row_count=9, version=1), 0)
    assert [first, second] == [True, False]  # exactly one landed, and it was the first
    assert jobs.get(record.job_id).version == 1
    # The LOSING write's row_count (9) never persisted; the winner's (5) did.
    assert jobs.get(record.job_id).row_count == 5


# --- Blocker 3: reconciler dispatch claim / backoff (updated_at eligibility) -----


def test_recover_undispatched_eligibility_is_keyed_on_updated_at(stores):
    """A record CREATED long ago but whose updated_at was just advanced (e.g. by a prior
    dispatch_attempt bump) is NOT eligible until the grace window elapses past updated_at —
    even though created_at is well past grace. This is the time-based dispatch claim."""
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=5)
    # created 1h ago (well past grace) but updated_at bumped to ~now via a dispatch bump.
    job, _ = make_received(jobs, envelopes, now=now - timedelta(hours=1))
    increment_dispatch_attempt(jobs, job.job_id, 0, now=now)  # advances updated_at to now
    assert jobs.get(job.job_id).state == "received"

    calls: list[tuple[str, int]] = []

    def enqueue(job_id, dispatch_attempt):
        calls.append((job_id, dispatch_attempt))
        return True

    # Within the grace window of the fresh updated_at: NOT eligible (backoff in effect).
    acted = recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue)
    assert acted == []
    assert calls == []
    assert jobs.get(job.job_id).state == "received"

    # Once the grace window elapses past updated_at, it becomes eligible again.
    later = now + grace + timedelta(seconds=1)
    acted_later = recover_undispatched(jobs, later, dispatch_max=10, grace=grace, enqueue=enqueue)
    assert acted_later == [job.job_id]
    assert jobs.get(job.job_id).state == "queued"


def test_recover_undispatched_barrier_no_second_generation_in_grace_window(stores):
    """Barrier-controlled concurrent race: reconciler A is PAUSED after its
    increment_dispatch_attempt (via an enqueue callback that blocks on a barrier) while
    reconciler B runs a full sweep concurrently. Because the bump advanced updated_at to
    `now`, B finds the just-bumped record inside its grace window and does NOT start a second
    dispatch generation: only ONE generation is in flight, dispatch_attempt advances by
    exactly one, and B re-dispatches nothing."""
    jobs, envelopes, _results = stores
    now = _now()
    grace = timedelta(minutes=5)
    job, _ = make_received(jobs, envelopes, now=now - timedelta(hours=1))

    a_in_enqueue = threading.Event()
    release_a = threading.Event()
    a_enqueue_calls: list[tuple[str, int]] = []
    b_enqueue_calls: list[tuple[str, int]] = []

    def enqueue_a(job_id, dispatch_attempt):
        # A has already done phase-1 increment_dispatch_attempt (updated_at now == `now`);
        # it is paused here BEFORE its phase-3 received->queued flip.
        a_enqueue_calls.append((job_id, dispatch_attempt))
        a_in_enqueue.set()
        release_a.wait(timeout=5)
        return True

    def enqueue_b(job_id, dispatch_attempt):
        b_enqueue_calls.append((job_id, dispatch_attempt))
        return True

    def run_a():
        recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue_a)

    ta = threading.Thread(target=run_a)
    ta.start()
    assert a_in_enqueue.wait(timeout=5)  # A is paused mid-enqueue, having bumped updated_at

    # While A is paused (record still `received`, updated_at == now), B sweeps. B must NOT
    # start a second generation: the record is within its grace window of the fresh
    # updated_at, so B skips it entirely (no enqueue, no bump).
    acted_b = recover_undispatched(jobs, now, dispatch_max=10, grace=grace, enqueue=enqueue_b)
    assert acted_b == []
    assert b_enqueue_calls == []  # B re-dispatched nothing
    assert jobs.get(job.job_id).dispatch_attempt == 1  # exactly one generation bump

    # Let A finish its phase-3 flip.
    release_a.set()
    ta.join(timeout=5)
    assert not ta.is_alive()
    assert a_enqueue_calls == [(job.job_id, 1)]  # only A's single generation
    assert jobs.get(job.job_id).state == "queued"
    assert jobs.get(job.job_id).dispatch_attempt == 1  # still exactly one generation


# --- Blocker 4: strict timezone-aware timestamp parsing ------------------------


def test_persistence_rejects_timezone_less_timestamps(stores):
    """A naive (timezone-less) created_at / expires_at / lease_expires_at is rejected at the
    persistence boundary (InvalidRecord), in BOTH backends — a naive value would otherwise
    persist and later raise TypeError against the tz-aware now."""
    jobs, envelopes, _results = stores
    # naive created_at
    with pytest.raises(InvalidRecord):
        jobs.create(dataclasses.replace(_valid_received(), created_at="2026-06-22T12:00:00"))
    # naive expires_at
    with pytest.raises(InvalidRecord):
        jobs.create(dataclasses.replace(_valid_received(), expires_at="2026-06-22T12:00:00"))
    # naive lease_expires_at on an executing record (the only state carrying a lease).
    now = _now()
    rec, _ = make_received(jobs, envelopes, now=now)
    # Build a would-be executing record with a tz-LESS lease deadline and CAS it: rejected.
    queued = api_received_to_queued(jobs, rec.job_id, 0, now=now)
    bad_executing = dataclasses.replace(
        jobs.get(rec.job_id),
        state="executing",
        lease_owner="w1",
        lease_expires_at="2026-06-22T12:00:00",  # tz-less
        version=queued.version + 1,
    )
    with pytest.raises(InvalidRecord):
        jobs.cas_update(bad_executing, queued.version)


def test_lease_acquisition_rejects_tz_less_deadline(stores):
    """Lease acquisition rejects a timezone-less lease deadline (InvalidLease via the strict
    parser), distinct from a well-formed but past deadline."""
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    with pytest.raises(InvalidLease):
        worker_queued_to_executing(
            jobs, record.job_id, queued.version, lease_owner="w1",
            lease_expires_at="2026-06-22T12:00:00", now=now,  # tz-less
        )
    assert jobs.get(record.job_id).state == "queued"  # no acquisition landed


def test_heartbeat_rejects_tz_less_new_deadline(stores):
    """A heartbeat with a timezone-less new deadline is rejected (InvalidLease)."""
    jobs, envelopes, _results = stores
    now = _now()
    record, _ = make_received(jobs, envelopes, now=now)
    queued = api_received_to_queued(jobs, record.job_id, 0, now=now)
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now + timedelta(minutes=5)), now=now,
    )
    with pytest.raises(InvalidLease):
        worker_heartbeat(
            jobs, record.job_id, executing.version, lease_owner="w1",
            new_lease_expires_at="2026-06-22T12:00:00", now=now,  # tz-less
        )


def test_valid_z_timestamp_round_trips():
    """A well-formed ...Z timestamp parses to a tz-aware UTC datetime and a record carrying
    only ...Z timestamps persists + round-trips cleanly (the strictness only rejects bad
    input, never our own serialization)."""
    parsed = _vt_parse_iso_z("2026-06-22T12:00:00Z")
    assert parsed.tzinfo == timezone.utc
    jobs = InMemoryJobStore()
    record = _valid_received()
    jobs.create(record)
    assert jobs.get(record.job_id) is not None


def test_non_utc_offset_is_accepted_and_normalized():
    """A non-UTC offset (e.g. +05:00) is ACCEPTED and normalized to UTC: 12:00+05:00 is
    07:00Z. The parser does not require a literal Z, only an explicit, tz-aware designator."""
    parsed = _vt_parse_iso_z("2026-06-22T12:00:00+05:00")
    assert parsed.tzinfo == timezone.utc
    assert parsed.hour == 7 and parsed.minute == 0
    # A record whose timestamps carry a non-UTC offset still persists (it is tz-aware).
    now_offset = "2026-06-22T12:00:00+05:00"
    later_offset = "2026-06-23T12:00:00+05:00"
    jobs = InMemoryJobStore()
    record = dataclasses.replace(
        _valid_received(),
        created_at=now_offset,
        updated_at=now_offset,
        expires_at=later_offset,
    )
    jobs.create(record)
    assert jobs.get(record.job_id) is not None
