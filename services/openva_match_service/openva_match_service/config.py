from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SERVICE_VERSION = "0.1.0"
ADVISORY_BOUNDARY = "non_advisory"

# Configurable launch defaults, not hard-coded product promises. Only the upload
# and row caps are enforced today (the service is still synchronous); the job
# limits are read-and-stored scaffolding for the later async resolver.
DEFAULT_MAX_UPLOAD_BYTES = 5_000_000
DEFAULT_MAX_ROWS = 500
DEFAULT_MAX_ACTIVE_JOBS = 3
DEFAULT_JOB_TTL_HOURS = 24


@dataclass(frozen=True)
class ServiceConfig:
    pack_path: Path
    api_key: str
    service_version: str = SERVICE_VERSION
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_rows: int = DEFAULT_MAX_ROWS
    max_active_jobs: int = DEFAULT_MAX_ACTIVE_JOBS
    job_ttl_hours: int = DEFAULT_JOB_TTL_HOURS

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        pack_path = os.environ.get("OPENVA_PACK_PATH", "").strip()
        api_key = os.environ.get("OPENVA_SERVICE_API_KEY", "").strip()
        if not pack_path:
            raise RuntimeError("OPENVA_PACK_PATH is required")
        if not api_key:
            raise RuntimeError("OPENVA_SERVICE_API_KEY is required")
        return cls(
            pack_path=Path(pack_path),
            api_key=api_key,
            max_upload_bytes=_positive_int_env("OPENVA_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
            max_rows=_positive_int_env("OPENVA_MAX_ROWS", DEFAULT_MAX_ROWS),
            max_active_jobs=_positive_int_env("OPENVA_MAX_ACTIVE_JOBS", DEFAULT_MAX_ACTIVE_JOBS),
            job_ttl_hours=_positive_int_env("OPENVA_JOB_TTL_HOURS", DEFAULT_JOB_TTL_HOURS),
        )


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value
