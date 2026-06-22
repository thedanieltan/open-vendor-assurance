"""Hosted verify-mode transport primitives (WP-02A).

This module ships the TRANSPORT + API contract for the hosted verify resolver
behind the ``OPENVA_VERIFY_TRANSPORT_ENABLED`` flag (default off). It deliberately
ships NO durable persistence, NO async worker, and NO queue: the stores here are
IN-MEMORY, NON-DURABLE implementations behind small interfaces (Protocol/ABC) so a
later slice (WP-02B) can swap durable backends without changing the API surface.

Because there is no worker in this slice, a created job stays in ``received`` and
never executes — that is the correct, documented behaviour for WP-02A.

Authoritative references:
  - docs/operations/contracts/hosted-deployment.yaml (job model, token transport)
  - schemas/openva/hosted-job-record.schema.json (job record shape + invariants)

Security posture (enforced here and at the route layer):
  - The job_token capability is accepted ONLY via ``Authorization: Bearer`` — there
    is no query-string, path, cookie, or redirect acceptance anywhere.
  - Only the SHA-256 digest (``sha256:<hex>``) of the token is stored; the raw token
    is NEVER stored and NEVER logged.
  - Token comparison is CONSTANT-TIME (``hmac.compare_digest`` on the digests).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

SCHEMA_VERSION = "0.1.0"
FRESHNESS_MODE_VERIFY = "verify"

# Non-terminal (active) job states, per hosted-deployment.yaml job_states /
# terminal_states. Used by active_count() for the optional concurrency cap.
TERMINAL_STATES = frozenset({"completed", "failed"})
NON_TERMINAL_STATES = frozenset({"received", "queued", "executing"})


# --- Token capability helpers (header-only, digest-only, constant-time) -------


def new_job_token() -> str:
    """Return a fresh high-entropy job_token capability (returned to the client
    exactly once, at job creation). The raw value is never stored or logged."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """Return the storable/comparable digest for a token: ``sha256:<hex>``.

    Only the digest is ever persisted (job_token_digest); the raw token is not."""
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


def digests_match(provided_digest: str, stored_digest: str) -> bool:
    """Constant-time equality of two ``sha256:<hex>`` digests.

    Uses ``hmac.compare_digest`` so the comparison time does not depend on how many
    leading characters match, defeating timing oracles on the capability."""
    return hmac.compare_digest(provided_digest, stored_digest)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Parse ``Authorization: Bearer <token>`` and return ``<token>``.

    The scheme is matched case-insensitively. Returns None when the header is
    absent or malformed. HEADER ONLY — there is no query/path/cookie fallback
    anywhere in the verify transport; the token must arrive in this header."""
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, value = parts
    if scheme.lower() != "bearer":
        return None
    token = value.strip()
    return token or None


# --- Job record (mirrors hosted-job-record.schema.json) -----------------------


@dataclass
class JobRecord:
    """In-memory mirror of one hosted verify job record.

    Fields mirror schemas/openva/hosted-job-record.schema.json. ``to_record_dict``
    emits a dict valid under that schema for the CURRENT state (it honours the
    state-dependent invariants: received/queued carry a live request_ref with no
    result/error/lease; completed carries result_ref with request_ref nulled; etc.).

    NOTE: this dataclass is an in-memory, non-durable representation. The durable
    backend is WP-02B.
    """

    job_id: str
    job_token_digest: str
    state: str
    request_ref: str | None
    row_count: int
    created_at: str
    updated_at: str
    expires_at: str
    schema_version: str = SCHEMA_VERSION
    freshness_mode: str = FRESHNESS_MODE_VERIFY
    result_ref: str | None = None
    error_code: str | None = None
    attempt: int = 0
    dispatch_attempt: int = 0
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    # Optimistic-concurrency version (WP-02B). CAS is on this version: every successful
    # guarded mutation increments it and persists with a version-guarded write; a stale
    # expected_version fails the CAS and the actor re-reads. Defaults to 0 so WP-02A
    # records (which never set it) round-trip unchanged.
    version: int = 0
    not_advice: bool = True

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_record_dict(self) -> dict[str, Any]:
        """Emit a schema-valid record dict for the current state.

        The schema's ``allOf`` invariants are state-dependent, so we project the
        nullable fields per state rather than dumping raw attributes. The raw
        job_token is NEVER part of this dict — only job_token_digest is."""
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "job_token_digest": self.job_token_digest,
            "state": self.state,
            "freshness_mode": self.freshness_mode,
            "row_count": self.row_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "attempt": self.attempt,
            "dispatch_attempt": self.dispatch_attempt,
            "version": self.version,
            "not_advice": self.not_advice,
        }

        if self.state in ("received", "queued"):
            # Live envelope; no result/error; not yet leased.
            record["request_ref"] = self.request_ref
            record["result_ref"] = None
            record["error_code"] = None
            record["lease_owner"] = None
            record["lease_expires_at"] = None
        elif self.state == "executing":
            record["request_ref"] = self.request_ref
            record["result_ref"] = None
            record["error_code"] = None
            record["lease_owner"] = self.lease_owner
            record["lease_expires_at"] = self.lease_expires_at
        elif self.state == "completed":
            # Result present; envelope deleted (request_ref nulled); lease released.
            record["request_ref"] = None
            record["result_ref"] = self.result_ref
            record["error_code"] = None
            record["lease_owner"] = None
            record["lease_expires_at"] = None
        elif self.state == "failed":
            # Generic error; no result; envelope deleted; lease released.
            record["request_ref"] = None
            record["result_ref"] = None
            record["error_code"] = self.error_code
            record["lease_owner"] = None
            record["lease_expires_at"] = None

        return record


# --- Store interfaces + in-memory (non-durable) implementations ---------------


class JobStore(ABC):
    """Durable job store interface. WP-02A ships only the in-memory impl below;
    WP-02B swaps a durable backend behind this same interface."""

    @abstractmethod
    def create(self, record: JobRecord) -> None: ...

    @abstractmethod
    def get(self, job_id: str) -> JobRecord | None: ...

    @abstractmethod
    def cas_update(self, record: JobRecord, expected_version: int) -> bool:
        """Optimistic-concurrency persist (WP-02B). Atomically replace the stored
        record for ``record.job_id`` ONLY IF its currently-stored version equals
        ``expected_version`` (the value the caller read before mutating). The caller
        has already set ``record.version`` to ``expected_version + 1`` and applied the
        mutated fields. Returns True when the write landed (one row matched) and False
        when the version did not match (a concurrent writer won — the actor must
        re-read). Durable backends realize this as ``UPDATE ... WHERE job_id=? AND
        version=?`` and check the affected rowcount.

        This is the SINGLE persistence primitive the job_lifecycle CAS protocol uses,
        so the version-CAS semantics are identical across the in-memory and durable
        backends."""
        ...

    @abstractmethod
    def active_count(self) -> int: ...

    @abstractmethod
    def iter_records(self) -> list[JobRecord]:
        """Return a stable snapshot list of the store's current records.

        Used by the watchdog/reconciler sweeps (job_lifecycle) as an ENUMERATION source
        only — each sweep mutation re-reads via ``get`` inside its guarded transition and
        persists with a version-guarded CAS, so a record that changed between the
        snapshot and the CAS is simply skipped this pass. The list contains copies, so a
        caller cannot mutate stored rows by holding a reference."""
        ...

    @abstractmethod
    def expired_request_refs(self, now: datetime) -> list[str]:
        """Return the request_ref of every record that is EXPIRED (``now >=
        expires_at``) but still carries a non-null request_ref — i.e. the submitted
        input is still present at/after TTL.

        This realizes the contract's `expiry` minimisation phase: the REQUEST ENVELOPE
        is deleted at/after ``expires_at`` (submitted input gone at TTL), strictly
        BEFORE the record's retained window elapses and the record is physically
        removed. The job store does not delete the envelope itself (that is a separate
        physical store); the caller (purge_expired_jobs) deletes by these refs and then
        clears the in-record pointer is unnecessary because the record is content-free
        operational metadata and is itself purged once the retained window elapses."""
        ...

    @abstractmethod
    def purge_expired(self, now: datetime, retained_window: timedelta) -> list[JobRecord]:
        """Physically delete every job record whose retained window has fully elapsed
        (``now >= expires_at + retained_window``) and return the deleted RECORDS.

        This realizes the hosted-deployment.yaml `expiry` model in the transport: a
        record stays retained (poll -> 410) for ``retained_window`` past ``expires_at``,
        then is physically removed (poll -> 404). In production the store-native TTL +
        object-lifecycle does this; the SQLite reference backend (sqlite_stores.py)
        demonstrates the same semantics durably. The job store removes ONLY the job
        records here; the caller (purge_expired_jobs) uses the returned records'
        request_ref/result_ref to delete the matching transient envelope/result blobs."""
        ...


class InMemoryJobStore(JobStore):
    """In-memory, NON-DURABLE job store. Lost on process restart. The durable
    backend is WP-02B."""

    def __init__(self) -> None:
        self._records: dict[str, JobRecord] = {}

    def create(self, record: JobRecord) -> None:
        # Store a snapshot copy so the caller's reference cannot mutate the stored
        # record without going through cas_update (mirrors a durable backend, where the
        # in-process object is never the stored row).
        self._records[record.job_id] = replace(record)

    def get(self, job_id: str) -> JobRecord | None:
        stored = self._records.get(job_id)
        # Hand back a fresh copy so mutations by the caller do not retroactively change
        # the stored row except through cas_update (the version-CAS gate).
        return replace(stored) if stored is not None else None

    def cas_update(self, record: JobRecord, expected_version: int) -> bool:
        stored = self._records.get(record.job_id)
        if stored is None or stored.version != expected_version:
            return False
        self._records[record.job_id] = replace(record)
        return True

    def active_count(self) -> int:
        return sum(1 for record in self._records.values() if not record.is_terminal())

    def iter_records(self) -> list[JobRecord]:
        return [replace(record) for record in self._records.values()]

    def expired_request_refs(self, now: datetime) -> list[str]:
        return [
            record.request_ref
            for record in self._records.values()
            if record.request_ref is not None and now >= _parse_iso_z(record.expires_at)
        ]

    def purge_expired(self, now: datetime, retained_window: timedelta) -> list[JobRecord]:
        purged: list[JobRecord] = []
        for job_id, record in list(self._records.items()):
            if now >= _parse_iso_z(record.expires_at) + retained_window:
                del self._records[job_id]
                purged.append(record)
        return purged


class RequestEnvelopeStore(ABC):
    """Transient request-envelope store interface (keyed by request_ref).

    WP-02B persists the submitted verify rows here so the worker (WP-02C) can read them;
    minimisation is provided by the deployment-managed encryption-at-rest plus the
    three-phase TTL deletion (the envelope is deleted at/after ``expires_at``) and the
    terminal deletion (deleted on completion/failure). The envelope is never carried in
    the job record (which holds only a request_ref pointer + minimised metadata) or the
    queue (which carries job_id only)."""

    @abstractmethod
    def put(self, ref: str, envelope: Any) -> None: ...

    @abstractmethod
    def get(self, ref: str) -> Any | None: ...

    @abstractmethod
    def delete(self, ref: str) -> None: ...


class InMemoryRequestEnvelopeStore(RequestEnvelopeStore):
    """In-memory, NON-DURABLE, transient request-envelope store. A durable reference
    backend (SQLite) is in ``sqlite_stores.py``; production encryption-at-rest is a
    deployment/infra concern (WP-02F/G)."""

    def __init__(self) -> None:
        self._envelopes: dict[str, Any] = {}

    def put(self, ref: str, envelope: Any) -> None:
        self._envelopes[ref] = envelope

    def get(self, ref: str) -> Any | None:
        return self._envelopes.get(ref)

    def delete(self, ref: str) -> None:
        self._envelopes.pop(ref, None)


class ResultStore(ABC):
    """Transient result-blob store interface (keyed by result_ref). WP-02B swaps a
    durable/TTL backend behind this interface."""

    @abstractmethod
    def put(self, ref: str, result: Any) -> None: ...

    @abstractmethod
    def get(self, ref: str) -> Any | None: ...

    @abstractmethod
    def delete(self, ref: str) -> None: ...


class InMemoryResultStore(ResultStore):
    """In-memory, NON-DURABLE, transient result-blob store. The durable, TTL
    backend is WP-02B."""

    def __init__(self) -> None:
        self._results: dict[str, Any] = {}

    def put(self, ref: str, result: Any) -> None:
        self._results[ref] = result

    def get(self, ref: str) -> Any | None:
        return self._results.get(ref)

    def delete(self, ref: str) -> None:
        self._results.pop(ref, None)


# --- Expiry / purge coordination ----------------------------------------------


def _parse_iso_z(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (with Z or offset) to a timezone-aware datetime.

    Local to the transport so the job store can decide its own retained-window
    physical-deletion boundary without importing the route layer."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def purge_expired_jobs(
    jobs: JobStore,
    envelopes: RequestEnvelopeStore,
    results: ResultStore,
    now: datetime,
    retained_window: timedelta,
) -> list[str]:
    """Opportunistically advance the THREE-PHASE expiry lifecycle on the stores.

    Realizes the hosted-deployment.yaml `expiry` model:
      Phase 2 (expired-but-retained, ``expires_at <= now < expires_at + retained_window``):
        the REQUEST ENVELOPE is deleted at/after ``expires_at`` for data minimisation —
        the submitted input is gone at TTL even though the (content-free) record is
        retained so the poll can still return 410. Idempotent: re-deleting an
        already-deleted envelope is a no-op, so repeated opportunistic sweeps are safe.
      Phase 3 (physically deleted, ``now >= expires_at + retained_window``): the record,
        its envelope (if any pointer remains), and its result blob are all removed, so a
        later poll is a content-free 404. This is the `expiry.deletes` set
        (job_record + transient_request_envelope + result_blob).

    In production the store-native TTL + object-lifecycle does both; the SQLite reference
    backend (sqlite_stores.py) demonstrates the same semantics durably. Returns the
    job_ids physically deleted in phase 3."""
    # Phase 2: minimise expired-but-retained input (delete the envelope at TTL).
    for ref in jobs.expired_request_refs(now):
        envelopes.delete(ref)
    # Phase 3: physical deletion of the record + any remaining envelope/result.
    purged = jobs.purge_expired(now, retained_window)
    for record in purged:
        if record.request_ref is not None:
            envelopes.delete(record.request_ref)
        if record.result_ref is not None:
            results.delete(record.result_ref)
    return [record.job_id for record in purged]


# --- Identifier helpers -------------------------------------------------------


def new_job_id() -> str:
    """Server-generated opaque correlation id (UUID4). Loggable; NOT a credential."""
    return str(uuid.uuid4())


def new_ref() -> str:
    """Opaque pointer for the transient envelope/result stores."""
    return uuid.uuid4().hex
