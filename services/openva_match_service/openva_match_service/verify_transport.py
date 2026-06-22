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
import importlib.resources
import json
import secrets
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jsonschema

SCHEMA_VERSION = "0.1.0"
FRESHNESS_MODE_VERIFY = "verify"

# Allowed JOB error_code vocabulary (schemas/openva/hosted-job-record.schema.json
# `error_code` enum, minus null). Enforced at the transition boundary (defence in
# depth) AND by the persistence-layer schema validation (the backstop).
ERROR_CODES = frozenset(
    {"execution_timeout", "upstream_unavailable", "rate_limited", "internal_error"}
)

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

    def to_storage_dict(self) -> dict[str, Any]:
        """Emit the FAITHFUL raw dataclass field values (no per-state nulling).

        Unlike ``to_record_dict`` (which PROJECTS the nullable fields per state for the
        poll/schema-shape view), this dumps exactly what is stored, including ``version``
        and the raw lease/ref/error fields. The persistence layer validates THIS dict
        against the schema's state-dependent invariants BEFORE writing, so a record that
        violates them (e.g. a terminal record still carrying a raw request_ref, or a
        received record with a raw lease) is rejected at persistence rather than silently
        normalised away. The raw job_token is never part of this dict — only the digest."""
        return asdict(self)

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


# --- Schema-enforced persistence boundary -------------------------------------


class InvalidRecord(Exception):
    """A record violates the hosted-job-record schema's state invariants and must NOT be
    persisted (e.g. a terminal record still carrying a raw request_ref, a received record
    with a raw lease/result/error, an error_code outside the enum, or a malformed
    timestamp). Raised by the persistence layer (create/cas_update) on the FAITHFUL
    serialization, so the durable record can never drift from the schema."""


class JobAlreadyExists(Exception):
    """A ``create`` was issued for a job_id that already exists in the store.

    ``create`` is the v0-genesis / one-winner boundary: a record is created EXACTLY ONCE and
    thereafter advanced only by the monotonic version-CAS. A second create for an existing
    job_id must NOT silently overwrite/reset state/token/refs/counters/version to 0 — it is
    rejected. Both backends raise this SAME type: the in-memory store checks existence under
    its lock; the SQLite store maps the primary-key ``sqlite3.IntegrityError`` onto it, so the
    one-winner create boundary is identical across backends (Blocker 3)."""


# The hosted-job-record schema is shipped AS PACKAGE DATA (services/openva_match_service/
# openva_match_service/schemas/hosted-job-record.schema.json) and loaded via
# importlib.resources, NOT a repo-layout ``parents[N]`` path. The repo path is absent from
# the built wheel / Docker image, so a path-based load would crash the persistence
# validation in the packaged service; the packaged copy is kept byte-identical to the
# canonical schemas/openva/hosted-job-record.schema.json by a drift-lock test.
_PACKAGED_SCHEMA_RESOURCE = "schemas/hosted-job-record.schema.json"


def load_packaged_schema() -> dict[str, Any]:
    """Load the packaged hosted-job-record schema via importlib.resources.

    Resolves the schema from the INSTALLED package (``openva_match_service`` package data),
    so it works from a wheel / Docker image with no repository ``schemas/`` tree on disk.
    Returns the parsed JSON document."""
    text = (
        importlib.resources.files("openva_match_service")
        .joinpath(_PACKAGED_SCHEMA_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


@lru_cache(maxsize=1)
def _record_validator() -> jsonschema.protocols.Validator:
    """Build (once) a format-checking validator for the hosted-job-record schema.

    Cached so the schema file is read and compiled a single time per process. The
    persistence layer validates the FAITHFUL (``to_storage_dict``) record against this
    BEFORE every write. The schema is loaded from the PACKAGED copy via importlib.resources
    so the validation is installable in the wheel / Docker image (Blocker 1)."""
    return jsonschema.Draft202012Validator(
        load_packaged_schema(), format_checker=jsonschema.FormatChecker()
    )


def validate_record_for_persistence(record: JobRecord) -> None:
    """Validate the record's FAITHFUL serialization against the schema's state invariants.

    Raises ``InvalidRecord`` (wrapping the first jsonschema error message) when the raw
    record would violate the schema — so the persistence boundary is FAITHFUL (it rejects
    the bad record) rather than relying on the projected ``to_record_dict`` to hide the
    violation. Called inside every backend's ``create`` and ``cas_update`` before writing.

    A malformed ``date-time`` field is rejected DETERMINISTICALLY here even though the
    jsonschema ``date-time`` format check is a no-op without the optional rfc3339-validator
    package — regulatory-grade determinism must not depend on an optional dependency being
    installed, so the timestamp fields are explicitly parsed as a backstop."""
    errors = sorted(_record_validator().iter_errors(record.to_storage_dict()), key=str)
    if errors:
        raise InvalidRecord(
            f"job {record.job_id} violates the hosted-job-record schema: {errors[0].message}"
        )
    # Deterministic timestamp backstop (the schema's date-time format check is advisory).
    for field, value in (
        ("created_at", record.created_at),
        ("updated_at", record.updated_at),
        ("expires_at", record.expires_at),
        ("lease_expires_at", record.lease_expires_at),
    ):
        if value is None:
            continue
        try:
            _parse_iso_z(value)
        except (ValueError, TypeError) as exc:
            raise InvalidRecord(
                f"job {record.job_id} has a malformed {field}: {value!r}"
            ) from exc


def _require_create_version(record: JobRecord) -> None:
    """Reject a ``create`` whose record version is not 0 (Blocker 2).

    ``create`` is the version-0 genesis of a record; the version is only ever advanced by a
    monotonic single-step CAS thereafter. Accepting an arbitrary version on create would let
    a caller forge a record at a chosen version and slip past the one-winner CAS invariant."""
    if record.version != 0:
        raise InvalidRecord(
            f"job {record.job_id} must be created at version 0, not {record.version}"
        )


def _require_monotonic_cas(record: JobRecord, expected_version: int) -> None:
    """Reject a CAS candidate that does not advance the version by EXACTLY one (Blocker 2).

    Enforced at the persistence boundary in BOTH backends BEFORE the stored-version guard, so
    a write that leaves the version unchanged, decreases it, or skips a generation is rejected
    even when the stored version still equals ``expected_version``. Combined with the existing
    stored-version guard (in-memory ``stored.version == expected_version`` / SQLite
    ``WHERE version = expected_version``), this makes the version a strictly monotonic,
    one-winner-per-generation counter: of two writers at the same expected_version, at most one
    can land, and every landed write moves the version forward by one and only one step."""
    if record.version != expected_version + 1:
        raise InvalidRecord(
            f"job {record.job_id} CAS must advance the version to {expected_version + 1} "
            f"(expected_version {expected_version} + 1), not {record.version}"
        )


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
        # A reentrant lock makes the read-check-write of cas_update atomic across threads,
        # so exactly one of two concurrent cas_update calls at the same expected_version
        # wins (mirroring the SQLite backend's WHERE version=? + rowcount semantics). All
        # public methods take it so a sweep/enumeration never observes a torn write.
        self._lock = threading.RLock()

    def create(self, record: JobRecord) -> None:
        # A newly created record MUST start at version 0 — the version is a monotonic,
        # CAS-advanced counter and create is the v0 genesis. A non-zero version on create
        # would let a caller forge a record at an arbitrary version and defeat the
        # one-winner CAS invariant (Blocker 2).
        _require_create_version(record)
        # Reject a schema-invalid record at the persistence boundary BEFORE storing it
        # (the durable record can never drift from the schema's state invariants —
        # terminal w/ request_ref, received w/ lease, bad error_code, malformed timestamp).
        validate_record_for_persistence(record)
        with self._lock:
            # One-winner create boundary (Blocker 3): a create for an already-existing job_id
            # must NOT silently reset the stored record to v0. The existence check + insert
            # are done ATOMICALLY under the lock so two concurrent creates for the same
            # job_id cannot both insert — exactly one wins, the rest raise JobAlreadyExists.
            # SQLite rejects the equivalent via its primary key (IntegrityError -> the SAME
            # JobAlreadyExists), so the backends are consistent.
            if record.job_id in self._records:
                raise JobAlreadyExists(
                    f"job {record.job_id} already exists; create is the v0 genesis "
                    "and must not overwrite an existing record"
                )
            # Store a snapshot copy so the caller's reference cannot mutate the stored
            # record without going through cas_update (mirrors a durable backend, where
            # the in-process object is never the stored row).
            self._records[record.job_id] = replace(record)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            stored = self._records.get(job_id)
            # Hand back a fresh copy so mutations by the caller do not retroactively
            # change the stored row except through cas_update (the version-CAS gate).
            return replace(stored) if stored is not None else None

    def cas_update(self, record: JobRecord, expected_version: int) -> bool:
        # MONOTONIC one-winner guard (Blocker 2): the candidate MUST advance the version by
        # EXACTLY one past expected_version, BEFORE the stored-version CAS. A write that does
        # not advance the version by exactly one (unchanged / decreased / skipped) is rejected
        # even if the stored version still matches expected_version — so a malformed candidate
        # can never bypass the monotonic single-step invariant via a matching stored version.
        _require_monotonic_cas(record, expected_version)
        # Validate OUTSIDE the lock (pure function of the record) to keep the critical
        # section to the read-check-write; an invalid record is rejected regardless of
        # the CAS outcome.
        validate_record_for_persistence(record)
        with self._lock:
            stored = self._records.get(record.job_id)
            if stored is None or stored.version != expected_version:
                return False
            self._records[record.job_id] = replace(record)
            return True

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for record in self._records.values() if not record.is_terminal())

    def iter_records(self) -> list[JobRecord]:
        with self._lock:
            return [replace(record) for record in self._records.values()]

    def expired_request_refs(self, now: datetime) -> list[str]:
        with self._lock:
            return [
                record.request_ref
                for record in self._records.values()
                if record.request_ref is not None and now >= _parse_iso_z(record.expires_at)
            ]

    def purge_expired(self, now: datetime, retained_window: timedelta) -> list[JobRecord]:
        with self._lock:
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
    def put(self, ref: str, envelope: Any, expires_at: str) -> None:
        """Store ``envelope`` under ``ref`` with an ISO-8601 Z ``expires_at``.

        The blob carries its OWN expiry so it is lifecycle-addressable independently of any
        surviving job record: ``purge_expired`` reaps it even when no record references it
        (the after-envelope-before-job and skipped-delete crash points)."""
        ...

    @abstractmethod
    def get(self, ref: str) -> Any | None: ...

    @abstractmethod
    def delete(self, ref: str) -> None: ...

    @abstractmethod
    def purge_expired(self, now: datetime) -> list[str]:
        """Delete and return every ref whose ``expires_at <= now``, INDEPENDENT of any job
        record. This is the orphan-blob backstop: a blob written before its job record (or
        whose record-pointer delete was skipped) is still reaped by its own expiry."""
        ...


class InMemoryRequestEnvelopeStore(RequestEnvelopeStore):
    """In-memory, NON-DURABLE, transient request-envelope store. A durable reference
    backend (SQLite) is in ``sqlite_stores.py``; production encryption-at-rest is a
    deployment/infra concern (WP-02F/G)."""

    def __init__(self) -> None:
        # ref -> (value, expires_at). The lock makes put/get/delete/purge_expired atomic
        # across threads (Blocker 5), matching the durable backend's single-writer file lock.
        self._envelopes: dict[str, tuple[Any, str]] = {}
        self._lock = threading.RLock()

    def put(self, ref: str, envelope: Any, expires_at: str) -> None:
        # Reject + normalize the blob expiry BEFORE storage (Blocker 4) so a malformed/naive
        # value can never persist and later abort a purge sweep. Store the normalized string.
        normalized = _validate_blob_expires_at(expires_at)
        with self._lock:
            self._envelopes[ref] = (envelope, normalized)

    def get(self, ref: str) -> Any | None:
        with self._lock:
            entry = self._envelopes.get(ref)
            return entry[0] if entry is not None else None

    def delete(self, ref: str) -> None:
        with self._lock:
            self._envelopes.pop(ref, None)

    def purge_expired(self, now: datetime) -> list[str]:
        with self._lock:
            reaped = [
                ref
                for ref, (_value, expires_at) in self._envelopes.items()
                if _parse_iso_z(expires_at) <= now
            ]
            for ref in reaped:
                del self._envelopes[ref]
            return reaped


class ResultStore(ABC):
    """Transient result-blob store interface (keyed by result_ref). WP-02B swaps a
    durable/TTL backend behind this interface."""

    @abstractmethod
    def put(self, ref: str, result: Any, expires_at: str) -> None:
        """Store ``result`` under ``ref`` with an ISO-8601 Z ``expires_at``.

        Like the envelope store, the result blob carries its OWN expiry so it can be reaped
        independently of the terminal job record that references it (the result-written-
        before-the-terminal-CAS crash point)."""
        ...

    @abstractmethod
    def get(self, ref: str) -> Any | None: ...

    @abstractmethod
    def delete(self, ref: str) -> None: ...

    @abstractmethod
    def purge_expired(self, now: datetime) -> list[str]:
        """Delete and return every ref whose ``expires_at <= now``, INDEPENDENT of any job
        record (orphan-result backstop)."""
        ...


class InMemoryResultStore(ResultStore):
    """In-memory, NON-DURABLE, transient result-blob store. The durable, TTL
    backend is WP-02B."""

    def __init__(self) -> None:
        # ref -> (value, expires_at); lock makes the operations atomic across threads.
        self._results: dict[str, tuple[Any, str]] = {}
        self._lock = threading.RLock()

    def put(self, ref: str, result: Any, expires_at: str) -> None:
        # Reject + normalize the blob expiry BEFORE storage (Blocker 4) so a malformed/naive
        # value can never persist and later abort a purge sweep. Store the normalized string.
        normalized = _validate_blob_expires_at(expires_at)
        with self._lock:
            self._results[ref] = (result, normalized)

    def get(self, ref: str) -> Any | None:
        with self._lock:
            entry = self._results.get(ref)
            return entry[0] if entry is not None else None

    def delete(self, ref: str) -> None:
        with self._lock:
            self._results.pop(ref, None)

    def purge_expired(self, now: datetime) -> list[str]:
        with self._lock:
            reaped = [
                ref
                for ref, (_value, expires_at) in self._results.items()
                if _parse_iso_z(expires_at) <= now
            ]
            for ref in reaped:
                del self._results[ref]
            return reaped


# --- Expiry / purge coordination ----------------------------------------------


def _parse_iso_z(value: str) -> datetime:
    """Parse a STRICT, timezone-aware ISO-8601 timestamp and normalize it to UTC.

    Local to the transport so the job store can decide its own retained-window
    physical-deletion boundary without importing the route layer.

    STRICTNESS (Blocker 4): the value MUST carry an explicit UTC designator (``Z``) or a
    numeric UTC offset. A NAIVE timestamp (``2026-06-22T12:00:00``) or a DATE-ONLY value
    (``2026-06-22``) is rejected with ``ValueError`` — a naive value would otherwise persist
    and then raise ``TypeError`` when compared against the tz-aware ``now``, a latent
    determinism/integrity bug. ``datetime.fromisoformat`` is lenient (it accepts naive and
    date-only inputs), so the result's ``tzinfo`` is checked explicitly and any non-UTC
    offset is converted to UTC. Produced timestamps from ``_iso_z`` always carry ``Z``, so
    this only ever rejects bad INPUT, never our own serialization."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(
            f"timestamp {value!r} must be timezone-aware (explicit Z or UTC offset)"
        )
    # Normalize any valid offset (e.g. +05:00) to UTC so all downstream comparisons are
    # against a single canonical zone.
    return parsed.astimezone(timezone.utc)


def _validate_blob_expires_at(expires_at: str) -> str:
    """Validate + NORMALIZE a transient-blob ``expires_at`` at PUT time (Blocker 4).

    The envelope/result blobs carry their own ``expires_at`` so the purge paths can reap
    them by it (via the strict ``_parse_iso_z``). A malformed/naive/date-only value that
    slipped into storage would later RAISE inside ``purge_expired`` and abort the whole sweep,
    stranding other expired blobs. So a bad expiry is rejected (``InvalidRecord``) BEFORE
    storage; the returned value is the parsed instant re-rendered as a canonical UTC ``...Z``
    string (a non-UTC offset such as ``+05:00`` is accepted and normalized to UTC), so every
    stored blob expiry is uniform and purge-safe."""
    try:
        parsed = _parse_iso_z(expires_at)
    except (ValueError, TypeError) as exc:
        raise InvalidRecord(
            f"blob expires_at {expires_at!r} must be a timezone-aware ISO-8601 timestamp"
        ) from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    job_ids physically deleted in phase 3.

    ORPHAN SWEEP (Blocker 1): the blob stores are reaped by their OWN ``expires_at`` too,
    independent of any surviving job record. This reaps the crash-window orphans the
    record-driven deletes above can never reach: an envelope written before its job record
    was created; a result written before the terminal CAS referenced it; an envelope whose
    in-record pointer was cleared but whose physical delete was skipped. Each blob carries
    its expiry, so this runs regardless of whether a record points at it."""
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
    # Orphan sweep: reap any envelope/result blob past its own expires_at, even with no
    # referencing record (the create-before-record and skipped-delete crash points).
    envelopes.purge_expired(now)
    results.purge_expired(now)
    return [record.job_id for record in purged]


# --- Identifier helpers -------------------------------------------------------


def new_job_id() -> str:
    """Server-generated opaque correlation id (UUID4). Loggable; NOT a credential."""
    return str(uuid.uuid4())


def new_ref() -> str:
    """Opaque pointer for the transient envelope/result stores."""
    return uuid.uuid4().hex
