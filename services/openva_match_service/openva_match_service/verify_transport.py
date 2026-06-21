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
from dataclasses import dataclass
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
    def active_count(self) -> int: ...

    @abstractmethod
    def purge_expired(self, now: datetime, retained_window: timedelta) -> list[JobRecord]:
        """Physically delete every job record whose retained window has fully elapsed
        (``now >= expires_at + retained_window``) and return the deleted RECORDS.

        This realizes the hosted-deployment.yaml `expiry` model in the in-memory
        transport: a record stays retained (poll -> 410) for ``retained_window`` past
        ``expires_at``, then is physically removed (poll -> 404). In production the
        store-native TTL + object-lifecycle does this; WP-02B swaps that backend in.
        The job store removes ONLY the job records here; the caller (purge_expired_jobs)
        uses the returned records' request_ref/result_ref to delete the matching
        transient envelope/result blobs."""
        ...


class InMemoryJobStore(JobStore):
    """In-memory, NON-DURABLE job store. Lost on process restart. The durable
    backend is WP-02B."""

    def __init__(self) -> None:
        self._records: dict[str, JobRecord] = {}

    def create(self, record: JobRecord) -> None:
        self._records[record.job_id] = record

    def get(self, job_id: str) -> JobRecord | None:
        return self._records.get(job_id)

    def active_count(self) -> int:
        return sum(1 for record in self._records.values() if not record.is_terminal())

    def purge_expired(self, now: datetime, retained_window: timedelta) -> list[JobRecord]:
        purged: list[JobRecord] = []
        for job_id, record in list(self._records.items()):
            if now >= _parse_iso_z(record.expires_at) + retained_window:
                del self._records[job_id]
                purged.append(record)
        return purged


class RequestEnvelopeStore(ABC):
    """Transient submitted-input envelope store interface (keyed by request_ref).

    Holds the submitted verify rows transiently for the worker to read. The
    envelope is never carried in the job record or the queue. WP-02B swaps a
    durable/encrypted-at-rest backend behind this interface."""

    @abstractmethod
    def put(self, ref: str, envelope: Any) -> None: ...

    @abstractmethod
    def get(self, ref: str) -> Any | None: ...

    @abstractmethod
    def delete(self, ref: str) -> None: ...


class InMemoryRequestEnvelopeStore(RequestEnvelopeStore):
    """In-memory, NON-DURABLE, transient request-envelope store. The durable,
    encrypted-at-rest backend is WP-02B."""

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
    """Opportunistically advance the expiry lifecycle by PHYSICALLY deleting every job
    whose retained window has fully elapsed, together with its transient request
    envelope (request_ref) and any result blob (result_ref).

    This is the in-memory realization of the hosted-deployment.yaml `expiry.deletes`
    set (job_record + transient_request_envelope + result_blob): the 410-while-retained
    -> 404-after-deletion transition is PHYSICAL, not a status-only flag. The job store
    returns the records it removed, so the envelope/result deletes run by ref.
    Returns the deleted job_ids. Idempotent: deleting an absent ref is a no-op."""
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
