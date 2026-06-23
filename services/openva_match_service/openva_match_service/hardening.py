"""Provider-neutral application-layer hardening controls (WP-02H).

This module ships the APPLICATION-LAYER abuse / cost-exhaustion / concurrency controls
that land BEFORE any infrastructure. They are provider-neutral policy objects and
in-process enforcement hooks — NOT an edge/WAF, NOT cloud config. Provider-specific edge
rate-limit enforcement, alert routing, and SLO dashboards are explicitly WP-02F/02G.

Everything here is OFF or GENEROUS by default so wiring it changes nothing unless a
deployment opts in:

  - :class:`RateLimitPolicy` — a deterministic token-bucket per opaque client key. The
    POLICY + enforcement hook the app consults; the edge realisation is a later slice.
    Disabled by default (``enabled=False``) → always allows.
  - :class:`ConcurrencyLimiter` — a bounded in-process gate on concurrent verify jobs
    (cost-exhaustion protection: a flood cannot run away before edge/budget controls
    exist). A non-positive limit means unbounded (the default posture).

The clock is injected so rate-limit behaviour is deterministic in tests (no wall-clock
sleeps). Client identity is reduced to an opaque key by the caller; a RAW identifier or a
prohibited telemetry field is never stored here.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    """The outcome of a rate-limit check. ``allowed`` is the only thing the caller acts
    on; ``remaining`` and ``retry_after_seconds`` are advisory and safe to surface
    (they carry no submitted content)."""

    allowed: bool
    remaining: float
    retry_after_seconds: float = 0.0


class RateLimitPolicy:
    """Deterministic token-bucket rate limiter, keyed per opaque client key.

    Provider-neutral application policy. Each key gets a bucket of ``capacity`` tokens that
    refills at ``refill_per_second``; a request consumes one token. Over-limit requests are
    rejected (``allowed=False``) with a ``retry_after_seconds`` hint. The clock is injected
    (``now``, a monotonic seconds source) so tests are deterministic with no sleeps.

    DISABLED BY DEFAULT: when ``enabled`` is False every check allows, so wiring the policy
    changes nothing until a deployment turns it on (and even then defaults are generous)."""

    def __init__(
        self,
        *,
        capacity: float = 60.0,
        refill_per_second: float = 1.0,
        enabled: bool = False,
        now: Callable[[], float] | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_per_second <= 0:
            raise ValueError("refill_per_second must be positive")
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self.enabled = bool(enabled)
        import time as _time

        self._now = now or _time.monotonic
        self._lock = threading.Lock()
        # key -> (tokens, last_refill_ts)
        self._buckets: dict[str, tuple[float, float]] = {}

    def _refill(self, key: str, now: float) -> float:
        tokens, last = self._buckets.get(key, (self.capacity, now))
        elapsed = max(0.0, now - last)
        tokens = min(self.capacity, tokens + elapsed * self.refill_per_second)
        return tokens

    def check(self, key: str, *, cost: float = 1.0) -> RateLimitDecision:
        """Consult-and-consume: if a token is available for ``key``, consume ``cost`` and
        allow; otherwise reject without consuming. When disabled, always allow and never
        track state (so a flag-off deployment carries no per-key memory)."""
        if not self.enabled:
            return RateLimitDecision(allowed=True, remaining=self.capacity)
        now = self._now()
        with self._lock:
            tokens = self._refill(key, now)
            if tokens >= cost:
                tokens -= cost
                self._buckets[key] = (tokens, now)
                return RateLimitDecision(allowed=True, remaining=tokens)
            # Rejected: do NOT consume; report when the next token will be available.
            deficit = cost - tokens
            retry_after = deficit / self.refill_per_second
            self._buckets[key] = (tokens, now)
            return RateLimitDecision(allowed=False, remaining=tokens, retry_after_seconds=retry_after)


class ConcurrencyLimitExceeded(Exception):
    """Raised when the in-process concurrency gate is full (cost-exhaustion protection)."""


class _Slot:
    """A context manager that releases a :class:`ConcurrencyLimiter` slot on exit."""

    def __init__(self, limiter: "ConcurrencyLimiter") -> None:
        self._limiter = limiter

    def __enter__(self) -> "_Slot":
        return self

    def __exit__(self, *exc: object) -> None:
        self._limiter._release()


class ConcurrencyLimiter:
    """Bounded in-process gate on concurrent verify jobs (cost-exhaustion protection).

    NON-BLOCKING: ``acquire()`` returns a slot context manager when capacity is available
    and raises :class:`ConcurrencyLimitExceeded` when the cap is reached, so the app can
    fail-fast with a stable 429/503 rather than queueing unbounded work. A non-positive
    ``limit`` means UNBOUNDED (the default posture) — ``acquire`` always succeeds and no
    counter is kept. Thread-safe (the worker pool and the API may both gate)."""

    def __init__(self, limit: int = 0) -> None:
        self.limit = int(limit)
        self._lock = threading.Lock()
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    @property
    def bounded(self) -> bool:
        return self.limit > 0

    def acquire(self) -> _Slot:
        if not self.bounded:
            return _Slot(self)
        with self._lock:
            if self._in_flight >= self.limit:
                raise ConcurrencyLimitExceeded(
                    f"verify concurrency limit of {self.limit} in-flight jobs reached"
                )
            self._in_flight += 1
        return _Slot(self)

    def _release(self) -> None:
        if not self.bounded:
            return
        with self._lock:
            if self._in_flight > 0:
                self._in_flight -= 1


def client_key(authorization: str | None, fallback: str | None = None) -> str:
    """Reduce a client to a STABLE, OPAQUE rate-limit key without retaining a credential.

    The key is derived from the presented bearer credential by digesting it (never the raw
    value) so two requests from the same caller share a bucket while the raw token never
    enters the policy's memory or any telemetry. When no credential is present, the
    ``fallback`` (e.g. a coarse network class supplied by the caller) is digested instead;
    absent both, an ``anonymous`` constant is used (all such callers share one bucket)."""
    import hashlib

    material = ""
    if authorization:
        material = authorization.strip()
    elif fallback:
        material = fallback.strip()
    if not material:
        return "anonymous"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return "client:" + digest[:16]
