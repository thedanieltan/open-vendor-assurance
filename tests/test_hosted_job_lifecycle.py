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
    JobRecord,
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
    record = JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(token),
        state="received",
        request_ref=request_ref,
        row_count=rows,
        created_at=_iso(now),
        updated_at=_iso(now),
        expires_at=_iso(now + expires_in),
    )
    jobs.create(record)
    envelopes.put(request_ref, {"row_count": rows, "rows": [{"vendor_name": "Acme"}]})
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
    worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="worker-1",
        lease_expires_at=_iso(now - timedelta(minutes=1)), now=now,  # already expired
    )
    # A redelivery whose record is executing with an EXPIRED lease must NOT preempt; it
    # defers to the watchdog (still LivePreemption from the worker's perspective).
    with pytest.raises(LivePreemption):
        worker_queued_to_executing(
            jobs, record.job_id, queued.version + 1, lease_owner="worker-2",
            lease_expires_at=_iso(now + timedelta(minutes=5)), now=now,
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
    results.put(result_ref, {"rows": [{"status": "ok"}]})
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
    executing = worker_queued_to_executing(
        jobs, record.job_id, queued.version, lease_owner="w1",
        lease_expires_at=_iso(now - timedelta(seconds=1)), now=now,  # stale
    )
    assert executing.attempt == 0
    requeued = watchdog_executing_to_queued(jobs, record.job_id, executing.version, now=now)
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
        lease_expires_at=_iso(now - timedelta(seconds=1)), now=now,
    )
    failed = watchdog_executing_to_failed(jobs, envelopes, record.job_id, executing.version, now=now)
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
    # job A: stale lease, attempt < max -> re-queued (attempt+1)
    a, _ = make_received(jobs, envelopes, now=now)
    qa = api_received_to_queued(jobs, a.job_id, 0, now=now)
    worker_queued_to_executing(
        jobs, a.job_id, qa.version, lease_owner="w1", lease_expires_at=_iso(now - timedelta(seconds=1)), now=now
    )
    # job B: stale lease, attempt already at max -> failed(execution_timeout)
    b, _ = make_received(jobs, envelopes, now=now)
    qb = api_received_to_queued(jobs, b.job_id, 0, now=now)
    eb = worker_queued_to_executing(
        jobs, b.job_id, qb.version, lease_owner="w1", lease_expires_at=_iso(now - timedelta(seconds=1)), now=now
    )
    # Drive attempt up to the max by repeated stale requeue+reexecute is overkill; set it
    # via a watchdog requeue then re-execute once so attempt==1, and use attempt_max=1.
    rb = watchdog_executing_to_queued(jobs, b.job_id, eb.version, now=now)  # attempt -> 1
    web = worker_queued_to_executing(
        jobs, b.job_id, rb.version, lease_owner="w1", lease_expires_at=_iso(now - timedelta(seconds=1)), now=now
    )
    assert web.attempt == 1
    # job C: LIVE lease -> untouched
    c, _ = make_received(jobs, envelopes, now=now)
    qc = api_received_to_queued(jobs, c.job_id, 0, now=now)
    worker_queued_to_executing(
        jobs, c.job_id, qc.version, lease_owner="w1", lease_expires_at=_iso(now + timedelta(minutes=10)), now=now
    )

    b_ref = jobs.get(b.job_id).request_ref  # capture before terminalization nulls it
    acted = recover_stale_leases(jobs, envelopes, now, attempt_max=1)
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

    acted = recover_undispatched(jobs, now, dispatch_max=2, grace=grace)
    assert acted == [old.job_id]
    assert jobs.get(old.job_id).state == "queued"
    assert jobs.get(old.job_id).dispatch_attempt == 1
    assert jobs.get(fresh.job_id).state == "received"  # still within grace
    assert jobs.get(exhausted.job_id).state == "received"  # exhausted, not re-dispatched


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
    results.put(deleted_result_ref, {"rows": []})
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
    results.put("result/1", {"ok": True})
    assert results.get("result/1") == {"ok": True}
    # Round-trips through to_record_dict + schema.
    _validate(fetched)


def test_sqlite_version_cas_rejects_stale_update(tmp_path):
    import dataclasses

    jobs, envelopes, _results = _sqlite_stores(tmp_path)
    record, _ = make_received(jobs, envelopes)
    # A CAS at the correct version wins; the same expected_version then loses.
    won = jobs.cas_update(dataclasses.replace(record, state="queued", version=1), 0)
    assert won is True
    lost = jobs.cas_update(dataclasses.replace(record, state="failed", version=1), 0)
    assert lost is False
    assert jobs.get(record.job_id).state == "queued"


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
    results.put(result_ref, {"rows": [{"status": "ok"}]})
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
    for exc in (IllegalTransition, UnauthorizedActor, StaleVersion, LivePreemption):
        assert issubclass(exc, LifecycleError)
