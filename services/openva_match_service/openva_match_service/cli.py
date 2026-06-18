from __future__ import annotations

import os

import uvicorn

_TRUE_TOKENS = {"1", "true", "yes", "on"}


def access_log_enabled() -> bool:
    """Whether Uvicorn's request access log is enabled. Default False.

    Default Uvicorn access logs record the concrete request target, which for
    ``/v1/vendors/{vendor_id}`` would log a submitted vendor identity. The supported
    launcher therefore disables access logging unless OPENVA_ACCESS_LOG_ENABLED is set.
    External ASGI/Gunicorn deployments must likewise disable raw-path access logging or
    use route-template/redacted structured logging, and must never log request bodies,
    query values, or concrete vendor IDs."""
    return os.environ.get("OPENVA_ACCESS_LOG_ENABLED", "").strip().lower() in _TRUE_TOKENS


def main() -> int:
    port = int(os.environ.get("OPENVA_SERVICE_PORT", "8000"))
    uvicorn.run(
        "openva_match_service.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        access_log=access_log_enabled(),
    )
    return 0
