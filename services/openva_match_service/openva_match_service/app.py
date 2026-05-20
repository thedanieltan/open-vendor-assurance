from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .adapter_paths import ensure_adapter_paths

ensure_adapter_paths()

from .config import ADVISORY_BOUNDARY, ServiceConfig  # noqa: E402
from .conversion import match_csv_bytes  # noqa: E402
from .service_state import ServiceState, load_service_state  # noqa: E402

HEADER_SERVICE_VERSION = "X-OpenVA-Service-Version"
HEADER_PACK_PROFILE = "X-OpenVA-Pack-Profile"
HEADER_PACK_SCHEMA_VERSION = "X-OpenVA-Pack-Schema-Version"
HEADER_PACK_GENERATED_AT = "X-OpenVA-Pack-Generated-At"
HEADER_ADVISORY_BOUNDARY = "X-OpenVA-Advisory-Boundary"


def create_app(config: ServiceConfig | None = None) -> FastAPI:
    service_config = config or ServiceConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = service_config
        app.state.service_state = load_service_state(str(service_config.pack_path))
        yield

    app = FastAPI(title="OpenVA Match Service", version=service_config.service_version, lifespan=lifespan)
    install_middleware_and_handlers(app)

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
        state = get_service_state(app)
        try:
            rows = match_csv_bytes(await inventory_csv.read(), state.matcher_index)
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
