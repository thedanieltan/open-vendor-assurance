from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_VERSION = "0.1.0"
ADVISORY_BOUNDARY = "non_advisory"

# Authoritative hard ceiling on the hosted verify row count. Matches
# hosted-deployment.yaml hosted_verify_limits.max_verify_rows AND
# hosted-job-record.schema row_count max. OPENVA_MAX_VERIFY_ROWS may be set lower
# but NEVER higher; a value above this fails closed at config construction/startup.
VERIFY_ROWS_HARD_CEILING = 20

# Configurable launch defaults, not hard-coded product promises. The cached path is
# synchronous (upload + row caps enforced). When the optional verify transport is
# enabled, OPENVA_JOB_TTL_HOURS is enforced (the verify job expires_at + a retained-window
# purge); OPENVA_MAX_ACTIVE_JOBS remains reserved/unenforced scaffolding (verify
# concurrency control is deferred to the worker, WP-02C).
DEFAULT_MAX_UPLOAD_BYTES = 5_000_000
DEFAULT_MAX_ROWS = 500
DEFAULT_MAX_ACTIVE_JOBS = 3
DEFAULT_JOB_TTL_HOURS = 24

# WP-02H provider-neutral application-hardening defaults. All are OFF or GENEROUS so the
# default build behaviour is UNCHANGED; only a deployment that opts in changes anything.
#
# Concurrency cap: 0 means UNBOUNDED (the default). A positive value bounds the number of
# concurrently-executing verify jobs in this process (cost-exhaustion protection) so a
# flood cannot run away before edge/budget controls exist (those are WP-02F/02G).
DEFAULT_VERIFY_CONCURRENCY_LIMIT = 0
# Application-layer rate-limit POLICY (a per-client token bucket the app consults — NOT an
# edge/WAF). Disabled by default; even enabled, the defaults are generous. The edge
# realisation is WP-02F/02G.
DEFAULT_RATE_LIMIT_ENABLED = False
DEFAULT_RATE_LIMIT_CAPACITY = 60
DEFAULT_RATE_LIMIT_REFILL_PER_SECOND = 1.0
# Hosted verify-mode row cap. Aligned to hosted-deployment.yaml
# hosted_verify_limits.max_verify_rows and the job record schema's row_count
# maximum (0..20). The verify limit is far smaller than the cached row cap
# because each verify row drives real, serial, SSRF-safe live fetches.
DEFAULT_MAX_VERIFY_ROWS = 20

# The expired-but-retained window: the time after `expires_at` during which a job
# record is kept (so a poll returns a content-free 410) before it is physically
# deleted (after which a poll returns a content-free 404). This realizes the
# hosted-deployment.yaml `expiry` model
# (expires_at_then_410_while_retained_then_404_after_deletion): in production this is
# the store-native TTL + object-lifecycle delete; in the WP-02A in-memory transport it
# is enforced by an opportunistic purge on access. Not env-overridable in WP-02A.
VERIFY_RETAINED_WINDOW_HOURS = 1

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TRUE_TOKENS = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServiceConfig:
    pack_path: Path
    api_key: str
    service_version: str = SERVICE_VERSION
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    # Maximum JSON request body accepted before parsing, enforced at the ASGI boundary
    # for the /v1 endpoints. Independent of the CSV upload cap, though it defaults to the
    # same value when unset.
    max_request_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_rows: int = DEFAULT_MAX_ROWS
    max_active_jobs: int = DEFAULT_MAX_ACTIVE_JOBS
    job_ttl_hours: int = DEFAULT_JOB_TTL_HOURS
    # Hosted verify-mode transport. When False (default) the verify endpoints
    # return 404; the cached endpoints and app state are unchanged (the verify routes
    # are registered but inert). Verify mode introduces async jobs (a later
    # slice ships the worker; WP-02A ships the transport only).
    verify_transport_enabled: bool = False
    # Maximum verify rows per request, enforced by the API before any job is
    # created (over-limit is a pre-job rejection, never a job error_code).
    max_verify_rows: int = DEFAULT_MAX_VERIFY_ROWS
    # WP-02D candidate-ingress (discovery role only). When False (default) the worker
    # proposes NO candidates and behaves exactly as the WP-02C worker. When True (only
    # meaningful when verify_transport_enabled is also True) genuinely newly-discovered
    # public sources surfaced by a verify job are STAGED into the EXISTING durable candidate
    # ingress AFTER the job is terminalized — discovery never gates the verify result. The
    # hosted service holds NO GitHub credential; the credentialed PR-opening remains the
    # existing, infra-gated candidate_ingress component. Enabling this without the verify
    # transport is inert (no worker runs).
    candidate_ingress_enabled: bool = False
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
    # --- WP-02H application-hardening controls (provider-neutral; off/generous) ---
    # Kill-switch: when True the verify/worker path fail-closes to CACHED-ONLY — verify
    # returns a clean disabled/anonymous response and no job is created; the cached/static
    # endpoints are unaffected. Default False = normal operation. This is an application
    # flag (no infra); the provider edge/automation that ARMS it lives in WP-02F/02G.
    verify_kill_switch: bool = False
    # In-process concurrency cap on executing verify jobs (0 = unbounded, the default).
    verify_concurrency_limit: int = DEFAULT_VERIFY_CONCURRENCY_LIMIT
    # Application-layer rate-limit policy (per opaque client key). Off by default.
    rate_limit_enabled: bool = DEFAULT_RATE_LIMIT_ENABLED
    rate_limit_capacity: int = DEFAULT_RATE_LIMIT_CAPACITY
    rate_limit_refill_per_second: float = DEFAULT_RATE_LIMIT_REFILL_PER_SECOND

    def __post_init__(self) -> None:
        # Clamp the configured verify row count to the authoritative budget. A value
        # above VERIFY_ROWS_HARD_CEILING (the hosted-deployment.yaml + job-record
        # schema maximum) fails closed at construction/startup; lower is allowed.
        if not (1 <= self.max_verify_rows <= VERIFY_ROWS_HARD_CEILING):
            raise RuntimeError(
                f"max_verify_rows must be between 1 and {VERIFY_ROWS_HARD_CEILING} "
                f"(hosted_verify_limits.max_verify_rows), got {self.max_verify_rows}"
            )

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        pack_path = os.environ.get("OPENVA_PACK_PATH", "").strip()
        api_key = os.environ.get("OPENVA_SERVICE_API_KEY", "").strip()
        if not pack_path:
            raise RuntimeError("OPENVA_PACK_PATH is required")
        if not api_key:
            raise RuntimeError("OPENVA_SERVICE_API_KEY is required")
        max_upload_bytes = _positive_int_env("OPENVA_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
        return cls(
            pack_path=Path(pack_path),
            api_key=api_key,
            max_upload_bytes=max_upload_bytes,
            # Defaults to the upload cap when unset, but is configured independently.
            max_request_bytes=_positive_int_env("OPENVA_MAX_REQUEST_BYTES", max_upload_bytes),
            max_rows=_positive_int_env("OPENVA_MAX_ROWS", DEFAULT_MAX_ROWS),
            max_active_jobs=_positive_int_env("OPENVA_MAX_ACTIVE_JOBS", DEFAULT_MAX_ACTIVE_JOBS),
            job_ttl_hours=_positive_int_env("OPENVA_JOB_TTL_HOURS", DEFAULT_JOB_TTL_HOURS),
            verify_transport_enabled=_bool_env("OPENVA_VERIFY_TRANSPORT_ENABLED", False),
            max_verify_rows=_positive_int_env("OPENVA_MAX_VERIFY_ROWS", DEFAULT_MAX_VERIFY_ROWS),
            candidate_ingress_enabled=_bool_env("OPENVA_CANDIDATE_INGRESS_ENABLED", False),
            public_read_enabled=_bool_env("OPENVA_PUBLIC_READ_ENABLED", False),
            allowed_origins=_origins_env("OPENVA_ALLOWED_ORIGINS"),
            catalog_commit_sha=_commit_sha_env("OPENVA_CATALOG_COMMIT_SHA"),
            verify_kill_switch=_bool_env("OPENVA_VERIFY_KILL_SWITCH", False),
            verify_concurrency_limit=_nonneg_int_env(
                "OPENVA_VERIFY_CONCURRENCY_LIMIT", DEFAULT_VERIFY_CONCURRENCY_LIMIT
            ),
            rate_limit_enabled=_bool_env("OPENVA_RATE_LIMIT_ENABLED", DEFAULT_RATE_LIMIT_ENABLED),
            rate_limit_capacity=_positive_int_env(
                "OPENVA_RATE_LIMIT_CAPACITY", DEFAULT_RATE_LIMIT_CAPACITY
            ),
            rate_limit_refill_per_second=_positive_float_env(
                "OPENVA_RATE_LIMIT_REFILL_PER_SECOND", DEFAULT_RATE_LIMIT_REFILL_PER_SECOND
            ),
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


def _nonneg_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a non-negative integer") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be a non-negative integer")
    return value


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive number")
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
