"""Tier A: the production fetch boundary, driven through an injected transport.

These exercise the SSRF and bound guards for real — the negatives come from the
transport (DNS answers, redirects, streamed bytes, timeouts), never from
fabricated FetchResult objects, so the checks under test actually run.
"""

import http.client
import socket

import pytest

from tools.openva.safe_fetch import (
    FetchPolicy,
    SafeFetcher,
    SafeFetchError,
)


class _Resp:
    """A fake in-flight response read in caller-sized chunks (RawResponse)."""

    def __init__(self, status, headers=None, body=b"", *, chunks=None, raise_mid=None, read_error=None):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._body = b"".join(chunks) if chunks is not None else body
        self._pos = 0
        self._raise_mid = raise_mid  # raise socket.timeout on the Nth read (0-based)
        self._read_error = read_error  # raise this exception on the first read
        self._reads = 0
        self.closed = False
        self.timeouts = []  # records every set_timeout (proves per-read clamping)

    def set_timeout(self, seconds):
        self.timeouts.append(seconds)

    def read(self, size):
        if self._read_error is not None and self._reads == 0:
            raise self._read_error
        if self._raise_mid is not None and self._reads == self._raise_mid:
            raise socket.timeout("read timed out")
        self._reads += 1
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

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

    def open(self, *, url, ip, host, headers, deadline, clock):
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


class _Clock:
    """Monotonic fake clock: returns queued values, repeating the last forever."""

    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    def __call__(self):
        value = self._values[min(self._i, len(self._values) - 1)]
        self._i += 1
        return value


def _fetcher(transport, *, same_authority=None, clock=None, **policy):
    return SafeFetcher(
        transport,
        FetchPolicy(**policy) if policy else None,
        same_authority_domains=same_authority,
        clock=clock,
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


# --- same-authority floor (single-element gate) ------------------------------


def test_single_element_same_authority_refuses_off_host_fetch_before_any_network():
    # A one-element authority list keeps the gate ON: a fetch to a DIFFERENT host
    # is refused as off_authority BEFORE any DNS or connection. No transport
    # entries are needed precisely because the authority check precedes them.
    t = FakeTransport(dns={})
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, same_authority=["vendor.example"]).fetch("https://other.example/robots.txt")
    assert "off_authority" in str(exc.value)
    assert t.resolved == []  # authority gate fired before resolution
    assert t.connected == []


def test_single_element_same_authority_refuses_redirect_to_other_host():
    # The floor is re-enforced on every hop: a 302 whose Location points to a
    # different host is refused as off_authority on the redirect hop.
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={
            "https://vendor.example/x": _Resp(302, {"Location": "https://other.example/y"}),
        },
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, same_authority=["vendor.example"]).fetch("https://vendor.example/x")
    assert "off_authority" in str(exc.value)
    assert [u for u, _ in t.connected] == ["https://vendor.example/x"]  # only the first hop opened


def test_empty_same_authority_list_coerces_to_none_disabling_the_gate():
    # TRAP: an empty list would reject every URL, which is never what a caller
    # means, so SafeFetcher coerces [] -> None. This documents WHY call sites
    # must bind a real authority and never pass [] (which would silently DISABLE
    # the same-authority floor, not lock it shut).
    fetcher = SafeFetcher(FakeTransport(dns={}), same_authority_domains=[])
    assert fetcher.same_authority_domains is None


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


def test_oversized_identity_response_is_refused_while_streaming():
    big = [b"x" * 1024] * 8  # 8 KiB streamed, identity cap 4 KiB
    served = _Resp(200, chunks=big)
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/robots.txt": served},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_decompressed_bytes=4096).fetch("https://vendor.example/robots.txt")
    assert "response_too_large" in str(exc.value)
    assert served.closed is True  # response closed on the limit failure


def test_gzip_response_is_bounded_by_the_compressed_cap_below_the_decompressed_cap():
    # 8 KiB gzip wire body: trips the 4 KiB compressed cap even though the 10 MB
    # decompressed cap is far higher. This is the exact gap the split closes.
    chunks = [b"x" * 1024] * 8
    served = _Resp(200, {"Content-Encoding": "gzip"}, chunks=chunks)
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml.gz": served},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_compressed_bytes=4096, max_decompressed_bytes=10_000_000).fetch(
            "https://vendor.example/sitemap.xml.gz"
        )
    assert "response_too_large" in str(exc.value)
    assert served.closed is True


def test_identity_body_of_the_same_size_passes_under_the_decompressed_cap():
    chunks = [b"x" * 1024] * 8  # identical 8 KiB, but identity -> decompressed cap
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": _Resp(200, chunks=chunks)},
    )
    result = _fetcher(t, max_compressed_bytes=4096, max_decompressed_bytes=10_000_000).fetch(
        "https://vendor.example/sitemap.xml"
    )
    assert result.status == 200 and len(result.body) == 8192


def test_gzip_magic_without_header_switches_to_the_compressed_cap():
    chunks = [b"\x1f\x8b" + b"x" * 1022] + [b"x" * 1024] * 7  # gzip magic, no header
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": _Resp(200, chunks=chunks)},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_compressed_bytes=4096, max_decompressed_bytes=10_000_000).fetch(
            "https://vendor.example/sitemap.xml"
        )
    assert "response_too_large" in str(exc.value)


def test_declared_content_length_over_compressed_cap_refused_before_read():
    served = _Resp(200, {"Content-Encoding": "gzip", "Content-Length": "10000000"}, body=b"unused")
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml.gz": served},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_compressed_bytes=4096, max_decompressed_bytes=10_000_000).fetch(
            "https://vendor.example/sitemap.xml.gz"
        )
    assert "response_too_large" in str(exc.value)


def test_oversized_streamed_sitemap_without_content_length_is_refused():
    huge = [b"y" * 65536] * 100  # no Content-Length header at all
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": _Resp(200, chunks=huge)},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_decompressed_bytes=1_000_000).fetch("https://vendor.example/sitemap.xml")
    assert "response_too_large" in str(exc.value)


# --- whole-exchange deadline -------------------------------------------------


def test_slow_trickle_aborts_on_the_whole_exchange_deadline():
    # Every read is tiny (well under the byte cap) and no single read times out,
    # but total elapsed time exceeds the deadline mid-stream. The small compressed
    # cap forces multiple small reads; the injected clock stays within budget
    # through resolution/open and the first two reads, then jumps past the deadline.
    served = _Resp(200, chunks=[b"x" * 16] * 50)  # 800 bytes total
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": served},
    )
    # Calls: deadline, loop-top, resolve, after-resolve, after-open, then per read.
    clock = _Clock([0, 0, 0, 0, 0, 0, 0, 100])
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(
            t, timeout_seconds=10, clock=clock, max_compressed_bytes=100, max_decompressed_bytes=10_000_000
        ).fetch("https://vendor.example/sitemap.xml")
    assert "request_deadline_exceeded" in str(exc.value)
    assert served.closed is True  # closed on the deadline failure
    assert len(served.timeouts) >= 2  # the read timeout was re-clamped per read


def test_redirects_consume_the_shared_overall_deadline():
    # Two redirect hops each stay within their per-op budget, but the SHARED
    # deadline (never reset per hop) is exhausted before the third hop fetches.
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={
            "https://vendor.example/a": _Resp(301, {"Location": "https://vendor.example/b"}),
            "https://vendor.example/b": _Resp(301, {"Location": "https://vendor.example/c"}),
            "https://vendor.example/c": _Resp(200, body=b"final"),
        },
    )
    # 4 deadline checks per hop (loop-top, resolve, after-resolve, after-open).
    clock = _Clock([0, 0, 0, 0, 0, 0, 0, 0, 0, 100])  # hops a,b ok; hop c loop-top trips
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, same_authority=["vendor.example"], timeout_seconds=10, clock=clock).fetch(
            "https://vendor.example/a"
        )
    assert "request_deadline_exceeded" in str(exc.value)
    # Hops a and b were fetched; c was never connected (deadline tripped first).
    assert [u for u, _ in t.connected] == ["https://vendor.example/a", "https://vendor.example/b"]


def test_redirect_hop_trips_the_monotonic_whole_exchange_deadline():
    # A single redirect hop: the first hop fetches within budget, but aggregate
    # elapsed time crosses the shared monotonic deadline before the SECOND hop's
    # body is read, so it fails closed with request_deadline_exceeded rather than
    # resetting the budget per hop. Same-authority so the redirect itself is fine;
    # only the deadline ends the exchange.
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={
            "https://vendor.example/a": _Resp(301, {"Location": "https://vendor.example/b"}),
            "https://vendor.example/b": _Resp(200, body=b"final"),
        },
    )
    # Hop a: deadline-init, loop-top, resolve, after-resolve, after-open all at 0.
    # Hop b: loop-top check jumps past the 10s deadline (elapsed 100s).
    clock = _Clock([0, 0, 0, 0, 0, 100])
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, same_authority=["vendor.example"], timeout_seconds=10, clock=clock).fetch(
            "https://vendor.example/a"
        )
    assert "request_deadline_exceeded" in str(exc.value)
    # Hop a was connected; hop b never was (the shared deadline tripped first).
    assert [u for u, _ in t.connected] == ["https://vendor.example/a"]


def test_hung_resolver_is_bounded_by_the_deadline():
    # DNS resolution is part of the whole-exchange budget: a resolver that blocks
    # past the deadline fails closed instead of hanging unbounded.
    import threading as _threading

    release = _threading.Event()

    class HangingTransport:
        def resolve(self, host):
            release.wait(5)  # blocks well past the (tiny) deadline
            return ["93.184.216.34"]

        def open(self, **kwargs):
            raise AssertionError("must never connect when resolution overruns")

    clock = _Clock([0.0, 0.0, 0.001])  # deadline 0.05s; ~0.049s left at resolve
    fetcher = SafeFetcher(HangingTransport(), FetchPolicy(timeout_seconds=0.05), clock=clock)
    try:
        with pytest.raises(SafeFetchError) as exc:
            fetcher.fetch("https://vendor.example/robots.txt")
        assert "request_deadline_exceeded" in str(exc.value)
    finally:
        release.set()  # let the daemon resolver thread exit


def test_socket_transport_enforces_a_hard_aggregate_deadline(monkeypatch):
    # Each blocking phase (connect, request send, header read) is given only the
    # REMAINING budget, recomputed each time, so their aggregate cannot exceed the
    # configured deadline: a phase that would push past it fails before it starts.
    import tools.openva.safe_fetch as sf

    state = {"t": 0.0}
    seen = []

    class FakeSock:
        def settimeout(self, t):
            seen.append(("settimeout", round(t, 3)))

        def close(self):
            seen.append(("sock_close",))

    def fake_connect(addr, timeout=None):
        seen.append(("connect", round(timeout, 3)))
        state["t"] += 4  # the connect phase consumes 4s of the budget
        return FakeSock()

    class FakeResponse:
        status = 200

        def getheaders(self):
            return []

        def read(self, n):
            return b""

        def close(self):
            pass

    class FakeConn:
        def __init__(self, host, port, timeout=None):
            seen.append(("conn", round(timeout, 3)))
            self.sock = None

        def request(self, *a, **k):
            seen.append(("request",))
            state["t"] += 4  # the request phase consumes another 4s

        def getresponse(self):
            seen.append(("getresponse",))
            return FakeResponse()

        def close(self):
            seen.append(("conn_close",))

    monkeypatch.setattr(sf.socket, "create_connection", fake_connect)
    monkeypatch.setattr(sf.http.client, "HTTPConnection", FakeConn)

    transport = sf.SocketTransport()
    with pytest.raises(sf.SafeFetchError) as exc:
        transport.open(
            url="http://vendor.example/x",
            ip="93.184.216.34",
            host="vendor.example",
            headers={"Host": "vendor.example"},
            deadline=7.0,  # connect(7s budget) + request(4s) overruns before headers
            clock=lambda: state["t"],
        )
    assert "request_deadline_exceeded" in str(exc.value)
    # connect saw the full 7s remaining, the request phase saw the reduced 3s.
    budgets = [entry[1] for entry in seen if entry[0] in ("connect", "conn")]
    assert budgets == [7.0, 3.0]
    assert ("conn_close",) in seen  # the connection was closed on the failure


def test_socket_transport_budgets_the_tls_phase(monkeypatch):
    # The https TLS handshake is a budgeted phase: it receives the remaining
    # budget after connect, and on a budget-exhausting TLS phase it fails closed
    # and closes the raw socket (no descriptor leak).
    import tools.openva.safe_fetch as sf

    state = {"t": 0.0}
    events = []

    class FakeRaw:
        def settimeout(self, t):
            events.append(("raw_settimeout", round(t, 3)))

        def close(self):
            events.append(("raw_close",))

    def fake_connect(addr, timeout=None):
        events.append(("connect", round(timeout, 3)))
        state["t"] += 6  # connect consumes 6s of a 5s deadline -> TLS has no budget
        return FakeRaw()

    class FakeCtx:
        def wrap_socket(self, sock, server_hostname=None):
            events.append(("wrap", server_hostname))
            return sock

    monkeypatch.setattr(sf.socket, "create_connection", fake_connect)
    monkeypatch.setattr(sf.ssl, "create_default_context", lambda: FakeCtx())

    transport = sf.SocketTransport()
    with pytest.raises(sf.SafeFetchError) as exc:
        transport.open(
            url="https://vendor.example/x",
            ip="93.184.216.34",
            host="vendor.example",
            headers={"Host": "vendor.example"},
            deadline=5.0,
            clock=lambda: state["t"],
        )
    assert "request_deadline_exceeded:tls" in str(exc.value)
    assert ("wrap", "vendor.example") not in events  # TLS never started
    assert ("raw_close",) in events  # the raw socket was closed on the failure


def test_socket_transport_tls_phase_receives_the_reduced_budget(monkeypatch):
    import tools.openva.safe_fetch as sf

    state = {"t": 0.0}
    events = []

    class FakeRaw:
        def settimeout(self, t):
            events.append(("raw_settimeout", round(t, 3)))

        def close(self):
            pass

    class FakeSock:
        def settimeout(self, t):
            pass

        def close(self):
            pass

    def fake_connect(addr, timeout=None):
        events.append(("connect", round(timeout, 3)))
        state["t"] += 1
        return FakeRaw()

    class FakeCtx:
        def wrap_socket(self, sock, server_hostname=None):
            events.append(("wrap", server_hostname))
            return FakeSock()

    class FakeResp:
        status = 200

        def getheaders(self):
            return []

        def read(self, n):
            return b""

        def close(self):
            pass

    class FakeConn:
        def __init__(self, host, port, timeout=None):
            self.sock = None

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return FakeResp()

        def close(self):
            pass

    monkeypatch.setattr(sf.socket, "create_connection", fake_connect)
    monkeypatch.setattr(sf.ssl, "create_default_context", lambda: FakeCtx())
    monkeypatch.setattr(sf.http.client, "HTTPConnection", FakeConn)

    transport = sf.SocketTransport()
    response = transport.open(
        url="https://vendor.example/x",
        ip="93.184.216.34",
        host="vendor.example",
        headers={"Host": "vendor.example"},
        deadline=100.0,
        clock=lambda: state["t"],
    )
    assert response.status == 200
    assert ("connect", 100.0) in events  # connect saw the full budget
    assert ("raw_settimeout", 99.0) in events  # TLS handshake clamped to the reduced remaining
    assert ("wrap", "vendor.example") in events  # SNI uses the real hostname


def test_compressed_cap_below_one_chunk_is_honored():
    # A gzip body (via magic, no header) with a sub-default-chunk compressed cap:
    # reads are sized to the cap so buffering never exceeds it by more than a read.
    body = b"\x1f\x8b" + b"x" * 9998  # 10 KiB, gzip magic, far over a 4 KiB cap
    served = _Resp(200, body=body)
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": served},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t, max_compressed_bytes=4096, max_decompressed_bytes=10_000_000).fetch(
            "https://vendor.example/sitemap.xml"
        )
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


def test_http_protocol_exception_on_open_fails_closed():
    # BadStatusLine / LineTooLong etc. are HTTPException, NOT OSError; they must
    # still be normalized to a bounded SafeFetchError, not escape.
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        open_error=http.client.BadStatusLine("garbage line"),
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://vendor.example/robots.txt")
    assert "transport_error:BadStatusLine" in str(exc.value)


def test_incomplete_read_during_body_fails_closed():
    served = _Resp(200, read_error=http.client.IncompleteRead(b"partial"))
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/sitemap.xml": served},
    )
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch("https://vendor.example/sitemap.xml")
    assert "transport_error:IncompleteRead" in str(exc.value)
    assert served.closed is True  # response closed on the protocol failure


@pytest.mark.parametrize(
    "url",
    ["https://[:::]/x", "https://[gg::1]/x", "https://vendor.example:99999/x"],
)
def test_malformed_url_is_a_bounded_rejection(url):
    # Bad IPv6 brackets / out-of-range port raise ValueError from urlsplit; the
    # boundary normalizes them to a bounded SafeFetchError instead of escaping.
    t = FakeTransport(dns={"vendor.example": ["93.184.216.34"]})
    with pytest.raises(SafeFetchError) as exc:
        _fetcher(t).fetch(url)
    assert "malformed" in str(exc.value)
    assert t.connected == []  # never connected


def test_response_is_closed_even_on_success():
    served = _Resp(200, body=b"ok")
    t = FakeTransport(
        dns={"vendor.example": ["93.184.216.34"]},
        responses={"https://vendor.example/robots.txt": served},
    )
    _fetcher(t).fetch("https://vendor.example/robots.txt")
    assert served.closed is True
