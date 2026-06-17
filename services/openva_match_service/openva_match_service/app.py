from __future__ import annotations

import re
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .adapter_paths import ensure_adapter_paths

ensure_adapter_paths()

from openva_pack_reader import PackError  # noqa: E402

from .config import ADVISORY_BOUNDARY, ServiceConfig  # noqa: E402
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
)
from .service_state import ServiceState, load_service_state  # noqa: E402

HEADER_SERVICE_VERSION = "X-OpenVA-Service-Version"
HEADER_PACK_PROFILE = "X-OpenVA-Pack-Profile"
HEADER_PACK_SCHEMA_VERSION = "X-OpenVA-Pack-Schema-Version"
HEADER_PACK_GENERATED_AT = "X-OpenVA-Pack-Generated-At"
HEADER_ADVISORY_BOUNDARY = "X-OpenVA-Advisory-Boundary"

# Catalogue vendor ids are lowercase-kebab tokens; reject anything else (path-traversal
# attempts, spaces, slashes) consistently as not found.
VENDOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")

V1_TAG = "v1"
V1_DESCRIPTION = (
    "Read-only, cached-pack catalogue enrichment for zero-install spreadsheet and "
    "document clients. Responses reflect the catalogue pack loaded at startup; no source "
    "is fetched or verified live during a request. Every response carries a snapshot "
    "identity and `not_advice: true`. Access requires the bearer API key unless "
    "OPENVA_PUBLIC_READ_ENABLED is set, in which case these read-only endpoints are public."
)


def create_app(config: ServiceConfig | None = None) -> FastAPI:
    service_config = config or ServiceConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = service_config
        app.state.service_state = load_service_state(str(service_config.pack_path))
        yield

    app = FastAPI(
        title="OpenVA Match Service",
        version=service_config.service_version,
        lifespan=lifespan,
        openapi_tags=[{"name": V1_TAG, "description": V1_DESCRIPTION}],
    )
    install_middleware_and_handlers(app)
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
        if not VENDOR_ID_RE.fullmatch(vendor_id):
            raise HTTPException(status_code=404, detail="vendor not found")
        try:
            detail = vendor_detail(state, vendor_id)
        except PackError as exc:
            # Do not leak the underlying pack message (it may reference internal paths).
            raise HTTPException(status_code=404, detail="vendor not found") from exc
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

    return app


def install_middleware_and_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_openva_headers(request: Request, call_next):
        response = await call_next(request)
        apply_headers(response.headers, request.app)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        response = JSONResponse(
            status_code=exc.status_code,
            content={"error": "http_error", "message": str(exc.detail)},
        )
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
