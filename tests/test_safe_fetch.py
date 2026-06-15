"""Tier A: the production fetch boundary, driven through an injected transport.

These exercise the SSRF and bound guards for real — the negatives come from the
transport (DNS answers, redirects, streamed bytes, timeouts), never from
fabricated FetchResult objects, so the checks under test actually run.
"""

import socket

import pytest

from tools.openva.safe_fetch import (
    FetchPolicy,
    SafeFetcher,
    SafeFetchError,
)


class _Resp:
    def __init__(self, status, headers=None, body=b"", *, chunks=None, raise_mid=None):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._chunks = chunks if chunks is not None else ([body] if body else [])
        self._raise_mid = raise_mid
        self.closed = False

    def stream(self, chunk_size):
        for i, chunk in enumerate(self._chunks):
            if self._raise_mid is not None and i == self._raise_mid:
                raise socket.timeout("read timed out")
            yield chunk

    def close(self):
        self.closed = True


class FakeTransport:
    """Serves canned DNS answers and responses; records pinned connections."""

    def __init__(self, *, dns=None, responses=None, open_error=None):
        self._dns = dns or {}
        self._responses = responses or {}
        self._open_error = open_error
        self.resolved: list[str] = []
        self.connected: list[tuple[str, str]] = []  # (url, pinned_ip)

    def resolve(self, host):
        self.resolved.append(host)
        if host not in self._dns:
            raise socket.gaierror(f"no DNS for {host}")
        return list(self._dns[host])

    def open(self, *, url, ip, host, headers, timeout):
        # Prove the boundary pinned the connection to a validated address and
        # never leaks credentials/cookies.
        self.connected.append((url, ip))
        assert "cookie" not in {k.lower() for k in headers}
        assert "authorization" not in {k.lower() for k in headers}
        assert headers["User-Agent"] == "OpenVA-Discovery"
        if self._open_error is not None:
            raise self._open_error
        if url not in self._responses:
            raise AssertionError(f"unexpected fetch: {url}")
        return self._responses[url]


def _fetcher(transport, *, same_authority=None, **policy):
    return SafeFetcher(
        transport,
        FetchPolicy(**policy) if policy else None,
        same_authority_domains=same_authority,
    )


# --- happy path --------------------------------------------------------------


def test_fetch_returns_result_and_pins_validated_ip():
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/robots.txt": _Resp(200, body=b"User-agent: *\n")},
    )
    result = _fetcher(t).fetch("https://vendor.example/robots.txt")
    assert result.status == 200
    assert result.final_url == "https://vendor.example/robots.txt"
    assert result.body == b"User-agent: *\n"
    assert t.connected == [("https://vendor.example/robots.txt", "93.184.216.34")]


def test_same_authority_redirect_is_followed_and_counted():
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={
            "https://vendor.example/sitemap.xml": _Resp(301, {"Location": "https://vendor.example/sm/final.xml"}),
            "https://vendor.example/sm/final.xml": _Resp(200, body=b"<urlset/>"),
        },
    )
    result = _fetcher(t, same_authority=["vendor.example"]).fetch("https://vendor.example/sitemap.xml")
    assert result.status == 200
    assert result.final_url == "https://vendor.example/sm/final.xml"
    assert result.redirects == 1


# --- DNS / SSRF negatives ----------------------------------------------------


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fe80::1"],
)
def test_dns_resolving_to_blocked_address_is_refused(address):
    t = FakeTransport(dns={"vendor.example": [address]})
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://vendor.example/robots.txt")
    assert "blocked_ip" in str(exc.value)
    assert t.connected == []  # never connected


def test_any_blocked_address_in_the_set_fails_closed_rebinding():
    # A public+private answer set (DNS rebinding / split-horizon) is refused
    # wholesale; we never pick the "good" answer and connect.
    t = FakeTransport(dns={"vendor.example": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://vendor.example/robots.txt")
    assert "dns_resolved_blocked_ip" in str(exc.value)
    assert t.connected == []


def test_unresolvable_host_fails_closed():
    t = FakeTransport(dns={})
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://nope.example/robots.txt")
    assert "dns_resolution_failed" in str(exc.value)


def test_blocked_ip_literal_is_refused_without_dns():
    t = FakeTransport(dns={})
    with pytest.raises(SafeFetchError):
        _fetcher(t).fetch("http://127.0.0.1/robots.txt")
    assert t.resolved == []  # static block, no resolution attempted


@pytest.mark.parametrize("url", ["ftp://vendor.example/x", "file:///etc/passwd"])
def test_non_http_scheme_is_refused(url):
    t = FakeTransport(dns={"vendor.example": ["93.184.216.34"]})
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch(url)
    assert "scheme_not_allowed" in str(exc.value)


def test_credentials_in_url_are_refused():
    t = FakeTransport(dns={"vendor.example": ["93.184.216.34"]})
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://user:pass@vendor.example/robots.txt")
    assert "credentials_in_url_forbidden" in str(exc.value)


# --- redirect negatives ------------------------------------------------------


def test_robots_redirect_off_authority_is_refused():
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"], "evil.test": ["198.51.100.7"]},
        responses={
            "https://vendor.example/robots.txt": _Resp(302, {"Location": "https://evil.test/robots.txt"}),
        },
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, same_authority=["vendor.example"]).fetch("https://vendor.example/robots.txt")
    assert "off_authority" in str(exc.value)


def test_redirect_to_blocked_address_is_refused_on_the_hop():
    # Off-authority restriction absent, but the redirect target resolves to a
    # private address: the per-hop DNS guard still refuses it.
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"], "internal.example": ["10.1.2.3"]},
        responses={
            "https://vendor.example/robots.txt": _Resp(302, {"Location": "https://internal.example/x"}),
        },
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://vendor.example/robots.txt")
    assert "blocked_ip" in str(exc.value)


def test_redirect_overflow_is_refused():
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={
            "https://vendor.example/a": _Resp(301, {"Location": "https://vendor.example/b"}),
            "https://vendor.example/b": _Resp(301, {"Location": "https://vendor.example/c"}),
            "https://vendor.example/c": _Resp(301, {"Location": "https://vendor.example/d"}),
        },
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, same_authority=["vendor.example"], max_redirects=2).fetch("https://vendor.example/a")
    assert "redirect_overflow" in str(exc.value)


# --- size / timeout negatives ------------------------------------------------


def test_oversized_robots_response_is_refused_while_streaming():
    big = [b"x" * 1024] * 8  # 8 KiB streamed, cap 4 KiB
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/robots.txt": _Resp(200, chunks=big)},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_response_bytes=4096).fetch("https://vendor.example/robots.txt")
    assert "response_too_large" in str(exc.value)


def test_declared_content_length_over_cap_refused_before_read():
    served = _Resp(200, {"Content-Length": "10000000"}, body=b"unused")
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": served},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_response_bytes=4096).fetch("https://vendor.example/sitemap.xml")
    assert "response_too_large" in str(exc.value)


def test_oversized_streamed_sitemap_without_content_length_is_refused():
    huge = [b"y" * 65536] * 100  # no Content-Length header at all
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": _Resp(200, chunks=huge)},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_response_bytes=1_000_000).fetch("https://vendor.example/sitemap.xml")
    assert "response_too_large" in str(exc.value)


def test_open_timeout_fails_closed():
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        open_error=socket.timeout("connect timed out"),
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, timeout_seconds=0.01).fetch("https://vendor.example/robots.txt")
    assert "transport_error" in str(exc.value)


def test_mid_body_timeout_fails_closed():
    served = _Resp(200, chunks=[b"a" * 1024, b"b" * 1024], raise_mid=1)
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": served},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://vendor.example/sitemap.xml")
    assert "transport_error" in str(exc.value)


def test_response_is_closed_even_on_success():
    served = _Resp(200, body=b"ok")
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/robots.txt": served},
    )
    _fetcher(t).fetch("https://vendor.example/robots.txt")
    assert served.closed is True
