"""Tier A: the single production fetch boundary for scheduled discovery.

Sitemaps, sitemap indexes and robots.txt are fetched from vendor-controlled
hosts over the public internet. That makes the fetch path an SSRF surface, so
every guarantee here is enforced at the boundary, never merely documented:

- only ``http`` / ``https``; URLs carrying credentials are rejected outright;
- the host is DNS-resolved BEFORE any connection, and the request is pinned to
  a validated resolved address. ``resolve_dns=False`` static checks are a
  pre-filter, never the SSRF guard: a name that resolves to a private,
  loopback, link-local, multicast, reserved or unspecified address is rejected;
- because the connection is pinned to the address we validated, a name that
  rebinds (or split-horizon resolves) between validation and connection cannot
  reach a blocked address — and if ANY resolved address is blocked we refuse,
  so a public+private answer set fails closed;
- every redirect hop is re-validated identically (scheme, credentials, static
  safety, same-authority, DNS-resolved address). Redirects are capped;
- requests carry a deterministic user agent and no cookies, Authorization, or
  other authenticated state;
- the response body is read under a hard byte cap while streaming, so an
  oversized (or oversized-compressed) body is abandoned before it is buffered;
  a declared ``Content-Length`` over the cap is refused before the first read;
- a per-request timeout bounds the whole exchange.

The transport (DNS + socket) is injected so tests drive the negatives through a
fake transport rather than fabricated ``FetchResult`` objects, and so the SSRF
checks above run for real in those tests. ``SocketTransport`` is the production
implementation. ``SafeFetcher.fetch`` is the ``Fetcher`` callable consumed by
``sitemap_discovery`` (for both robots.txt and sitemaps); a per-vendor instance
is bound to that vendor's official domains for same-authority enforcement.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Iterator, Mapping, Protocol
from urllib.parse import urljoin, urlsplit

from tools.openva.sitemap_discovery import FetchResult, SitemapDiscoveryError
from tools.openva.source_authority import is_on_official_domain
from tools.openva.url_safety import (
    ALLOWED_SCHEMES,
    is_blocked_ip,
    is_ip_literal,
    normalize_host,
    validate_url_safety,
)

USER_AGENT = "OpenVA-Discovery"
_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_CHUNK = 65536


class SafeFetchError(SitemapDiscoveryError):
    """A fetch refused or aborted by the boundary (unsafe target, bound hit).

    Subclasses ``SitemapDiscoveryError`` so the bounded sitemap pipeline records
    it as a rejected locator rather than crashing the vendor's discovery run.
    """


class RawResponse(Protocol):
    """One in-flight HTTP response, streamed and closeable."""

    status: int
    headers: Mapping[str, str]  # header names lower-cased

    def stream(self, chunk_size: int) -> Iterator[bytes]: ...

    def close(self) -> None: ...


class Transport(Protocol):
    """DNS + connection primitives, injected so tests exercise the real guards."""

    def resolve(self, host: str) -> list[str]:
        """Return the resolved IP addresses (as strings) for ``host``."""

    def open(
        self, *, url: str, ip: str, host: str, headers: Mapping[str, str], timeout: float
    ) -> RawResponse:
        """Open ``url`` by connecting to the pinned ``ip`` (no re-resolution)."""


@dataclass(frozen=True)
class FetchPolicy:
    max_redirects: int = 5
    timeout_seconds: float = 20.0
    max_response_bytes: int = 5_000_000
    user_agent: str = USER_AGENT


class SafeFetcher:
    """SSRF-safe, bounded GET fetcher; ``fetch`` is the injectable ``Fetcher``."""

    def __init__(
        self,
        transport: Transport,
        policy: FetchPolicy | None = None,
        *,
        same_authority_domains: list[str] | None = None,
    ) -> None:
        self.transport = transport
        self.policy = policy or FetchPolicy()
        # None means "no same-authority restriction"; an empty list would reject
        # everything, which is never what a caller means, so treat it as None.
        self.same_authority_domains = list(same_authority_domains) if same_authority_domains else None

    def fetch(self, url: str) -> FetchResult:
        redirects = 0
        current = url
        while True:
            self._validate_request_url(current)
            ip = self._resolve_and_pin(current)
            host = normalize_host(urlsplit(current).hostname) or ""
            try:
                response = self.transport.open(
                    url=current,
                    ip=ip,
                    host=host,
                    headers=self._request_headers(),
                    timeout=self.policy.timeout_seconds,
                )
            except OSError as exc:  # connect/TLS/timeout failures fail closed
                raise SafeFetchError(f"transport_error:{type(exc).__name__}") from exc
            try:
                status = int(response.status)
                location = response.headers.get("location")
                if status in _REDIRECT_STATUS and location:
                    redirects += 1
                    if redirects > self.policy.max_redirects:
                        raise SafeFetchError("redirect_overflow")
                    current = urljoin(current, location)
                    continue  # re-validate the next hop from the top of the loop
                body, encoding = self._read_capped(response)
                return FetchResult(
                    status=status,
                    final_url=current,
                    body=body,
                    content_encoding=encoding,
                    redirects=redirects,
                )
            finally:
                response.close()

    # --- request construction ------------------------------------------------

    def _request_headers(self) -> dict[str, str]:
        # Deterministic, identity-free: no cookies, no Authorization, no UA drift.
        return {
            "User-Agent": self.policy.user_agent,
            "Accept": "application/xml,text/xml,text/plain,*/*",
            "Accept-Encoding": "gzip, identity",
            "Connection": "close",
        }

    # --- SSRF guards ---------------------------------------------------------

    def _validate_request_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ALLOWED_SCHEMES:
            raise SafeFetchError(f"scheme_not_allowed:{parts.scheme or '<missing>'}")
        if parts.username or parts.password:
            raise SafeFetchError("credentials_in_url_forbidden")
        host = normalize_host(parts.hostname)
        if not host:
            raise SafeFetchError("host_missing")
        # Static pre-filter (blocked names, blocked IP literals). NOT the SSRF
        # guard on its own — DNS resolution below is.
        failures = validate_url_safety(url, resolve_dns=False)
        if failures:
            raise SafeFetchError(failures[0])
        if self.same_authority_domains is not None and not is_on_official_domain(
            url, self.same_authority_domains
        ):
            raise SafeFetchError("off_authority")

    def _resolve_and_pin(self, url: str) -> str:
        """Resolve the host, refuse if any address is blocked, pin the first."""
        host = normalize_host(urlsplit(url).hostname) or ""
        if is_ip_literal(host):
            ip = ipaddress.ip_address(host.strip("[]"))
            if is_blocked_ip(ip):
                raise SafeFetchError("blocked_ip_literal")
            return str(ip)
        try:
            addresses = self.transport.resolve(host)
        except Exception as exc:  # DNS failure is fail-closed, never a soft pass
            raise SafeFetchError(f"dns_resolution_failed:{host}") from exc
        if not addresses:
            raise SafeFetchError(f"dns_no_addresses:{host}")
        pinned: str | None = None
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise SafeFetchError(f"dns_returned_non_ip:{address}") from exc
            if is_blocked_ip(ip):
                # Any blocked answer fails the whole set (split-horizon / rebind).
                raise SafeFetchError(f"dns_resolved_blocked_ip:{ip}")
            if pinned is None:
                pinned = str(ip)
        assert pinned is not None
        return pinned

    # --- bounded body read ---------------------------------------------------

    def _read_capped(self, response: RawResponse) -> tuple[bytes, str | None]:
        cap = self.policy.max_response_bytes
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > cap:
                    raise SafeFetchError("response_too_large")
            except ValueError:
                pass  # unparseable Content-Length: rely on the streaming cap
        buffer = bytearray()
        try:
            for chunk in response.stream(_CHUNK):
                buffer += chunk
                if len(buffer) > cap:
                    # Abandon before fully buffering: the compressed/wire bytes
                    # are bounded here, decompressed bytes bounded downstream.
                    raise SafeFetchError("response_too_large")
        except OSError as exc:  # mid-body timeout / reset fails closed
            raise SafeFetchError(f"transport_error:{type(exc).__name__}") from exc
        encoding = response.headers.get("content-encoding")
        return bytes(buffer), (encoding or None)


# --- production transport ----------------------------------------------------


class _HttpRawResponse:
    """Adapts ``http.client.HTTPResponse`` to the ``RawResponse`` protocol."""

    def __init__(self, response: http.client.HTTPResponse, connection: http.client.HTTPConnection) -> None:
        self._response = response
        self._connection = connection
        self.status = response.status
        self.headers = {k.lower(): v for k, v in response.getheaders()}

    def stream(self, chunk_size: int) -> Iterator[bytes]:
        while True:
            chunk = self._response.read(chunk_size)
            if not chunk:
                return
            yield chunk

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


class SocketTransport:
    """Production DNS + socket transport pinning the connection to a chosen IP."""

    def resolve(self, host: str) -> list[str]:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        # De-duplicate while preserving order; we validate every distinct answer.
        seen: list[str] = []
        for info in infos:
            address = info[4][0]
            if address not in seen:
                seen.append(address)
        return seen

    def open(
        self, *, url: str, ip: str, host: str, headers: Mapping[str, str], timeout: float
    ) -> RawResponse:
        parts = urlsplit(url)
        scheme = parts.scheme
        port = parts.port or (443 if scheme == "https" else 80)
        # Connect to the validated IP literal (create_connection does not
        # re-resolve a literal), so the socket cannot rebind to another address.
        raw = socket.create_connection((ip, port), timeout=timeout)
        try:
            if scheme == "https":
                context = ssl.create_default_context()
                # SNI + certificate validation use the real hostname, not the IP.
                sock: socket.socket = context.wrap_socket(raw, server_hostname=host)
            else:
                sock = raw
        except Exception:
            raw.close()
            raise
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.sock = sock
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        request_headers = dict(headers)
        request_headers.setdefault("Host", host)
        connection.request("GET", path, headers=request_headers)
        response = connection.getresponse()
        return _HttpRawResponse(response, connection)


def build_safe_fetcher(
    official_domains: list[str],
    *,
    max_redirects: int,
    timeout_seconds: float,
    max_response_bytes: int,
    transport: Transport | None = None,
) -> SafeFetcher:
    """Construct the production fetcher bound to a vendor's own authority."""
    policy = FetchPolicy(
        max_redirects=max_redirects,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )
    return SafeFetcher(
        transport or SocketTransport(),
        policy,
        same_authority_domains=official_domains,
    )
