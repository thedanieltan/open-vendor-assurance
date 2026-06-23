"""WP-02D candidate-ingress (discovery-only) boundary tests.

Asserts the hosted match service's discovery role:

- discovery-only boundary: proposing a candidate writes NO ``data/**``, performs NO
  catalogue mutation and NO merge — it only STAGES into the EXISTING candidate ingress
  (here an in-memory ingress sink);
- uses the existing ingress, not a second path: the proposed candidate carries the SAME
  deterministic candidate id + evidence digest the existing ``candidate_record`` machinery
  produces (not a parallel re-implementation);
- separation of duties: the worker/proposer holds no GitHub credential; the discovery
  proposal is distinct from any decision/merge; an already-catalogued or non-new resolution
  proposes nothing;
- off by default: a worker built WITHOUT the proposer (default) proposes nothing and the
  verify result is identical whether or not ingress is enabled; a proposer failure never
  fails the verify job;
- idempotency: proposing the same discovery twice is idempotent (same candidate id; the
  durable ingress dedups).

All tests are DETERMINISTIC with NO network: a FAKE resolver builds candidate records via
the SAME ``vendor_resolution`` emitter machinery the real resolver uses, and an in-memory
ingress (``RecordingIngress``) stands in for the durable ``maintenance/candidates`` queue.
Parametrized over the in-memory and durable SQLite stores (like the WP-02C worker tests).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service import candidate_ingress as ci  # noqa: E402
from openva_match_service import job_lifecycle as jl  # noqa: E402
from openva_match_service import worker as wk  # noqa: E402
from openva_match_service.config import ServiceConfig  # noqa: E402
from openva_match_service.queue import InMemoryQueue  # noqa: E402
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

from tools.openva import candidate_record  # noqa: E402
from tools.openva.vendor_resolution import (  # noqa: E402
    RecordingIngress,
    SessionEmitter,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- store fixtures (parametrized over in-memory + durable SQLite) -------------


def _in_memory_stores():
    return InMemoryJobStore(), InMemoryRequestEnvelopeStore(), InMemoryResultStore()


def _sqlite_stores(tmp_path):
    db = str(tmp_path / "wp02d.db")
    return SqliteJobStore(db), SqliteRequestEnvelopeStore(db), SqliteResultStore(db)


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return _in_memory_stores()
    return _sqlite_stores(tmp_path)


def make_received(jobs, envelopes, *, now=None, rows=None):
    now = now or _now()
    if rows is None:
        rows = [{"row_id": "1", "vendor_name": "Acme", "domain": "acme.test"}]
    token = new_job_token()
    request_ref = new_ref()
    expires_at = _iso(now + timedelta(hours=24))
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
    now = now or _now()
    return jl.api_received_to_queued(jobs, record.job_id, record.version, now=now)


# --- candidate-building shared with the REAL ingress machinery -----------------

# Inputs for a single discovered candidate. Building it via SessionEmitter.emit() — the SAME
# entry point the real resolver uses — is what proves "uses the existing ingress, not a
# second path": the deterministic id/digest are produced by the one canonical machinery.
DISCOVERY = dict(
    candidate_origin="catalog_discovery",
    origin_reference="acme:acme.test",
    discovery_component="vendor_resolution:public_matcher_discovery",
    vendor_identity_candidate={"vendor_id_candidate": "acme", "official_domain": "acme.test"},
    source_candidates=[
        {
            "candidate_url": "https://acme.test/legal/dpa",
            "final_url": "https://acme.test/legal/dpa",
            "http_status": 200,
            "content_type": "text/html",
            "source_type_candidate": "dpa",
            "access_state": "public_reachable",
            "source_role": "primary_assurance",
            "on_vendor_domain": True,
            "verification_result": "likely_vendor_published",
            "reasons": ["matched_terms:3"],
        }
    ],
    evidence_references=[
        {
            "candidate_url": "https://acme.test/legal/dpa",
            "final_url": "https://acme.test/legal/dpa",
            "http_status": 200,
            "content_type": "text/html",
            "verification_result": "likely_vendor_published",
            "observed_at": "2026-06-23T00:00:00Z",
        }
    ],
    created_at="2026-06-23T00:00:00Z",
    is_new_vendor=True,
)


def _emit_candidate(emitter: SessionEmitter) -> dict:
    """Build ONE discovered candidate through the SAME emitter machinery the resolver uses."""
    return emitter.emit(**DISCOVERY).record


def _canonical_candidate_record() -> dict:
    """The candidate the EXISTING machinery produces, via a throwaway in-memory ingress."""
    return _emit_candidate(SessionEmitter(RecordingIngress()))


class DiscoveringResolver:
    """A deterministic fake resolver that, GIVEN a capture emitter, emits one discovered
    candidate (mimicking the real resolver) and returns a ``newly_discovered`` resolution.

    Records every call so a test can assert the worker always passes the SSRF-safe
    fetcher_factory and an emitter only when capture is on (off by default)."""

    def __init__(self, status: str = "newly_discovered"):
        self.status = status
        self.calls = []

    def __call__(self, request, *, catalog=None, fetcher_factory=None, emitter=None, **kwargs):
        self.calls.append({"request": request, "fetcher_factory": fetcher_factory, "emitter": emitter})
        if emitter is not None:
            _emit_candidate(emitter)
        return {"resolution_status": self.status, "vendor": request.get("vendor", {}), "not_advice": True}


def make_worker(stores, queue, *, resolver=None, proposer=None, config=None, now=None):
    jobs, envelopes, results = stores
    return wk.VerifyWorker(
        jobs, envelopes, results, queue,
        catalog=None,
        config=config or wk.WorkerConfig(),
        resolve=resolver or DiscoveringResolver(),
        now=now or _now,
        proposer=proposer,
    )


def drive_to_completion(stores, *, resolver, proposer):
    jobs, envelopes, results = stores
    q = InMemoryQueue()
    record, _ = make_received(jobs, envelopes)
    to_queued(jobs, record)
    q.enqueue(record.job_id, dispatch_attempt=0)
    worker = make_worker(stores, q, resolver=resolver, proposer=proposer)
    outcomes = worker.run_once()
    return record, worker, outcomes


# --- off by default: no proposer -> proposes nothing, identical to WP-02C ------


def test_off_by_default_worker_proposes_nothing_and_calls_resolver_without_emitter(stores):
    resolver = DiscoveringResolver()
    record, _worker, outcomes = drive_to_completion(stores, resolver=resolver, proposer=None)
    jobs, _envelopes, results = stores
    assert outcomes == ["completed"]
    # No emitter is passed when ingress is off -> the resolver builds NO candidate, and the
    # worker behaves exactly as the WP-02C worker.
    assert resolver.calls and resolver.calls[0]["emitter"] is None
    # The verify result is the WP-02C shape.
    final = jobs.get(record.job_id)
    blob = results.get(final.result_ref)
    assert blob["rows"][0]["resolution"]["resolution_status"] == "newly_discovered"


def test_verify_result_identical_whether_or_not_ingress_enabled(stores):
    # Same stores would be mutated, so run two independent jobs and compare result blobs.
    jobs, envelopes, results = stores
    sink = RecordingIngress()
    proposer = ci.DurableIngressProposer(ingress=sink)

    def _result_blob(proposer_arg):
        q = InMemoryQueue()
        record, _ = make_received(jobs, envelopes)
        to_queued(jobs, record)
        q.enqueue(record.job_id, dispatch_attempt=0)
        worker = make_worker(stores, q, resolver=DiscoveringResolver(), proposer=proposer_arg)
        assert worker.run_once() == ["completed"]
        blob = results.get(jobs.get(record.job_id).result_ref)
        return blob

    off = _result_blob(None)
    on = _result_blob(proposer)
    # The verify RESULT is byte-identical regardless of the (side-output) ingress.
    assert off == on
    # But with ingress on, a candidate WAS staged into the existing ingress sink.
    assert len(sink.records) == 1


# --- discovery-only boundary: stages into the existing ingress sink ONLY -------


def test_proposing_stages_into_existing_ingress_and_writes_no_data(stores, tmp_path):
    sink = RecordingIngress()
    proposer = ci.DurableIngressProposer(ingress=sink)
    record, _worker, outcomes = drive_to_completion(
        stores, resolver=DiscoveringResolver(), proposer=proposer
    )
    assert outcomes == ["completed"]
    # The discovery was STAGED into the in-memory candidate ingress sink (and ONLY there).
    assert len(sink.records) == 1
    staged_id = next(iter(sink.records))
    assert staged_id.startswith("cand-")
    # No data/** write and no catalogue mutation: the in-memory sink is the only target and
    # there is no filesystem candidate dir or vendor dir created by the proposal.
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "maintenance").exists()


def test_durable_ingress_proposer_holds_no_github_credential():
    # Separation of duties: the proposer is provider-neutral application code with no
    # credential attribute and no PR-open / merge surface — it ONLY enqueues.
    proposer = ci.DurableIngressProposer(ingress=RecordingIngress())
    for attr in ("github_app_key", "token", "credential", "open_pr", "merge"):
        assert not hasattr(proposer, attr)
    # The only public operation is propose() (the discovery-staging boundary).
    assert hasattr(proposer, "propose")


def test_worker_holds_no_github_credential_and_passes_safe_fetcher(stores):
    resolver = DiscoveringResolver()
    sink = RecordingIngress()
    record, worker, _ = drive_to_completion(
        stores, resolver=resolver, proposer=ci.DurableIngressProposer(ingress=sink)
    )
    # The worker carries no GitHub credential anywhere.
    for attr in ("github_app_key", "token", "credential"):
        assert not hasattr(worker, attr)
    # It always passes the SSRF-safe fetcher_factory (never an arbitrary fetcher).
    assert resolver.calls[0]["fetcher_factory"] is wk.default_fetcher_factory
    # And it passes a capture emitter ONLY because ingress is on.
    assert resolver.calls[0]["emitter"] is not None


# --- uses the existing ingress (same deterministic id/digest), not a 2nd path --


def test_proposed_candidate_matches_existing_machinery_id_and_digest(stores):
    sink = RecordingIngress()
    proposer = ci.DurableIngressProposer(ingress=sink)
    drive_to_completion(stores, resolver=DiscoveringResolver(), proposer=proposer)

    canonical = _canonical_candidate_record()
    staged = next(iter(sink.records.values()))
    # The proposal carries the SAME deterministic candidate id + evidence digest the
    # existing candidate_record machinery produces — proving it is the existing ingress, not
    # a parallel re-implementation.
    assert staged["candidate_id"] == canonical["candidate_id"]
    assert staged["evidence_digest"] == canonical["evidence_digest"]
    assert staged["candidate_id"] == candidate_record.compute_candidate_id(
        DISCOVERY["candidate_origin"], DISCOVERY["origin_reference"]
    )
    # The staged record is schema-valid (the one canonical validator accepts it).
    assert candidate_record.validate_candidate(staged) == []


# --- separation of duties: non-new / catalogued resolution proposes nothing ----


@pytest.mark.parametrize("status", ["catalog_current", "catalogued", "not_found", "identity_ambiguous"])
def test_already_catalogued_or_non_new_resolution_proposes_nothing(stores, status):
    sink = RecordingIngress()
    proposer = ci.DurableIngressProposer(ingress=sink)
    # A resolver that returns a non-new status AND emits nothing (no discovery to propose).
    class NonNewResolver(DiscoveringResolver):
        def __call__(self, request, *, catalog=None, fetcher_factory=None, emitter=None, **kwargs):
            self.calls.append({"request": request, "fetcher_factory": fetcher_factory, "emitter": emitter})
            return {"resolution_status": status, "vendor": request.get("vendor", {}), "not_advice": True}

    record, _worker, outcomes = drive_to_completion(
        stores, resolver=NonNewResolver(), proposer=proposer
    )
    assert outcomes == ["completed"]
    # Nothing genuinely-new -> NOTHING is proposed.
    assert sink.records == {}


def test_is_proposable_resolution_vocabulary():
    assert ci.is_proposable_resolution({"resolution_status": "newly_discovered"})
    assert ci.is_proposable_resolution({"resolution": {"resolution_status": "catalog_refreshed"}})
    assert not ci.is_proposable_resolution({"resolution_status": "catalog_current"})
    assert not ci.is_proposable_resolution({"resolution": {"resolution_status": "catalogued"}})
    assert not ci.is_proposable_resolution({"resolution_status": "not_found"})
    assert not ci.is_proposable_resolution({})


# --- a proposer failure NEVER fails the (already terminal) verify job ----------


def test_proposer_failure_never_fails_the_verify_job(stores):
    jobs, _envelopes, results = stores

    class ExplodingProposer:
        def propose(self, records):
            raise RuntimeError("ingress boom")

    record, _worker, outcomes = drive_to_completion(
        stores, resolver=DiscoveringResolver(), proposer=ExplodingProposer()
    )
    # The job is COMPLETED with a result blob despite the proposer raising.
    assert outcomes == ["completed"]
    final = jobs.get(record.job_id)
    assert final.state == "completed"
    assert results.get(final.result_ref)["rows"][0]["resolution"]["resolution_status"] == "newly_discovered"


# --- idempotency: proposing the same discovery twice is idempotent -------------


def test_proposing_same_discovery_twice_is_idempotent(stores):
    # A single shared durable sink across two independent jobs that discover the same source.
    jobs, envelopes, results = stores
    sink = RecordingIngress()
    proposer = ci.DurableIngressProposer(ingress=sink)

    for _ in range(2):
        q = InMemoryQueue()
        record, _ = make_received(jobs, envelopes)
        to_queued(jobs, record)
        q.enqueue(record.job_id, dispatch_attempt=0)
        worker = make_worker(stores, q, resolver=DiscoveringResolver(), proposer=proposer)
        assert worker.run_once() == ["completed"]

    # The durable ingress dedups by deterministic candidate id -> exactly ONE candidate.
    assert len(sink.records) == 1


def test_proposer_returns_enqueued_then_reused(stores):
    sink = RecordingIngress()
    proposer = ci.DurableIngressProposer(ingress=sink)
    canonical = _canonical_candidate_record()

    first = proposer.propose([canonical])
    second = proposer.propose([canonical])
    assert len(first) == len(second) == 1
    # First call creates the candidate; the second reuses (idempotent) the same id.
    assert first[0].enqueued is True
    assert second[0].enqueued is False
    assert first[0].candidate_id == second[0].candidate_id == canonical["candidate_id"]


def test_proposer_skips_schema_invalid_records_fail_closed(stores):
    sink = RecordingIngress()
    proposer = ci.DurableIngressProposer(ingress=sink)
    # A non-dict and a dict that is NOT a valid candidate record are both skipped.
    proposals = proposer.propose(["not-a-record", {"candidate_id": "x"}])
    assert proposals == []
    assert sink.records == {}


# --- off-by-default factory policy --------------------------------------------


def test_build_proposer_if_enabled_requires_both_flags():
    base = dict(pack_path=Path("."), api_key="k")
    # Both off -> None.
    assert wk.build_proposer_if_enabled(ServiceConfig(**base)) is None
    # Verify on, ingress off -> None.
    assert wk.build_proposer_if_enabled(ServiceConfig(**base, verify_transport_enabled=True)) is None
    # Ingress on, verify off -> None (inert; no worker runs without the transport).
    assert wk.build_proposer_if_enabled(ServiceConfig(**base, candidate_ingress_enabled=True)) is None
    # BOTH on -> the default durable-ingress proposer.
    both = ServiceConfig(**base, verify_transport_enabled=True, candidate_ingress_enabled=True)
    proposer = wk.build_proposer_if_enabled(both)
    assert isinstance(proposer, ci.DurableIngressProposer)
    assert isinstance(proposer, ci.CandidateProposer)
