"""Tier A: candidate verification runs over the SSRF-safe boundary, not urllib.

Every negative the discovery fetch refuses, the candidate-verification adapter
must also refuse — and surface it as a not-a-candidate FetchResult so a sitemap
locator stays zero-weight until safe verification actually succeeds.
"""

import socket

from tools.openva.safe_verify import build_safe_verify_fetcher


class _Resp:
    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._body = body
        self._pos = 0
        self.closed = False

    def set_timeout(self, seconds):
        pass

    def read(self, size):
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, *, dns=None, responses=None, open_error=None):
        self._dns = dns or {}
        self._responses = responses or {}
        self._open_error = open_error
        self.connected = []

    def resolve(self, host):
        if host not in self._dns:
            raise socket.gaierror(host)
        return list(self._dns[host])

    def open(self, *, url, ip, host, headers, deadline, clock):
        self.connected.append((url, ip))
        # The verification lane carries no credentials or cookies.
        assert "cookie" not in {k.lower() for k in headers}
        assert "authorization" not in {k.lower() for k in headers}
        if self._open_error is not None:
            raise self._open_error
        if url not in self._responses:
            raise AssertionError(f"unexpected fetch: {url}")
        return self._responses[url]


def _verify(transport, *, authority="vendor.example", **kwargs):
    kwargs.setdefault("max_redirects", 5)
    kwargs.setdefault("timeout_seconds", 20.0)
    return build_safe_verify_fetcher([authority], transport=transport, **kwargs)


def test_verify_private_dns_resolution_is_refused():
    t = FakeTransport(dns={"vendor.example": ["10.0.0.5"]})
    result = _verify(t)("https://vendor.example/trust")
    assert result.http_status is None
    assert "blocked_ip" in (result.error or "")
    assert t.connected == []  # never connected to the private address


def test_verify_mixed_public_private_dns_fails_closed():
    t = FakeTransport(dns={"vendor.example": ["93.184.216.34", "10.0.0.5"]})
    result = _verify(t)("https://vendor.example/trust")
    assert result.http_status is None
    assert "dns_resolved_blocked_ip" in (result.error or "")
    assert t.connected == []


def test_verify_off_authority_redirect_is_refused():
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"], "evil.test": ["198.51.100.7"]},
        responses={"https://vendor.example/trust": _Resp(302, {"Location": "https://evil.test/x"})},
    )
    result = _verify(t)("https://vendor.example/trust")
    assert result.http_status is None
    assert "off_authority" in (result.error or "")


def test_verify_redirect_to_private_address_is_refused():
    # The redirect target is ON-authority (a vendor subdomain) but resolves to a
    # private address, so it passes same-authority yet the per-hop DNS guard
    # still refuses it.
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"], "internal.vendor.example": ["10.1.2.3"]},
        responses={"https://vendor.example/trust": _Resp(302, {"Location": "https://internal.vendor.example/x"})},
    )
    result = _verify(t)("https://vendor.example/trust")
    assert result.http_status is None
    assert "blocked_ip" in (result.error or "")


def test_verify_credentials_in_url_are_refused():
    t = FakeTransport(dns={"vendor.example": ["93.184.216.34"]})
    result = _verify(t)("https://user:pass@vendor.example/trust")
    assert result.http_status is None
    assert "credentials_in_url_forbidden" in (result.error or "")
    assert t.connected == []


def test_verify_timeout_fails_closed():
    t = FakeTransport(dns={"vendor.example": ["93.184.216.34"]}, open_error=socket.timeout("timed out"))
    result = _verify(t, timeout_seconds=0.05)("https://vendor.example/trust")
    assert result.http_status is None
    assert "transport_error" in (result.error or "")


def test_verify_oversized_response_is_refused():
    body = b"x" * 5000  # over the 4 KiB verification byte bound
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/trust": _Resp(200, {"Content-Type": "text/html"}, body=body)},
    )
    result = _verify(t, max_bytes=4096)("https://vendor.example/trust")
    assert result.http_status is None
    assert "response_too_large" in (result.error or "")


def test_verify_success_returns_source_verification_fetchresult_shape():
    body = b"<html><head><title>Trust</title></head><body>data processing agreement processor</body></html>"
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={
            "https://vendor.example/trust": _Resp(
                200, {"Content-Type": "text/html; charset=utf-8", "ETag": '"abc"', "Content-Length": str(len(body))}, body=body
            )
        },
    )
    result = _verify(t)("https://vendor.example/trust")
    assert result.http_status == 200
    assert result.final_url == "https://vendor.example/trust"
    assert result.content_type == "text/html; charset=utf-8"
    assert result.etag == '"abc"'
    assert result.content_length == len(body)
    assert result.body_sample == body
    assert result.error is None


def test_verify_same_authority_redirect_is_followed():
    body = b"<html>data processing agreement processor</html>"
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={
            "https://vendor.example/trust": _Resp(301, {"Location": "https://vendor.example/legal/dpa"}),
            "https://vendor.example/legal/dpa": _Resp(200, {"Content-Type": "text/html"}, body=body),
        },
    )
    result = _verify(t)("https://vendor.example/trust")
    assert result.http_status == 200
    assert result.final_url == "https://vendor.example/legal/dpa"
    assert result.body_sample == body
