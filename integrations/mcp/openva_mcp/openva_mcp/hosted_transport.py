"""Provider-neutral client of the hosted verify transport (the ``/v1`` verify path).

WP-02I activates a live ``resolve_*`` MCP tool that resolves vendors **over the
hosted transport** rather than fetching anything itself. This module is that
client and nothing more: it submits a bounded batch of vendor IDENTITIES to the
hosted ``POST /v1/verify`` create endpoint, then polls ``GET /v1/verify/{job_id}``
with the returned one-time ``job_token`` until the job reaches a terminal state.

Boundaries this client enforces structurally (ADR-0001 / ADR-0003):

- **No arbitrary-URL fetch.** The client never fetches a caller-supplied URL. The
  only URL it ever contacts is the operator-configured hosted endpoint base; the
  request body carries vendor identities only (the SSRF-safe fetching, if any,
  happens server-side on the hosted service, never here).
- **Read-only / bounded.** It sends identity rows and an optional, capped
  ``source_types`` list; it never carries a write capability or workspace
  credential. Timeouts and poll counts are bounded so a hung endpoint cannot
  stall the tool indefinitely.
- **Credential isolation.** The one-time ``job_token`` is sent ONLY as an
  ``Authorization: Bearer`` header on the poll and is never logged, echoed in a
  result, or stored. This module performs no logging at all.

The HTTP function is injectable (``transport``) so tests drive a deterministic
fake with no real network, mirroring the ``RemoteSnapshotSource.fetch`` pattern.
The default transport uses ``urllib`` (no third-party SDK, provider-neutral) and
is only ever constructed when an operator has explicitly configured a hosted
endpoint — the default ``openva-mcp`` build never reaches it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

# Terminal job states per hosted-deployment.yaml job lifecycle. Polling stops once
# the job reaches either of these.
TERMINAL_STATES = frozenset({"completed", "failed"})

# Defaults are conservative: a live resolve is a short, bounded round-trip, not a
# long batch. These bound a misbehaving / hung endpoint without any background work.
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_MAX_POLLS = 60


class HostedTransportError(Exception):
    """A hosted-transport call failed (network, HTTP status, or protocol).

    The message is intentionally generic and never carries the job_token or the
    submitted vendor identities."""


@dataclass(frozen=True)
class HostedResponse:
    """A decoded hosted-transport HTTP response: status code + parsed JSON body."""

    status: int
    body: dict[str, Any]


# A transport is a function (method, url, json_body, bearer_token) -> HostedResponse.
# Injecting it keeps the network layer replaceable for deterministic tests.
Transport = Callable[[str, str, "dict[str, Any] | None", "str | None"], HostedResponse]


class TransportProtocol(Protocol):
    def __call__(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None,
        bearer_token: str | None,
    ) -> HostedResponse: ...


def _validate_endpoint(endpoint: str) -> str:
    """Validate the operator-configured hosted endpoint base and normalise it.

    Only http/https is accepted; embedded credentials and fragments are rejected so
    the endpoint stays plain operator configuration (mirrors the snapshot base-URL
    validator). This is the ONLY URL the client ever contacts — it is never derived
    from caller input."""
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https"):
        raise HostedTransportError("hosted endpoint must be an http(s) URL")
    if parts.username or parts.password:
        raise HostedTransportError("hosted endpoint must not embed credentials")
    if parts.fragment:
        raise HostedTransportError("hosted endpoint must not contain a fragment")
    if not parts.netloc:
        raise HostedTransportError("hosted endpoint has no host")
    return endpoint if endpoint.endswith("/") else endpoint + "/"


def _default_transport(connect_timeout: float) -> Transport:
    """A urllib-backed transport. No third-party SDK; provider-neutral.

    The bearer token, when present, is attached ONLY as an Authorization header and
    is never logged. The body is JSON. Only http(s) is reached (the endpoint was
    validated up front); the URL is operator config, never caller input."""

    def transport(
        method: str,
        url: str,
        json_body: dict[str, Any] | None,
        bearer_token: str | None,
    ) -> HostedResponse:
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        request = Request(url, data=data, headers=headers, method=method)  # noqa: S310 - validated http(s) operator endpoint
        try:
            with urlopen(request, timeout=connect_timeout) as response:  # noqa: S310
                raw = response.read()
                status = response.status
        except HTTPError as exc:  # a non-2xx status still carries a body we can decode
            raw = exc.read()
            status = exc.code
        except (URLError, TimeoutError, OSError) as exc:
            # Generic failure; never include the token or the submitted identities.
            raise HostedTransportError(f"hosted transport request failed: {type(exc).__name__}") from exc
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise HostedTransportError("hosted transport returned a non-JSON body") from exc
        if not isinstance(body, dict):
            raise HostedTransportError("hosted transport returned a non-object body")
        return HostedResponse(status=status, body=body)

    return transport


@dataclass(frozen=True)
class HostedTransportClient:
    """A bounded, read-only client of the hosted verify transport.

    Construct only when an operator has explicitly configured a hosted endpoint
    (off by default). ``resolve`` submits identity rows and returns the terminal
    job's status projection (including its ``result`` when completed). It NEVER
    fetches a caller-supplied URL and NEVER logs the job_token."""

    endpoint: str
    api_key: str | None = None
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    poll_interval: float = DEFAULT_POLL_INTERVAL
    max_polls: int = DEFAULT_MAX_POLLS
    transport: Transport | None = None
    sleep: Callable[[float], None] = time.sleep

    def _transport(self) -> Transport:
        return self.transport or _default_transport(self.connect_timeout)

    def _url(self, rel: str) -> str:
        return urljoin(_validate_endpoint(self.endpoint), rel)

    def resolve(
        self,
        rows: list[dict[str, Any]],
        source_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a verify job for ``rows`` and poll it to a terminal state.

        ``rows`` are bounded vendor-identity rows ONLY (no fetch-target URL). The
        hosted endpoint validates and re-bounds them; this client also passes
        ``source_types`` straight through (already capped by the caller / schema).
        Returns the terminal status projection dict from the hosted poll endpoint."""
        transport = self._transport()
        payload: dict[str, Any] = {"rows": rows}
        if source_types is not None:
            payload["source_types"] = source_types

        # Create: the API key (when configured) authorises submission via Bearer.
        created = transport("POST", self._url("v1/verify"), payload, self.api_key)
        if created.status == 200 and created.body.get("state") == "disabled":
            # The hosted verify path is kill-switched: surface a clean disabled signal
            # so the tool can fall back to the static snapshot. No job exists.
            raise HostedTransportError("hosted verify transport is disabled")
        if created.status not in (200, 201):
            raise HostedTransportError(f"hosted verify create failed with status {created.status}")
        job_id = created.body.get("job_id")
        job_token = created.body.get("job_token")
        if not isinstance(job_id, str) or not isinstance(job_token, str):
            raise HostedTransportError("hosted verify create returned an incomplete job handle")

        # Poll: authorised SOLELY by the one-time job_token (Bearer), never the API key.
        # The token is held only in this local variable and passed only as a header.
        poll_url = self._url(f"v1/verify/{job_id}")
        last: HostedResponse | None = None
        for attempt in range(self.max_polls):
            status_response = transport("GET", poll_url, None, job_token)
            last = status_response
            if status_response.status == 200:
                state = status_response.body.get("state")
                if state in TERMINAL_STATES:
                    return status_response.body
            elif status_response.status in (404, 410):
                raise HostedTransportError(f"hosted verify job is unavailable (status {status_response.status})")
            elif status_response.status == 401:
                raise HostedTransportError("hosted verify poll was not authorised")
            if attempt + 1 < self.max_polls:
                self.sleep(self.poll_interval)
        raise HostedTransportError(
            f"hosted verify job did not reach a terminal state within {self.max_polls} polls"
        )
