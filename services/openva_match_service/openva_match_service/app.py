from __future__ import annotations

import re
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .adapter_paths import ensure_adapter_paths

ensure_adapter_paths()

from .config import ADVISORY_BOUNDARY, VERIFY_RETAINED_WINDOW_HOURS, ServiceConfig  # noqa: E402
from .conversion import match_csv_bytes  # noqa: E402
from .enrichment import build_snapshot, enrich_one, match_one, vendor_detail, vendor_sources  # noqa: E402
from .models import (  # noqa: E402
    CatalogMetaResponse,
    EnrichRequest,
    EnrichResponse,
    MatchInput,
    MatchResponse,
    VendorDetailResponse,
    VendorSourcesResponse,
    VerifyCreatedResponse,
    VerifyRequest,
    VerifyStatusResponse,
)
from .hardening import (  # noqa: E402
    ConcurrencyLimiter,
    RateLimitPolicy,
    client_key,
)
from .queue import InMemoryQueue  # noqa: E402
from .service_state import ServiceState, load_service_state  # noqa: E402
from .telemetry import NullTelemetry, Telemetry  # noqa: E402
from .verify_transport import (  # noqa: E402
    InMemoryJobStore,
    InMemoryRequestEnvelopeStore,
    InMemoryResultStore,
    JobRecord,
    _parse_iso_z,
    extract_bearer_token,
    digests_match,
    new_job_id,
    new_job_token,
    new_ref,
    purge_expired_jobs,
    token_digest,
)

HEADER_SERVICE_VERSION = "X-OpenVA-Service-Version"
HEADER_PACK_PROFILE = "X-OpenVA-Pack-Profile"
HEADER_PACK_SCHEMA_VERSION = "X-OpenVA-Pack-Schema-Version"
HEADER_PACK_GENERATED_AT = "X-OpenVA-Pack-Generated-At"
HEADER_ADVISORY_BOUNDARY = "X-OpenVA-Advisory-Boundary"

# Catalogue vendor ids are lowercase-kebab tokens; reject anything else (path-traversal
# attempts, spaces, slashes) consistently as not found.
VENDOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")

# A job_id is a canonical UUID. A non-UUID path param is never a real job and is
# treated as not-found (404, content-free) — never a 500, and the job_id is not a
# credential so 404 leaks nothing.
JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

V1_TAG = "v1"
V1_DESCRIPTION = (
    "Read-only, cached-pack catalogue enrichment for zero-install spreadsheet and "
    "document clients. Responses reflect the catalogue pack loaded at startup; no source "
    "is fetched or verified live during a request. Every response carries a snapshot "
    "identity and `not_advice: true`. Access requires the bearer API key unless "
    "OPENVA_PUBLIC_READ_ENABLED is set, in which case these read-only endpoints are public."
)


def create_app(
    config: ServiceConfig | None = None,
    *,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    service_config = config or ServiceConfig.from_env()
    # Telemetry is provider-neutral. The DEFAULT is the no-op sink so the default build
    # emits nothing and behaves exactly as before; a deployment (or a test) may inject the
    # in-memory/stdout impl. The always-on REDACTOR lives inside every Telemetry impl, so
    # no wiring can ever leak a prohibited field. A provider exporter is WP-02F/02G.
    service_telemetry: Telemetry = telemetry or NullTelemetry()
    # Application-layer abuse / cost controls (provider-neutral; off/generous by default).
    rate_limiter = RateLimitPolicy(
        capacity=service_config.rate_limit_capacity,
        refill_per_second=service_config.rate_limit_refill_per_second,
        enabled=service_config.rate_limit_enabled,
    )
    concurrency_limiter = ConcurrencyLimiter(service_config.verify_concurrency_limit)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = service_config
        app.state.telemetry = service_telemetry
        app.state.rate_limiter = rate_limiter
        app.state.verify_concurrency = concurrency_limiter
        app.state.service_state = load_service_state(str(service_config.pack_path))
        # In-memory, NON-DURABLE verify-transport stores (WP-02A), created ONLY when
        # the verify transport is enabled, so a flag-off deployment keeps exactly the
        # current cached-only service state (no extra app.state). The verify endpoints
        # 404 before reaching these when the flag is off. The durable backend is WP-02B.
        if service_config.verify_transport_enabled:
            app.state.verify_jobs = InMemoryJobStore()
            app.state.verify_envelopes = InMemoryRequestEnvelopeStore()
            app.state.verify_results = InMemoryResultStore()
            # WP-02C: the provider-neutral queue interface, created ONLY behind the verify
            # flag. The in-memory impl is faithful to the Cloud-Tasks dedup/tombstone
            # semantics the reconciler relies on; a real Cloud Tasks adapter is a later,
            # infra-gated slice. NO worker LOOP and NO network egress is started here — the
            # worker is constructed/driven explicitly (off by default); this only makes the
            # queue available so the API/reconciler can enqueue when wired in a later slice.
            app.state.verify_queue = InMemoryQueue()
        yield

    app = FastAPI(
        title="OpenVA Match Service",
        version=service_config.service_version,
        lifespan=lifespan,
        openapi_tags=[{"name": V1_TAG, "description": V1_DESCRIPTION}],
    )
    install_middleware_and_handlers(app)
    # Bound the request body at the ASGI boundary, before Pydantic parses it, so a single
    # huge JSON payload cannot exhaust memory regardless of row count (added before CORS
    # so CORS remains outermost and still annotates the 413 for browser clients).
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=service_config.max_request_bytes)
    # Browser clients (Sheets/Office task panes) are enabled per configured origin only.
    # An empty allow-list never becomes a wildcard; existing server-to-server clients are
    # unaffected. Credentialed cross-origin requests are not enabled.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(service_config.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # Liveness: the process is up. No auth, no pack dependency.
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        # Readiness: 200 only once the pack/matcher state is loaded; 503 otherwise.
        state = getattr(app.state, "service_state", None)
        status_code = 200 if state is not None else 503
        return JSONResponse(status_code=status_code, content={"status": "ready" if state is not None else "not_ready"})

    @app.get("/pack/meta")
    async def pack_meta(_: None = Depends(require_api_key)) -> dict[str, Any]:
        state = get_service_state(app)
        return asdict(state.meta)

    @app.post("/match")
    async def match(
        _: None = Depends(require_api_key),
        inventory_csv: UploadFile = File(...),
    ) -> dict[str, Any]:
        if inventory_csv.content_type not in {None, "", "text/csv", "application/vnd.ms-excel"}:
            raise HTTPException(status_code=400, detail="inventory_csv must be a CSV upload")
        # Bound the in-memory read so an oversized upload cannot exhaust memory
        # before matching (reads at most max_upload_bytes + 1 to detect overflow).
        data = await inventory_csv.read(service_config.max_upload_bytes + 1)
        if len(data) > service_config.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"inventory_csv exceeds the maximum of {service_config.max_upload_bytes} bytes",
            )
        state = get_service_state(app)
        try:
            rows = match_csv_bytes(data, state.matcher_index, max_rows=service_config.max_rows)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "meta": {
                **asdict(state.meta),
                "service_version": service_config.service_version,
                "advisory_boundary": ADVISORY_BOUNDARY,
            },
            "rows": rows,
        }

    @app.get(
        "/v1/catalog/meta",
        response_model=CatalogMetaResponse,
        tags=[V1_TAG],
        summary="Catalogue snapshot identity and manifest guarantees",
    )
    async def v1_catalog_meta(_: None = Depends(require_read_access)) -> dict[str, Any]:
        state = get_service_state(app)
        guarantees = state.guarantees or {}
        return {
            "snapshot": build_snapshot(state, service_config),
            "guarantees": {
                "public_sources_only": bool(guarantees.get("public_sources_only", False)),
                "metadata_first": bool(guarantees.get("metadata_first", False)),
                "non_advisory": bool(guarantees.get("non_advisory", False)),
                "raw_documents_mirrored_by_default": bool(guarantees.get("raw_documents_mirrored_by_default", False)),
            },
            "not_advice": True,
        }

    @app.get(
        "/v1/vendors/{vendor_id}",
        response_model=VendorDetailResponse,
        tags=[V1_TAG],
        summary="One vendor and its canonical public sources",
    )
    async def v1_vendor(vendor_id: str, _: None = Depends(require_read_access)) -> dict[str, Any]:
        state = get_service_state(app)
        # Decide "unknown vendor" only from the authoritative loaded vendor index. A
        # PackError after this point means pack corruption, not an unknown vendor, so it
        # is NOT converted to 404 — it propagates to the generic handler as a non-leaking
        # 500 rather than masquerading as an ordinary not-found.
        if not VENDOR_ID_RE.fullmatch(vendor_id) or vendor_id not in state.matcher_index.vendors_by_id:
            raise HTTPException(status_code=404, detail="vendor not found")
        detail = vendor_detail(state, vendor_id)
        return {**detail, "snapshot": build_snapshot(state, service_config), "not_advice": True}

    @app.get(
        "/v1/vendors/{vendor_id}/sources",
        response_model=VendorSourcesResponse,
        tags=[V1_TAG],
        summary="Canonical sources for a vendor, optionally filtered by source_type",
    )
    async def v1_vendor_sources(
        vendor_id: str,
        source_type: list[str] | None = Query(default=None, description="Repeatable. Omit for all canonical sources. Unknown types yield an empty filtered result."),
        _: None = Depends(require_read_access),
    ) -> dict[str, Any]:
        state = get_service_state(app)
        if not VENDOR_ID_RE.fullmatch(vendor_id) or vendor_id not in state.matcher_index.vendors_by_id:
            raise HTTPException(status_code=404, detail="vendor not found")
        sources, _primary, _urls = vendor_sources(state, vendor_id, source_type)
        return {
            "vendor_id": vendor_id,
            "sources": sources,
            "source_types_requested": source_type or [],
            "snapshot": build_snapshot(state, service_config),
            "not_advice": True,
        }

    @app.post(
        "/v1/match",
        response_model=MatchResponse,
        tags=[V1_TAG],
        summary="Resolve one vendor identity against the catalogue",
    )
    async def v1_match(payload: MatchInput, _: None = Depends(require_read_access)) -> dict[str, Any]:
        state = get_service_state(app)
        match = match_one(
            state,
            vendor_name=payload.vendor_name,
            domain=payload.domain,
            business_entity_name=payload.business_entity_name,
            registration_number=payload.registration_number,
        )
        return {
            "input": payload.model_dump(),
            "match": match,
            "snapshot": build_snapshot(state, service_config),
            "not_advice": True,
        }

    @app.post(
        "/v1/enrich",
        response_model=EnrichResponse,
        tags=[V1_TAG],
        summary="Enrich a bounded batch of vendor rows for spreadsheet/document clients",
    )
    async def v1_enrich(payload: EnrichRequest, _: None = Depends(require_read_access)) -> dict[str, Any]:
        state = get_service_state(app)
        if len(payload.vendors) > service_config.max_rows:
            raise HTTPException(
                status_code=413,
                detail=f"vendors exceeds the maximum of {service_config.max_rows} rows",
            )
        results = [
            enrich_one(
                state,
                row_id=item.row_id,
                vendor_name=item.vendor_name,
                domain=item.domain,
                business_entity_name=item.business_entity_name,
                registration_number=item.registration_number,
                source_types=payload.source_types,
            )
            for item in payload.vendors
        ]
        return {
            "results": results,
            "snapshot": build_snapshot(state, service_config),
            "not_advice": True,
        }

    @app.post(
        "/v1/verify",
        response_model=VerifyCreatedResponse,
        tags=[V1_TAG],
        summary="Create a hosted verify job (async transport; behind a flag, default off)",
    )
    async def v1_verify_create(
        payload: VerifyRequest,
        request: Request,
        _enabled: None = Depends(require_verify_enabled),
        _access: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        # Creating a verify job ALWAYS requires the bearer API key, even when
        # OPENVA_PUBLIC_READ_ENABLED is true. Public-read mode grants read-only access
        # to the cached /v1 data endpoints only — never submission.
        telemetry: Telemetry = request.app.state.telemetry
        state = get_service_state(app)

        # Kill-switch (WP-02H): when armed, the verify path FAIL-CLOSES to cached-only.
        # No job is created, NO submitted content is read beyond the already-parsed body,
        # and a clean disabled/anonymous response is returned. The cached/static endpoints
        # are unaffected (this gate is verify-only). The response carries no job_id/token.
        if service_config.verify_kill_switch:
            telemetry.increment("verify_requests_total", outcome="kill_switch_disabled")
            # A clean disabled/anonymous response (no job_id/token); bypass the
            # VerifyCreatedResponse model since no job exists. Headers are applied by the
            # add_openva_headers middleware on the way out.
            return JSONResponse(
                status_code=200,
                content={
                    "state": "disabled",
                    "verify_enabled": False,
                    "snapshot": build_snapshot(state, service_config),
                    "not_advice": True,
                },
            )

        # Application-layer rate-limit POLICY (provider-neutral; off by default). The
        # client is reduced to an opaque key derived from the credential digest — never the
        # raw token. Edge enforcement is WP-02F/02G; this is the in-app backstop.
        rate_limiter: RateLimitPolicy = request.app.state.rate_limiter
        decision = rate_limiter.check(client_key(request.headers.get("authorization")))
        if not decision.allowed:
            telemetry.increment("verify_requests_total", outcome="rate_limited")
            retry_after = max(1, int(round(decision.retry_after_seconds)))
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limited",
                    "message": "verify request rate limit exceeded; retry later",
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Pre-job rejection: an over-limit request is rejected BEFORE any job
        # exists, so row_limit_exceeded is an API response, never a job error_code.
        # The structured detail surfaces the stable row_limit_exceeded API code.
        if len(payload.rows) > service_config.max_verify_rows:
            raise HTTPException(
                status_code=413,
                detail={
                    "error": "row_limit_exceeded",
                    "message": f"verify request exceeds the maximum of {service_config.max_verify_rows} rows",
                },
            )
        jobs = app.state.verify_jobs
        envelopes = app.state.verify_envelopes
        now = datetime.now(timezone.utc)
        # Cost-exhaustion protection (WP-02H): bound the number of concurrently-active
        # (non-terminal) verify jobs in this process so a flood cannot run away before the
        # edge/budget controls exist (those are WP-02F/02G). 0 = unbounded (the default).
        # Enforced AFTER an opportunistic purge so expired jobs never count against the cap.
        purge_expired_jobs(
            jobs, envelopes, app.state.verify_results, now, timedelta(hours=VERIFY_RETAINED_WINDOW_HOURS)
        )
        concurrency: ConcurrencyLimiter = request.app.state.verify_concurrency
        if concurrency.bounded and jobs.active_count() >= concurrency.limit:
            telemetry.increment("verify_requests_total", outcome="concurrency_limited")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "rate_limited",
                    "message": "verify capacity is full; retry later",
                },
                headers={"Retry-After": "5"},
            )

        expires_at = now + timedelta(hours=service_config.job_ttl_hours)

        job_id = new_job_id()
        token = new_job_token()
        digest = token_digest(token)
        request_ref = new_ref()
        # WP-02A minimisation — the transport validates then DISCARDS submitted
        # identities; only non-identifying metadata is retained. We store NO vendor
        # identities (no vendor_name/domain/business_entity_name/registration_number and
        # no raw rows) — only a minimised envelope carrying the row count. WP-02A ships
        # no worker, so nothing would ever consume the rows; retaining them would breach
        # ADR-0001 boundary 4 (transient unpublished inputs). The durable, encrypted,
        # TTL-deleted request envelope holding the actual input arrives in WP-02B.
        # request_ref is still generated and set on the record (the schema requires a
        # non-null request_ref for `received`) and points at this minimised envelope. The
        # envelope carries the job's own expires_at so it is reaped independently of the
        # record even if the process crashes after this put but before jobs.create below
        # (the after-envelope-before-job crash point); see purge_expired_jobs' orphan sweep.
        expires_at_iso = _iso_z(expires_at)
        envelopes.put(request_ref, {"row_count": len(payload.rows)}, expires_at_iso)

        record = JobRecord(
            job_id=job_id,
            job_token_digest=digest,
            state="received",
            request_ref=request_ref,
            row_count=len(payload.rows),
            created_at=_iso_z(now),
            updated_at=_iso_z(now),
            expires_at=expires_at_iso,
        )
        jobs.create(record)

        # Telemetry: structured creation event + counter. The job_token and any vendor
        # identity are NEVER passed here; the redactor would drop them regardless. job_id
        # is a loggable (non-credential) correlation id; row_count is an aggregate.
        telemetry.log("verify_job_created", job_id=job_id, state=record.state, row_count=record.row_count)
        telemetry.increment("verify_requests_total", outcome="created")

        # WP-02A ships no worker, so the job stays `received` and never executes.
        # That is correct for this slice. The token is returned ONLY here.
        return {
            "job_id": job_id,
            "job_token": token,
            "state": record.state,
            "expires_at": record.expires_at,
            "snapshot": build_snapshot(state, service_config),
            "not_advice": True,
        }

    @app.get(
        "/v1/verify/{job_id}",
        response_model=VerifyStatusResponse,
        tags=[V1_TAG],
        summary="Poll a hosted verify job (job_token via Authorization: Bearer only)",
    )
    async def v1_verify_status(
        job_id: str,
        request: Request,
        _enabled: None = Depends(require_verify_enabled),
    ) -> Any:
        # Poll is authorized SOLELY by the job_token (not the API key, not public
        # read). The token is header-only — there is no query/path/cookie fallback.
        # Lifecycle ordering per hosted-deployment.yaml `expiry` (all error cases are
        # CONTENT-FREE: empty body, X-OpenVA-* + advisory-boundary headers only, added
        # by the add_openva_headers middleware):
        #   record gone (purged or never existed) -> 404 (job_id is NOT a credential)
        #   now >= expires_at (retained, within window) -> 410 (checked before the token)
        #   live job + missing/invalid job_token -> 401
        #   else -> 200 (the JSON status projection, with not_advice: true)
        jobs = app.state.verify_jobs
        now = datetime.now(timezone.utc)
        # Opportunistically advance the expiry lifecycle on access (no background
        # thread): physically delete any job past expires_at + the retained window,
        # together with its envelope/result. This makes the 410 (retained) -> 404
        # (deleted) transition real — a record polled after its retained window is
        # GONE, not merely flagged.
        purge_expired_jobs(
            jobs, app.state.verify_envelopes, app.state.verify_results, now,
            timedelta(hours=VERIFY_RETAINED_WINDOW_HOURS),
        )
        # A non-UUID path param can never be a real job; resolve to None so it takes
        # the same not-found path (never a 500, never an existence signal beyond 404).
        record = jobs.get(job_id) if JOB_ID_RE.fullmatch(job_id) else None
        if record is None:
            # Unknown, deleted, or just purged (covers non-UUID too). job_id is not a
            # credential, so a content-free 404 leaks nothing.
            return Response(status_code=404)

        if now >= _parse_iso_z(record.expires_at):
            # Expired-but-retained (within the retained window): content-free 410. The
            # record still exists; it is removed once the window fully elapses (-> 404).
            return Response(status_code=410)

        # Token check last, constant-time, with no token echo. A missing or wrong
        # token on a live job is an indistinguishable, content-free generic 401.
        token = extract_bearer_token(request.headers.get("authorization"))
        if token is None or not digests_match(token_digest(token), record.job_token_digest):
            return Response(status_code=401)

        state = get_service_state(app)
        result = None
        if record.state == "completed" and record.result_ref is not None:
            result = app.state.verify_results.get(record.result_ref)

        # Projection excludes the token, the digest, request content, and lease fields.
        return {
            "job_id": record.job_id,
            "state": record.state,
            "row_count": record.row_count,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "expires_at": record.expires_at,
            "result": result,
            "error_code": record.error_code,
            "snapshot": build_snapshot(state, service_config),
            "not_advice": True,
        }

    return app


def _iso_z(value: datetime) -> str:
    """Render a timezone-aware datetime as ISO-8601 with a literal Z suffix."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# NOTE (round-3 Blocker D): app.py no longer defines its own lenient _parse_iso_z. The poll
# path (v1_verify_status) uses the SINGLE strict parser imported from verify_transport, so
# the service has ONE deterministic RFC3339 validation boundary. The only timestamps the poll
# path parses are self-produced canonical ``...Z`` values (record.expires_at), which the strict
# parser accepts unchanged.


def install_middleware_and_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_openva_headers(request: Request, call_next):
        response = await call_next(request)
        apply_headers(response.headers, request.app)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # A structured detail ({"error", "message"}) surfaces a stable API code such as
        # row_limit_exceeded; a plain string detail keeps the generic http_error shape.
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail and "message" in detail:
            content = {"error": detail["error"], "message": detail["message"]}
        else:
            content = {"error": "http_error", "message": str(detail)}
        response = JSONResponse(status_code=exc.status_code, content=content)
        # Preserve any advisory headers set on the exception (e.g. Retry-After on a 429
        # rate-limit rejection); they carry no submitted content.
        for name, value in (getattr(exc, "headers", None) or {}).items():
            response.headers[name] = value
        apply_headers(response.headers, request.app)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        response = JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": "Invalid match service request"},
        )
        apply_headers(response.headers, request.app)
        return response

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        response = JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Internal OpenVA match service error"},
        )
        apply_headers(response.headers, request.app)
        return response


def require_api_key(request: Request) -> None:
    config: ServiceConfig = request.app.state.config
    expected = f"Bearer {config.api_key}"
    if request.headers.get("authorization") != expected:
        raise HTTPException(status_code=401, detail="missing or invalid API key")


def require_verify_enabled(request: Request) -> None:
    """Gate the hosted verify transport behind the feature flag.

    When OPENVA_VERIFY_TRANSPORT_ENABLED is False (default) both verify endpoints
    return 404; the cached endpoints and app state are unchanged (the routes are
    registered but inert). A 404 (rather than 403) leaks nothing about whether the
    capability exists for this deployment."""
    config: ServiceConfig = request.app.state.config
    if not config.verify_transport_enabled:
        raise HTTPException(status_code=404, detail="verify transport is not enabled")


def require_read_access(request: Request) -> None:
    """Single reusable read-access policy for the /v1 data endpoints.

    Public-read mode (OPENVA_PUBLIC_READ_ENABLED) grants unauthenticated read-only
    access; otherwise the existing bearer key is required. Public mode never enables any
    write, submission, or candidate-intake capability — there are no such endpoints."""
    config: ServiceConfig = request.app.state.config
    if config.public_read_enabled:
        return
    require_api_key(request)


def get_service_state(app: FastAPI) -> ServiceState:
    return app.state.service_state


def apply_headers(headers: dict[str, str], app: FastAPI) -> None:
    config: ServiceConfig | None = getattr(app.state, "config", None)
    state: ServiceState | None = getattr(app.state, "service_state", None)
    if config:
        headers[HEADER_SERVICE_VERSION] = config.service_version
    if state:
        headers[HEADER_PACK_PROFILE] = state.meta.profile_id
        headers[HEADER_PACK_SCHEMA_VERSION] = state.meta.schema_version
        headers[HEADER_PACK_GENERATED_AT] = state.meta.generated_at
    headers[HEADER_ADVISORY_BOUNDARY] = ADVISORY_BOUNDARY


async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


class RequestSizeLimitMiddleware:
    """ASGI middleware that bounds the request body before Pydantic parses it.

    Enforcement happens at the ASGI boundary, including chunked / no-Content-Length
    requests: it fast-rejects on a declared Content-Length over the cap, then buffers the
    streamed body up to the cap (never holding more than ~max_bytes in memory) before
    replaying it to the app. The CSV ``/match`` endpoint is exempt — it keeps its own
    dedicated byte cap unchanged. A breach returns the stable 413 envelope with the
    standard OpenVA headers."""

    EXEMPT_PATHS = frozenset({"/match"})

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break
                if declared > self.max_bytes:
                    await self._reject(scope, send)
                    return
                break

        buffered: list[dict[str, Any]] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                if message["type"] == "http.disconnect":
                    break
                continue
            total += len(message.get("body", b"") or b"")
            if total > self.max_bytes:
                await self._reject(scope, send)
                return
            buffered.append(message)
            more = message.get("more_body", False)

        replayed_terminal = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed_terminal
            if buffered:
                return buffered.pop(0)
            if not replayed_terminal:
                replayed_terminal = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, scope, send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"error": "http_error", "message": f"request body exceeds the maximum of {self.max_bytes} bytes"},
        )
        app = scope.get("app")
        if app is not None:
            apply_headers(response.headers, app)
        await response(scope, _empty_receive, send)
