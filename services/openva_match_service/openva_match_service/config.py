from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
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

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TRUE_TOKENS = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServiceConfig:
    pack_path: Path
    api_key: str
    service_version: str = SERVICE_VERSION
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_rows: int = DEFAULT_MAX_ROWS
    max_active_jobs: int = DEFAULT_MAX_ACTIVE_JOBS
    job_ttl_hours: int = DEFAULT_JOB_TTL_HOURS
    # Zero-install read access. When False (default) the new /v1 data endpoints
    # require the existing bearer key; when True they are public read-only. Public
    # mode never enables any write/submission/candidate-intake capability.
    public_read_enabled: bool = False
    # Cross-origin application origins for browser-based clients. Empty means no
    # cross-origin origins are enabled (never an implicit wildcard).
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    # Optional deployment-supplied catalogue commit SHA (40-char lowercase hex).
    # Never fabricated; None when unavailable.
    catalog_commit_sha: str | None = None

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
            public_read_enabled=_bool_env("OPENVA_PUBLIC_READ_ENABLED", False),
            allowed_origins=_origins_env("OPENVA_ALLOWED_ORIGINS"),
            catalog_commit_sha=_commit_sha_env("OPENVA_CATALOG_COMMIT_SHA"),
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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in _TRUE_TOKENS


def _origins_env(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return parse_allowed_origins(raw)


def parse_allowed_origins(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated origins list. Whitespace is stripped, empty entries
    ignored, order and duplicates de-duplicated while preserving first-seen order.
    An absent or empty value yields an empty tuple, never a wildcard."""
    seen: list[str] = []
    for entry in (raw or "").split(","):
        origin = entry.strip()
        if origin and origin not in seen:
            seen.append(origin)
    return tuple(seen)


def _commit_sha_env(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    if not _COMMIT_SHA_RE.fullmatch(raw):
        raise RuntimeError(f"{name} must be a 40-character lowercase hexadecimal commit SHA")
    return raw
