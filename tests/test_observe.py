import socket

import pytest

from tools.openva import observe
from tools.openva.observe import fetch_public, observation_for_source

DOMAINS = ["example.com"]


# --- safe-fetch test harness (mirrors tests/test_safe_fetch.py) ----------------
class _Resp:
    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._body = body
        self._pos = 0

    def set_timeout(self, seconds):
        pass

    def read(self, size):
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self):
        pass


class FakeTransport:
    """Serves canned DNS answers and responses; never touches the network."""

    def __init__(self, *, dns=None, responses=None, open_error=None):
        self._dns = dns or {}
        self._responses = responses or {}
        self._open_error = open_error

    def resolve(self, host):
        if host not in self._dns:
            raise socket.gaierror(f"no DNS for {host}")
        return list(self._dns[host])

    def open(self, *, url, ip, host, headers, deadline, clock):
        assert "cookie" not in {k.lower() for k in headers}
        assert "authorization" not in {k.lower() for k in headers}
        if self._open_error is not None:
            raise self._open_error
        if url not in self._responses:
            raise AssertionError(f"unexpected fetch: {url}")
        return self._responses[url]


class _Clock:
    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    def __call__(self):
        value = self._values[min(self._i, len(self._values) - 1)]
        self._i += 1
        return value


# --- safe-fetch routing + SSRF matrix -----------------------------------------
def test_public_source_fetches_through_safe_boundary():
    t = FakeTransport(
        dns={"example.com": ["93.184.216.34"]},
        responses={"https://example.com/trust": _Resp(200, {}, b"<h1>Trust</h1>")},
    )
    result, status, final_url, data = fetch_public("https://example.com/trust", DOMAINS, transport=t)
    assert result == "ok"
    assert status == 200
    assert data == b"<h1>Trust</h1>"


def test_hostname_resolving_to_private_ip_is_quarantined():
    t = FakeTransport(dns={"example.com": ["127.0.0.1"]})
    result, status, _final, data = fetch_public("https://example.com/x", DOMAINS, transport=t)
    assert result == "quarantined"
    assert status is None
    assert data == b""


def test_mixed_public_private_dns_answers_are_quarantined():
    t = FakeTransport(dns={"example.com": ["93.184.216.34", "10.0.0.1"]})
    result, status, _final, _data = fetch_public("https://example.com/x", DOMAINS, transport=t)
    assert result == "quarantined"
    assert status is None


def test_redirect_to_private_ip_is_quarantined():
    # On-authority subdomain whose DNS answer is a link-local metadata address.
    t = FakeTransport(
        dns={"example.com": ["93.184.216.34"], "internal.example.com": ["169.254.169.254"]},
        responses={"https://example.com/x": _Resp(302, {"location": "https://internal.example.com/y"})},
    )
    result, status, _final, _data = fetch_public("https://example.com/x", DOMAINS, transport=t)
    assert result == "quarantined"
    assert status is None


def test_off_authority_redirect_is_quarantined():
    t = FakeTransport(
        dns={"example.com": ["93.184.216.34"]},
        responses={"https://example.com/x": _Resp(302, {"location": "https://evil.test/y"})},
    )
    result, status, _final, _data = fetch_public("https://example.com/x", DOMAINS, transport=t)
    assert result == "quarantined"
    assert status is None


def test_oversized_response_is_refused_by_byte_bound(monkeypatch):
    monkeypatch.setattr(observe, "MAX_BYTES", 16)
    t = FakeTransport(
        dns={"example.com": ["93.184.216.34"]},
        responses={"https://example.com/big": _Resp(200, {}, b"x" * 64)},
    )
    result, status, _final, data = fetch_public("https://example.com/big", DOMAINS, transport=t)
    assert result == "quarantined"  # byte bound tripped -> fail closed, no body
    assert data == b""


def test_shared_deadline_trips_across_redirect_hop():
    # The clock advances past the timeout while following a same-authority redirect.
    t = FakeTransport(
        dns={"example.com": ["93.184.216.34"]},
        responses={
            "https://example.com/a": _Resp(302, {"location": "https://example.com/b"}),
            "https://example.com/b": _Resp(200, {}, b"late"),
        },
    )
    clock = _Clock([0.0, 0.0, 1000.0])  # exceeds the whole-exchange deadline
    result, status, _final, _data = fetch_public(
        "https://example.com/a", DOMAINS, transport=t, clock=clock
    )
    assert result == "quarantined"
    assert status is None


def test_ip_literal_url_is_quarantined_by_static_precheck():
    result, status, final_url, data = fetch_public("http://127.0.0.1/meta", DOMAINS)
    assert result == "quarantined"
    assert (status, final_url, data) == (None, None, b"")


def test_no_official_domains_fails_closed():
    result, status, _final, data = fetch_public("https://example.com/x", [])
    assert result == "quarantined"
    assert data == b""


def test_bot_protected_status_is_classified():
    t = FakeTransport(
        dns={"example.com": ["93.184.216.34"]},
        responses={"https://example.com/x": _Resp(403, {}, b"")},
    )
    result, status, _final, data = fetch_public("https://example.com/x", DOMAINS, transport=t)
    assert result == "bot_protected"
    assert status == 403
    assert data == b""


def test_client_error_status_is_fetch_failed():
    t = FakeTransport(
        dns={"example.com": ["93.184.216.34"]},
        responses={"https://example.com/x": _Resp(404, {}, b"")},
    )
    result, status, _final, _data = fetch_public("https://example.com/x", DOMAINS, transport=t)
    assert result == "fetch_failed"
    assert status == 404


# --- observation_for_source (fetch_public injected) ---------------------------
def test_observation_for_source_records_success(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com/trust",
        "access_class": "public_web",
    }
    monkeypatch.setattr(
        "tools.openva.observe.fetch_public",
        lambda url, official_domains: ("ok", 200, url, b"<h1>Hello</h1>"),
    )
    observation = observation_for_source(source)

    assert observation["result"] == "ok"
    assert observation["http_status"] == 200
    assert observation["hashes"]["raw_sha256"].startswith("sha256:")
    assert observation["hashes"]["normalized_text_sha256"].startswith("sha256:")
    assert observation["storage"]["raw_document_stored"] is False
    assert "Fetched public source successfully" in observation["notes"]


def test_observation_for_source_does_not_hash_access_changed(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com/private",
        "access_class": "public_web",
    }
    monkeypatch.setattr(
        "tools.openva.observe.fetch_public",
        lambda url, official_domains: ("access_changed", 403, url, b""),
    )
    observation = observation_for_source(source)

    assert observation["result"] == "access_changed"
    assert observation["hashes"]["raw_sha256"] == "sha256:TBD"
    assert observation["hashes"]["normalized_text_sha256"] == "sha256:TBD"
    assert "Maintainer review required" in observation["notes"]


def test_blocked_page_text_becomes_bot_protected(monkeypatch):
    source = {
        "source_id": "example-source",
        "vendor_id": "example-vendor",
        "source_url": "https://example.com",
        "access_class": "public_web",
    }
    monkeypatch.setattr(
        observe,
        "fetch_public",
        lambda url, official_domains: ("ok", 200, "https://example.com", b"Checking your browser before accessing"),
    )
    observation = observe.observation_for_source(source)
    assert observation["result"] == "bot_protected"
    assert observation["hashes"]["raw_sha256"] == "sha256:TBD"
    assert observation["storage"]["raw_document_stored"] is False
    assert "does not bypass" in observation["notes"]


# --- pilot selection + write gating (unchanged behaviour) ---------------------
def test_load_pilot_source_ids_includes_expected_sources():
    source_ids = observe.load_pilot_source_ids()
    assert "aws-subprocessors" in source_ids
    assert "google-cloud-subprocessors" in source_ids
    assert "microsoft-dpa" in source_ids
    assert "alibaba-cloud-international-subprocessors" in source_ids
    assert "tencent-cloud-international-subprocessors" in source_ids


def test_select_sources_pilot_rejects_unknown_source(monkeypatch):
    monkeypatch.setattr(observe, "load_pilot_source_ids", lambda: {"missing-source"})
    with pytest.raises(ValueError, match="unknown source_id"):
        observe.select_sources(pilot_only=True)


def test_ambiguous_results_are_identified():
    assert observe.is_ambiguous_result("bot_protected") is True
    assert observe.is_ambiguous_result("size_limited") is True
    assert observe.is_ambiguous_result("fetch_failed") is True
    assert observe.is_ambiguous_result("quarantined") is True
    assert observe.is_ambiguous_result("ok") is False


def _ambiguous_observation():
    return {
        "schema_version": "0.1.0",
        "observation_id": "example-source-2026-05-14",
        "vendor_id": "example-vendor",
        "source_id": "example-source",
        "artifact_id": None,
        "observed_at": "2026-05-14T00:00:00Z",
        "result": "bot_protected",
        "http_status": 403,
        "final_url": "https://example.com",
        "access_class": "public_web",
        "hashes": {"raw_sha256": "sha256:TBD", "normalized_text_sha256": "sha256:TBD", "etag": None, "last_modified": None},
        "storage": {"raw_document_stored": False, "extracted_text_stored": False, "screenshot_stored": False},
        "notes": "test",
    }


def test_observe_sources_skips_ambiguous_writes_by_default(monkeypatch):
    source = {"source_id": "example-source", "vendor_id": "example-vendor", "source_url": "https://example.com", "access_class": "public_web"}
    monkeypatch.setattr(observe, "select_sources", lambda pilot_only: [source])
    monkeypatch.setattr(observe, "observation_for_source", lambda _source: _ambiguous_observation())
    written = []
    monkeypatch.setattr(
        observe,
        "write_observation",
        lambda observation: written.append(observation) or observe.ROOT / "data/vendors/example-vendor/observations/x.yaml",
    )
    observe.observe_sources(dry_run=False, pilot_only=True)
    assert written == []


def test_observe_sources_can_write_ambiguous_when_explicitly_allowed(monkeypatch):
    source = {"source_id": "example-source", "vendor_id": "example-vendor", "source_url": "https://example.com", "access_class": "public_web"}
    observation = _ambiguous_observation()
    monkeypatch.setattr(observe, "select_sources", lambda pilot_only: [source])
    monkeypatch.setattr(observe, "observation_for_source", lambda _source: observation)
    written = []
    monkeypatch.setattr(
        observe,
        "write_observation",
        lambda item: written.append(item) or observe.ROOT / "data/vendors/example-vendor/observations/x.yaml",
    )
    observe.observe_sources(dry_run=False, pilot_only=True, allow_ambiguous_write=True)
    assert written == [observation]


def test_dry_run_summary_is_compact(monkeypatch, capsys):
    source = {"source_id": "example-source", "vendor_id": "example-vendor", "source_url": "https://example.com", "access_class": "public_web"}
    observation = _ambiguous_observation()
    observation["result"] = "ok"
    observation["http_status"] = 200
    observation["hashes"] = {"raw_sha256": "sha256:" + "a" * 64, "normalized_text_sha256": "sha256:" + "b" * 64, "etag": None, "last_modified": None}
    monkeypatch.setattr(observe, "select_sources", lambda pilot_only: [source])
    monkeypatch.setattr(observe, "observation_for_source", lambda _source: observation)
    observe.observe_sources(dry_run=True, pilot_only=True)
    captured = capsys.readouterr().out
    assert "OpenVA observation summary" in captured
    assert "example-source: ok" in captured
    assert "schema_version:" not in captured
