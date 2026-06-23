"""Synchronous ``/v1/check`` live-verify-or-cached resolution (WP-02J).

``/v1/check`` is the public live verify MODE over ``/v1``. It returns a vendor-resolution
check that EXPLICITLY LABELS each row's freshness as ``cached`` vs ``verify`` so a
consumer always knows whether the answer came from the static cached snapshot or a live
verification.

Design (provider-neutral application code only; OFF by default for the live path):

  - The CACHED answer is ALWAYS available. It reuses the existing cached match path
    (``enrichment.match_one`` + ``enrichment.vendor_sources``) — the same authority the
    cached ``/v1/match`` / ``/v1/enrich`` endpoints use — and is labelled ``cached``.

  - The LIVE-verify augmentation runs ONLY when ALL of: the verify transport is enabled,
    the kill-switch is NOT armed, AND a verify runner (worker over the existing TTL stores)
    is wired on app state. It drives the EXISTING async ``/v1/verify`` transport + worker
    over the EXISTING TTL job/result store — no new persistence — synchronously: create a
    job record + transient envelope (carrying identities so the worker can resolve), drive
    the worker once, read the result blob, then let the lifecycle reap it. Each verified row
    is labelled ``verify`` and carries the live ``verification`` payload.

  - Otherwise the endpoint DEGRADES HONESTLY to the cached answer, clearly labelled
    ``cached`` — it never presents stale cached data as a live result.

SSRF boundary: the endpoint takes vendor IDENTITIES only (no fetch-target URL — enforced
structurally by ``CheckRowItem``'s ``extra="forbid"``). The live path forwards identities
to the worker, which always fetches through the SSRF-safe resolver boundary; the caller can
never supply a fetch target.

Non-advisory: every row carries ``not_advice: true``; no scoring/ranking/verdict is added.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .config import VERIFY_RETAINED_WINDOW_HOURS, ServiceConfig
from .enrichment import match_one, vendor_sources
from .models import FRESHNESS_CACHED, FRESHNESS_VERIFY
from .service_state import ServiceState
from .verify_transport import (
    JobRecord,
    new_job_id,
    new_job_token,
    new_ref,
    purge_expired_jobs,
    token_digest,
)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class VerifyRunner(Protocol):
    """The synchronous live-verify driver wired on app state ONLY when the live path is
    explicitly opted in (off by default — ``create_app`` constructs none). It owns the
    existing TTL stores + the existing async worker/queue, so ``/check`` reuses the
    EXISTING verify transport rather than forking a parallel one."""

    def run(self, rows: list[dict[str, Any]], source_types: list[str] | None) -> dict[Any, dict[str, Any]]:
        """Verify the given identity rows synchronously over the existing transport.

        Returns a mapping of ``row_id -> live verification payload`` for the rows that were
        successfully verified. A row absent from the mapping degrades honestly to cached."""
        ...


@dataclass
class TransportVerifyRunner:
    """A synchronous ``VerifyRunner`` over the EXISTING verify transport + worker.

    It creates a job record + transient request envelope in the EXISTING TTL stores
    (no new persistence), enqueues it, drives the EXISTING worker once, reads the result
    blob back, and reaps the job — all over the same stores the async ``/v1/verify``
    endpoints use. The worker resolves through the SSRF-safe boundary (identities only).
    Constructed only by a deployment/test that opts into the live path; never by
    ``create_app`` (so the default build has no runner and ``/check`` serves cached only)."""

    jobs: Any
    envelopes: Any
    results: Any
    queue: Any
    worker: Any
    config: ServiceConfig

    def run(self, rows: list[dict[str, Any]], source_types: list[str] | None) -> dict[Any, dict[str, Any]]:
        now = datetime.now(timezone.utc)
        # Opportunistically reap any expired job/blob before and after, so the transient
        # job/result this synchronous check creates is bounded by the existing TTL store.
        purge_expired_jobs(
            self.jobs, self.envelopes, self.results, now,
            timedelta(hours=VERIFY_RETAINED_WINDOW_HOURS),
        )

        job_id = new_job_id()
        token = new_job_token()
        request_ref = new_ref()
        expires_at = _iso_z(now + timedelta(hours=self.config.job_ttl_hours))
        # The envelope carries the IDENTITY rows so the worker can resolve them through the
        # SSRF-safe boundary. It is reaped by the existing TTL purge (no new persistence).
        envelope: dict[str, Any] = {"row_count": len(rows), "rows": rows}
        if source_types:
            envelope["source_types"] = list(source_types)
        self.envelopes.put(request_ref, envelope, expires_at)
        record = JobRecord(
            job_id=job_id,
            job_token_digest=token_digest(token),
            state="received",
            request_ref=request_ref,
            row_count=len(rows),
            created_at=_iso_z(now),
            updated_at=_iso_z(now),
            expires_at=expires_at,
        )
        self.jobs.create(record)
        # Enqueue (generation 0) + drive the existing worker synchronously. The worker
        # terminalizes the job (executing -> completed) and writes the result blob.
        self.queue.enqueue(job_id, dispatch_attempt=0)
        self.worker.run_once(max_deliveries=1)

        verified: dict[Any, dict[str, Any]] = {}
        final = self.jobs.get(job_id)
        if final is not None and final.state == "completed" and final.result_ref is not None:
            payload = self.results.get(final.result_ref)
            if isinstance(payload, dict):
                for row in payload.get("rows", []) or []:
                    if isinstance(row, dict):
                        verified[row.get("row_id")] = row
        # Reap the transient job/result now that we have read it back (its own TTL is the
        # backstop; this keeps the synchronous check from leaving state behind).
        purge_expired_jobs(
            self.jobs, self.envelopes, self.results,
            datetime.now(timezone.utc) + timedelta(hours=self.config.job_ttl_hours + VERIFY_RETAINED_WINDOW_HOURS + 1),
            timedelta(hours=VERIFY_RETAINED_WINDOW_HOURS),
        )
        return verified


# Identity fields forwarded to the live runner; NOTHING else (never a url) is forwarded —
# the resolver chooses what to fetch (the SSRF + transient-input boundary).
_IDENTITY_FIELDS = ("vendor_name", "domain", "business_entity_name", "registration_number")


def _cached_row(
    state: ServiceState,
    item_input: dict[str, Any],
    source_types: list[str] | None,
    *,
    freshness: str,
    verification: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one row's CACHED projection (match + canonical sources), labelled ``freshness``.

    The cached match is ALWAYS computed (the cached answer is always available); when
    ``freshness == verify`` the live ``verification`` payload is attached alongside it."""
    match = match_one(
        state,
        vendor_name=item_input.get("vendor_name"),
        domain=item_input.get("domain"),
        business_entity_name=item_input.get("business_entity_name"),
        registration_number=item_input.get("registration_number"),
    )
    vendor_id = match.get("vendor_id")
    if vendor_id:
        sources, _primary, _urls = vendor_sources(state, vendor_id, source_types)
    else:
        sources = []
    return {
        "row_id": item_input.get("row_id"),
        "input": {field: item_input.get(field) for field in _IDENTITY_FIELDS},
        "freshness": freshness,
        "match": match,
        "sources": sources,
        "verification": verification,
        "not_advice": True,
    }


def run_check(
    state: ServiceState,
    config: ServiceConfig,
    rows: list[dict[str, Any]],
    source_types: list[str] | None,
    *,
    runner: VerifyRunner | None,
) -> dict[str, Any]:
    """Resolve a bounded batch of identity rows, labelling each ``cached`` vs ``verify``.

    The cached answer is ALWAYS produced. When ``runner`` is present (the live path is
    enabled, not kill-switched, and a worker is wired) each row that the runner verifies is
    labelled ``verify`` and carries the live verification; rows the runner could not verify
    degrade HONESTLY to ``cached``. When ``runner`` is None the whole batch is ``cached``."""
    verified: dict[Any, dict[str, Any]] = {}
    if runner is not None:
        identity_rows = [
            {**{field: row.get(field) for field in _IDENTITY_FIELDS}, "row_id": row.get("row_id")}
            for row in rows
        ]
        try:
            verified = runner.run(identity_rows, source_types)
        except Exception:  # noqa: BLE001 - any live-path failure degrades honestly to cached
            verified = {}

    results: list[dict[str, Any]] = []
    any_verified = False
    for row in rows:
        row_id = row.get("row_id")
        live = verified.get(row_id) if verified else None
        if live is not None:
            any_verified = True
            results.append(
                _cached_row(state, row, source_types, freshness=FRESHNESS_VERIFY, verification=live)
            )
        else:
            results.append(
                _cached_row(state, row, source_types, freshness=FRESHNESS_CACHED, verification=None)
            )

    return {
        "results": results,
        "freshness_mode": FRESHNESS_VERIFY if any_verified else FRESHNESS_CACHED,
        "verify_enabled": runner is not None,
    }
