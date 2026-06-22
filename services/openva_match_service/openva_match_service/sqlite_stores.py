"""Durable (stdlib sqlite3) reference backends for the verify transport (WP-02B).

These implement the SAME ABCs as the in-memory stores in ``verify_transport`` —
``SqliteJobStore`` / ``SqliteRequestEnvelopeStore`` / ``SqliteResultStore`` — backed by
a single SQLite database file (from config), so state survives a process restart. They
satisfy the identical interface + optimistic-concurrency (version-CAS) semantics as the
in-memory stores: the job store persists ``version`` and CAS is
``UPDATE ... WHERE job_id=? AND version=?`` with a rowcount check.

Encryption-at-rest NOTE: production encryption-at-rest is provided by the DEPLOYMENT's
managed storage (a provider/infra concern, WP-02F/G — e.g. the managed database /
object-store native encryption). This SQLite implementation is the REFERENCE DURABLE
backend that demonstrates the interface + the CAS lifecycle semantics; it is NOT the
production store and does NOT itself encrypt the database file. It is deliberately NOT
wired as the app default (the in-memory store remains the default); it is selectable but
optional.

Like the in-memory stores, the envelope/result blobs are TRANSIENT: the three-phase TTL
purge (``verify_transport.purge_expired_jobs``) and the terminal/abandonment deletes are
what minimise the stored submitted input; this backend just persists durably between
those events.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .verify_transport import (
    JobRecord,
    JobStore,
    RequestEnvelopeStore,
    ResultStore,
    _parse_iso_z,
    validate_record_for_persistence,
)

# Columns persisted for a job record, in JobRecord field order (version included).
_JOB_COLUMNS = (
    "job_id",
    "job_token_digest",
    "state",
    "request_ref",
    "row_count",
    "created_at",
    "updated_at",
    "expires_at",
    "schema_version",
    "freshness_mode",
    "result_ref",
    "error_code",
    "attempt",
    "dispatch_attempt",
    "lease_owner",
    "lease_expires_at",
    "version",
    "not_advice",
)


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with row access by name and FK/now-friendly settings.

    ``check_same_thread=False`` so a single connection can back the app across the
    threadpool the FastAPI sync deps run on; writes are short and serialized by SQLite's
    file lock. The reference backend favours correctness/clarity over throughput."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=row["job_id"],
        job_token_digest=row["job_token_digest"],
        state=row["state"],
        request_ref=row["request_ref"],
        row_count=row["row_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
        schema_version=row["schema_version"],
        freshness_mode=row["freshness_mode"],
        result_ref=row["result_ref"],
        error_code=row["error_code"],
        attempt=row["attempt"],
        dispatch_attempt=row["dispatch_attempt"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        version=row["version"],
        not_advice=bool(row["not_advice"]),
    )


def _record_values(record: JobRecord) -> tuple[Any, ...]:
    return (
        record.job_id,
        record.job_token_digest,
        record.state,
        record.request_ref,
        record.row_count,
        record.created_at,
        record.updated_at,
        record.expires_at,
        record.schema_version,
        record.freshness_mode,
        record.result_ref,
        record.error_code,
        record.attempt,
        record.dispatch_attempt,
        record.lease_owner,
        record.lease_expires_at,
        record.version,
        1 if record.not_advice else 0,
    )


class SqliteJobStore(JobStore):
    """Durable job store (stdlib sqlite3). Persists ``version`` and realizes the
    version-CAS as ``UPDATE ... WHERE job_id=? AND version=?`` + rowcount check."""

    def __init__(self, db_path: str) -> None:
        self._conn = _connect(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        columns = ", ".join(f"{name}" for name in _JOB_COLUMNS)
        # job_id is the primary key; version is a plain integer column used by the CAS.
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS jobs ({columns}, PRIMARY KEY (job_id))"
        )
        self._conn.commit()

    def create(self, record: JobRecord) -> None:
        # Reject a schema-invalid record at the persistence boundary BEFORE writing
        # (Blocker 4: same faithful schema check as the in-memory backend).
        validate_record_for_persistence(record)
        placeholders = ", ".join("?" for _ in _JOB_COLUMNS)
        columns = ", ".join(_JOB_COLUMNS)
        self._conn.execute(
            f"INSERT INTO jobs ({columns}) VALUES ({placeholders})",
            _record_values(record),
        )
        self._conn.commit()

    def get(self, job_id: str) -> JobRecord | None:
        cur = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        return _row_to_record(row) if row is not None else None

    def cas_update(self, record: JobRecord, expected_version: int) -> bool:
        # Reject a schema-invalid record before the version-guarded write (Blocker 4).
        validate_record_for_persistence(record)
        # The version-guarded write: only the row whose stored version equals the value
        # the caller read is updated. rowcount == 1 means the CAS won; 0 means a
        # concurrent writer advanced the version and the actor must re-read.
        assignments = ", ".join(f"{name} = ?" for name in _JOB_COLUMNS)
        values = _record_values(record) + (record.job_id, expected_version)
        cur = self._conn.execute(
            f"UPDATE jobs SET {assignments} WHERE job_id = ? AND version = ?",
            values,
        )
        self._conn.commit()
        return cur.rowcount == 1

    def active_count(self) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE state NOT IN ('completed', 'failed')"
        )
        return int(cur.fetchone()["n"])

    def iter_records(self) -> list[JobRecord]:
        cur = self._conn.execute("SELECT * FROM jobs")
        return [_row_to_record(row) for row in cur.fetchall()]

    def expired_request_refs(self, now: datetime) -> list[str]:
        refs: list[str] = []
        for row in self._conn.execute(
            "SELECT request_ref, expires_at FROM jobs WHERE request_ref IS NOT NULL"
        ).fetchall():
            if now >= _parse_iso_z(row["expires_at"]):
                refs.append(row["request_ref"])
        return refs

    def purge_expired(self, now: datetime, retained_window: timedelta) -> list[JobRecord]:
        purged: list[JobRecord] = []
        for record in self.iter_records():
            if now >= _parse_iso_z(record.expires_at) + retained_window:
                self._conn.execute("DELETE FROM jobs WHERE job_id = ?", (record.job_id,))
                purged.append(record)
        if purged:
            self._conn.commit()
        return purged

    def close(self) -> None:  # pragma: no cover - lifecycle convenience
        self._conn.close()


class _SqliteBlobStore:
    """Shared durable key->JSON-blob store for the transient envelope/result stores.

    The value is JSON-serialised on put and parsed on get; deleting an absent key is a
    no-op (idempotent), matching the in-memory stores and the TTL purge's expectations.
    Each blob persists its OWN ``expires_at`` (an ISO-8601 Z string) so it is
    lifecycle-addressable independently of any job record: ``purge_expired`` reaps every
    blob past its expiry regardless of whether a record still points at it (Blocker 1)."""

    _TABLE = "blobs"

    def __init__(self, db_path: str, table: str) -> None:
        self._conn = _connect(db_path)
        self._TABLE = table
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._TABLE} "
            f"(ref TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def put(self, ref: str, value: Any, expires_at: str) -> None:
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self._TABLE} (ref, payload, expires_at) VALUES (?, ?, ?)",
            (ref, json.dumps(value), expires_at),
        )
        self._conn.commit()

    def get(self, ref: str) -> Any | None:
        cur = self._conn.execute(
            f"SELECT payload FROM {self._TABLE} WHERE ref = ?", (ref,)
        )
        row = cur.fetchone()
        return json.loads(row["payload"]) if row is not None else None

    def delete(self, ref: str) -> None:
        self._conn.execute(f"DELETE FROM {self._TABLE} WHERE ref = ?", (ref,))
        self._conn.commit()

    def purge_expired(self, now: datetime) -> list[str]:
        # Reap every blob whose expires_at <= now, independent of any job record. Compare
        # in Python (via _parse_iso_z) so mixed Z/offset suffixes are handled consistently
        # with the in-memory backend rather than relying on lexical SQL string comparison.
        reaped = [
            row["ref"]
            for row in self._conn.execute(
                f"SELECT ref, expires_at FROM {self._TABLE}"
            ).fetchall()
            if _parse_iso_z(row["expires_at"]) <= now
        ]
        for ref in reaped:
            self._conn.execute(f"DELETE FROM {self._TABLE} WHERE ref = ?", (ref,))
        if reaped:
            self._conn.commit()
        return reaped

    def close(self) -> None:  # pragma: no cover - lifecycle convenience
        self._conn.close()


class SqliteRequestEnvelopeStore(RequestEnvelopeStore):
    """Durable (sqlite3) transient request-envelope store. Persists the submitted verify
    rows so the worker (WP-02C) can read them; minimisation is the three-phase TTL delete
    + terminal delete + deployment-managed encryption-at-rest (NOT this file)."""

    def __init__(self, db_path: str) -> None:
        self._store = _SqliteBlobStore(db_path, "request_envelopes")

    def put(self, ref: str, envelope: Any, expires_at: str) -> None:
        self._store.put(ref, envelope, expires_at)

    def get(self, ref: str) -> Any | None:
        return self._store.get(ref)

    def delete(self, ref: str) -> None:
        self._store.delete(ref)

    def purge_expired(self, now: datetime) -> list[str]:
        return self._store.purge_expired(now)

    def close(self) -> None:  # pragma: no cover - lifecycle convenience
        self._store.close()


class SqliteResultStore(ResultStore):
    """Durable (sqlite3) transient result-blob store. TTL-deleted by the three-phase
    purge, exactly like the in-memory result store."""

    def __init__(self, db_path: str) -> None:
        self._store = _SqliteBlobStore(db_path, "result_blobs")

    def put(self, ref: str, result: Any, expires_at: str) -> None:
        self._store.put(ref, result, expires_at)

    def get(self, ref: str) -> Any | None:
        return self._store.get(ref)

    def delete(self, ref: str) -> None:
        self._store.delete(ref)

    def purge_expired(self, now: datetime) -> list[str]:
        return self._store.purge_expired(now)

    def close(self) -> None:  # pragma: no cover - lifecycle convenience
        self._store.close()
