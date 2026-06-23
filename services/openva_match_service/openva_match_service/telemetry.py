"""Provider-neutral telemetry interface + always-on redaction (WP-02H).

This module ships the ``telemetry`` provider interface required by
hosted-deployment.yaml ``cross_cutting_execution_constraints.provider_interfaces``
(``queue``, ``store``, ``telemetry``). It is PROVIDER-NEUTRAL application code only:
an abstract structured-logging + metrics interface plus ONE in-memory/stdout
implementation. A real provider exporter (Cloud Logging / Cloud Monitoring / OTLP)
is a later, infrastructure-gated slice (WP-02F/02G) and is NOT implemented here.

The load-bearing guarantee is the REDACTION layer. Every field listed in the
contract's ``prohibited_telemetry_fields`` MUST be impossible to emit:

  - request_body
  - vendor_identity
  - inventory_row
  - uploaded_inventory
  - tool_arguments
  - candidate_url
  - authorization_header  (the ``Authorization`` header / Bearer value)
  - job_token             (the raw capability; only job_token_digest is ever safe)

The redactor is deterministic and ALWAYS-ON (it only ever removes data, so it is
the single control that is not behind a feature flag). It drops/masks prohibited
keys anywhere in a (possibly nested) payload, masks the ``Authorization`` header and
any bearer-token-shaped value, and refuses to emit a metric label that is a
prohibited field. The only correlation id permitted across signals is the opaque
``job_id`` (not a credential); see ADR-0001 / ADR-0006 and the observability spec
(docs/operations/hosted-deployment-observability.md).
"""

from __future__ import annotations

import json
import re
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import IO, Any

# The verbatim contract prohibited_telemetry_fields list. Kept here as an executable
# constant so the redactor can never drift from the contract; a drift test asserts the
# doc/contract carry the same list.
PROHIBITED_TELEMETRY_FIELDS: tuple[str, ...] = (
    "request_body",
    "vendor_identity",
    "inventory_row",
    "uploaded_inventory",
    "tool_arguments",
    "candidate_url",
    "authorization_header",
    "job_token",
)

REDACTED = "[redacted]"

# Key names (case-insensitive, after normalising separators) that carry submitted
# content or a credential and must be dropped/masked wherever they appear in a payload.
# This is a SUPERSET of the prohibited list: it also catches the concrete request-field
# names the app handles (vendor identity components, inventory rows, the Authorization
# header, candidate/source URLs, the raw token) so a caller cannot smuggle a prohibited
# value under a near-synonym key.
_PROHIBITED_KEYS: frozenset[str] = frozenset(
    {
        # contract prohibited_telemetry_fields (normalised)
        "request_body",
        "vendor_identity",
        "inventory_row",
        "uploaded_inventory",
        "tool_arguments",
        "candidate_url",
        "authorization_header",
        "job_token",
        # concrete request-field names that ARE the prohibited content
        "authorization",
        "vendor_name",
        "business_entity_name",
        "registration_number",
        "domain",
        "rows",
        "row",
        "inventory",
        "inventory_csv",
        "vendors",
        "vendor",
        "candidate",
        "url",
        "source_url",
        "token",
        "bearer",
        "api_key",
        "password",
        "secret",
    }
)

# A bearer-token-shaped value: ``Bearer <opaque>`` (case-insensitive). Masked wherever it
# appears as a string VALUE, defeating an attempt to log the Authorization header under a
# non-prohibited key name.
_BEARER_VALUE_RE = re.compile(r"\bbearer\s+\S+", re.IGNORECASE)

# Keys whose values are always safe, low-cardinality operational metadata (the
# observability spec §1 "MAY carry" set). Used only to document intent; the redactor does
# not depend on an allow-list (it is a deny-by-key + value-mask design) so a brand-new
# safe key is never accidentally dropped.
SAFE_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "job_id",
        "state",
        "freshness_mode",
        "error_code",
        "attempt",
        "dispatch_attempt",
        "row_count",
        "latency_ms",
        "duration_ms",
        "http_status",
        "status_class",
        "route",
        "region",
        "revision",
        "queue",
        "outcome",
    }
)


def _normalise_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _is_prohibited_key(key: Any) -> bool:
    return _normalise_key(key) in _PROHIBITED_KEYS


def _mask_value(value: Any) -> Any:
    """Mask a leaf string value if it looks like a bearer credential; otherwise pass it
    through. Non-strings are returned unchanged (redaction of structure is by key)."""
    if isinstance(value, str) and _BEARER_VALUE_RE.search(value):
        return REDACTED
    return value


def redact(payload: Any, *, _depth: int = 0) -> Any:
    """Return a deep, deterministic copy of ``payload`` with every prohibited key
    DROPPED and every bearer-token-shaped value MASKED, recursively through dicts and
    lists. The input is never mutated.

    - A mapping key in the prohibited set is removed entirely (the value never leaves).
    - Any remaining string value matching the bearer pattern is replaced with the
      redaction marker (defends against the header value smuggled under a safe key).
    - Recursion is bounded so a pathological/cyclic structure cannot exhaust the stack;
      beyond the bound the value is replaced with the redaction marker.
    """
    if _depth > 32:
        return REDACTED
    if isinstance(payload, Mapping):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if _is_prohibited_key(key):
                continue
            out[str(key)] = redact(value, _depth=_depth + 1)
        return out
    if isinstance(payload, (list, tuple)):
        return [redact(item, _depth=_depth + 1) for item in payload]
    if isinstance(payload, (str, bytes)):
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
        return _mask_value(text)
    return payload


def redact_metric_labels(labels: Mapping[str, Any] | None) -> dict[str, str]:
    """Return only the SAFE, low-cardinality labels, as strings. A prohibited-key label
    is dropped; a bearer-shaped value is masked. ``job_id`` is intentionally NOT a valid
    metric label (unbounded cardinality, observability spec §1) and is dropped here even
    though it is loggable elsewhere."""
    out: dict[str, str] = {}
    if not labels:
        return out
    for key, value in labels.items():
        if _is_prohibited_key(key):
            continue
        if _normalise_key(key) == "job_id":
            # job_id is loggable as a correlation id but never a metric label.
            continue
        masked = _mask_value(value)
        out[str(key)] = REDACTED if masked is REDACTED else str(masked)
    return out


# --- Telemetry provider interface ---------------------------------------------


class Telemetry(ABC):
    """Provider-neutral structured-logging + metrics interface.

    Implementations MUST funnel every emission through the always-on redactor so a
    prohibited field can never reach a backend. The interface is intentionally tiny
    (one structured log method + one counter + one timing observation) — the rich
    provider exporter (labels-as-time-series, histograms, traces) is a later infra
    slice and is built against this same surface."""

    @abstractmethod
    def log(self, event: str, /, **fields: Any) -> None:
        """Emit one structured log event. ``fields`` are redacted before emission."""

    @abstractmethod
    def increment(self, metric: str, *, value: int = 1, **labels: Any) -> None:
        """Increment a counter. Labels are reduced to the safe, low-cardinality set."""

    @abstractmethod
    def observe(self, metric: str, value: float, **labels: Any) -> None:
        """Record a timing/size observation. Labels are reduced to the safe set."""


class InMemoryTelemetry(Telemetry):
    """In-memory + optional stdout structured telemetry (the deterministic local impl).

    Captures redacted log events and metric samples for tests and local runs. When
    ``stream`` is provided, each log event is also written as one JSON line (structured
    logs are JSON per the observability spec). Thread-safe so the worker pool can emit
    concurrently. NO network egress, NO provider SDK."""

    def __init__(self, *, stream: IO[str] | None = None) -> None:
        self._stream = stream
        self._lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        self.observations: list[tuple[str, float, dict[str, str]]] = []

    def log(self, event: str, /, **fields: Any) -> None:
        record = {"event": str(event), **redact(fields)}
        with self._lock:
            self.events.append(record)
            if self._stream is not None:
                self._stream.write(json.dumps(record, sort_keys=True, default=str) + "\n")
                self._stream.flush()

    def increment(self, metric: str, *, value: int = 1, **labels: Any) -> None:
        safe = redact_metric_labels(labels)
        key = (str(metric), tuple(sorted(safe.items())))
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + int(value)

    def observe(self, metric: str, value: float, **labels: Any) -> None:
        safe = redact_metric_labels(labels)
        with self._lock:
            self.observations.append((str(metric), float(value), safe))

    # -- test/inspection helpers (not part of the provider interface) -----------

    def counter_value(self, metric: str, **labels: Any) -> int:
        safe = redact_metric_labels(labels)
        key = (str(metric), tuple(sorted(safe.items())))
        with self._lock:
            return self.counters.get(key, 0)

    def emitted_text(self) -> str:
        """All captured telemetry rendered to a single string (logs + metrics +
        observations) for leakage assertions: no prohibited value may appear here."""
        with self._lock:
            parts: list[str] = [json.dumps(e, sort_keys=True, default=str) for e in self.events]
            parts += [
                json.dumps({"metric": m, "labels": dict(lab), "value": v}, sort_keys=True)
                for (m, lab), v in self.counters.items()
            ]
            parts += [
                json.dumps({"metric": m, "value": v, "labels": lab}, sort_keys=True, default=str)
                for (m, v, lab) in self.observations
            ]
        return "\n".join(parts)


class StdoutTelemetry(InMemoryTelemetry):
    """Structured telemetry that writes JSON log lines to stdout (and still captures
    in memory). The default provider-neutral runtime sink until an exporter is wired."""

    def __init__(self) -> None:
        super().__init__(stream=sys.stdout)


class NullTelemetry(Telemetry):
    """A no-op telemetry sink. The DEFAULT when no telemetry is configured, so the
    default build emits nothing and behaves exactly as before. Even the no-op funnels
    through the redactor conceptually (it simply discards), so wiring it can never leak."""

    def log(self, event: str, /, **fields: Any) -> None:  # noqa: D401 - no-op
        return None

    def increment(self, metric: str, *, value: int = 1, **labels: Any) -> None:
        return None

    def observe(self, metric: str, value: float, **labels: Any) -> None:
        return None
