from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from tools.openva.robots_policy import RobotsPolicy
from tools.openva.safe_fetch import build_safe_fetcher
from tools.openva.sitemap_discovery import Bounds, FetchResult, discover_sitemap_candidates
from tools.openva.web_bot_auth import (
    ENV_DIRECTORY_URL,
    ENV_PRIVATE_KEY,
    ENV_PUBLIC_JWK,
    WebBotAuthConfigurationError,
    WebBotAuthSigner,
    WebBotAuthTransport,
    jwk_thumbprint,
    wrap_transport,
)


PUBLIC_JWK = {
    "kty": "OKP",
    "crv": "Ed25519",
    "x": base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("="),
}
DIRECTORY = "https://openva-web-bot-auth.example/.well-known/http-message-signatures-directory"


def test_jwk_thumbprint_uses_rfc7638_required_members_only():
    with_extra = {**PUBLIC_JWK, "kid": "ignored", "use": "sig"}
    canonical = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": PUBLIC_JWK["x"]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    expected = base64.urlsafe_b64encode(hashlib.sha256(canonical).digest()).decode().rstrip("=")
    assert jwk_thumbprint(with_extra) == expected


def test_request_headers_cover_authority_and_signature_agent():
    signed_payloads: list[bytes] = []
    signer = WebBotAuthSigner(
        directory_url=DIRECTORY,
        public_jwk=PUBLIC_JWK,
        sign_bytes=lambda payload: signed_payloads.append(payload) or (b"s" * 64),
        clock=lambda: 1_700_000_000,
        nonce_factory=lambda: b"n" * 32,
    )

    headers = signer.headers_for_url("https://Vendor.Example:8443/security?q=1")

    assert headers["Signature-Agent"] == f'"{DIRECTORY}"'
    assert headers["Signature-Input"].startswith('openva=("@authority" "signature-agent")')
    assert ';created=1700000000;' in headers["Signature-Input"]
    assert ';expires=1700000060;' in headers["Signature-Input"]
    assert headers["Signature"].startswith("openva=:")
    payload = signed_payloads[0].decode("ascii")
    assert '"@authority": vendor.example:8443' in payload
    assert f'"signature-agent": "{DIRECTORY}"' in payload
    assert 'tag="web-bot-auth"' in payload


def test_ipv6_authority_is_bracketed_in_signature_base():
    signed_payloads: list[bytes] = []
    signer = WebBotAuthSigner(
        directory_url=DIRECTORY,
        public_jwk=PUBLIC_JWK,
        sign_bytes=lambda payload: signed_payloads.append(payload) or (b"s" * 64),
        clock=lambda: 1_700_000_000,
        nonce_factory=lambda: b"n" * 32,
    )

    signer.headers_for_url("https://[2001:db8::1]:8443/security")

    assert '"@authority": [2001:db8::1]:8443' in signed_payloads[0].decode("ascii")


def test_non_https_requests_are_not_signed_directly():
    signer = WebBotAuthSigner(
        directory_url=DIRECTORY,
        public_jwk=PUBLIC_JWK,
        sign_bytes=lambda _: b"s" * 64,
    )
    with pytest.raises(WebBotAuthConfigurationError, match="HTTPS"):
        signer.headers_for_url("http://vendor.example/security")


def test_partial_environment_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv(ENV_DIRECTORY_URL, DIRECTORY)
    monkeypatch.delenv(ENV_PUBLIC_JWK, raising=False)
    monkeypatch.delenv(ENV_PRIVATE_KEY, raising=False)
    with pytest.raises(WebBotAuthConfigurationError, match="partial"):
        WebBotAuthSigner.from_environment()


def test_absent_environment_preserves_unsigned_transport(monkeypatch):
    for name in (ENV_DIRECTORY_URL, ENV_PUBLIC_JWK, ENV_PRIVATE_KEY):
        monkeypatch.delenv(name, raising=False)
    delegate = object()
    assert wrap_transport(delegate) is delegate


def test_shared_safe_fetch_constructor_applies_identity_once(monkeypatch):
    class Delegate:
        def resolve(self, host):
            return ["93.184.216.34"]

        def open(self, **kwargs):
            raise AssertionError("network should not be used by this construction test")

    class Signer:
        def headers_for_url(self, url):
            return {"Signature-Agent": '"https://directory.example/.well-known/http-message-signatures-directory"'}

    delegate = Delegate()
    signer = Signer()
    monkeypatch.setattr(
        WebBotAuthSigner,
        "from_environment",
        classmethod(lambda cls: signer),
    )

    fetcher = build_safe_fetcher(
        ["vendor.example"],
        max_redirects=2,
        timeout_seconds=3,
        max_compressed_bytes=100,
        max_decompressed_bytes=200,
        transport=delegate,
    )

    assert isinstance(fetcher.transport, WebBotAuthTransport)
    assert fetcher.transport.delegate is delegate
    assert fetcher.transport.signer is signer


def test_transport_re_signs_each_https_url_and_leaves_http_unsigned():
    class Delegate:
        def __init__(self):
            self.calls = []

        def resolve(self, host):
            return ["93.184.216.34"]

        def open(self, **kwargs):
            self.calls.append(kwargs)
            return "response"

    signed_urls: list[str] = []

    class Signer:
        def headers_for_url(self, url):
            signed_urls.append(url)
            return {"Signature-Agent": '"https://directory.example/.well-known/http-message-signatures-directory"'}

    delegate = Delegate()
    transport = WebBotAuthTransport(delegate, Signer())
    result = transport.open(
        url="https://vendor.example/a",
        ip="93.184.216.34",
        host="vendor.example",
        headers={"User-Agent": "OpenVA-Discovery"},
        deadline=10.0,
        clock=lambda: 0.0,
    )
    transport.open(
        url="https://vendor.example/b",
        ip="93.184.216.34",
        host="vendor.example",
        headers={"User-Agent": "OpenVA-Discovery"},
        deadline=10.0,
        clock=lambda: 0.0,
    )
    transport.open(
        url="http://vendor.example/legacy",
        ip="93.184.216.34",
        host="vendor.example",
        headers={"User-Agent": "OpenVA-Discovery"},
        deadline=10.0,
        clock=lambda: 0.0,
    )

    assert result == "response"
    assert signed_urls == ["https://vendor.example/a", "https://vendor.example/b"]
    assert "Signature-Agent" in delegate.calls[0]["headers"]
    assert "Signature-Agent" in delegate.calls[1]["headers"]
    assert "Signature-Agent" not in delegate.calls[2]["headers"]


def test_robots_crawl_delay_uses_most_specific_group_and_conservative_max():
    policy = RobotsPolicy.parse(
        """
        User-agent: *
        Crawl-delay: 1
        User-agent: OpenVA-Discovery
        Crawl-delay: 2
        User-agent: OpenVA-Discovery
        Crawl-delay: 3.5
        """
    )
    assert policy.crawl_delay("OpenVA-Discovery") == 3.5
    assert policy.crawl_delay("OtherBot") == 1


def test_invalid_crawl_delay_is_ignored():
    policy = RobotsPolicy.parse(
        """
        User-agent: OpenVA-Discovery
        Crawl-delay: -1
        Crawl-delay: infinity
        Crawl-delay: not-a-number
        Allow: /
        """
    )
    assert policy.crawl_delay("OpenVA-Discovery") is None
    assert policy.can_fetch("OpenVA-Discovery", "/security")


def test_crawl_delay_before_user_agent_does_not_create_a_valid_group():
    policy = RobotsPolicy.parse("Crawl-delay: 2\n")
    assert policy.malformed is True
    assert policy.crawl_delay("OpenVA-Discovery") is None
    assert policy.can_fetch("OpenVA-Discovery", "/security") is False


def test_sitemap_discovery_waits_after_robots_before_fetching_sitemap():
    calls: list[str] = []
    sleeps: list[float] = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        if url.endswith("/robots.txt"):
            return FetchResult(
                200,
                url,
                b"User-agent: OpenVA-Discovery\nCrawl-delay: 2\n",
            )
        if url.endswith("/sitemap.xml"):
            return FetchResult(
                200,
                url,
                b"<urlset><url><loc>https://vendor.example/security</loc></url></urlset>",
            )
        raise AssertionError(f"unexpected fetch: {url}")

    outcome = discover_sitemap_candidates(
        ["vendor.example"],
        fetch,
        bounds=Bounds(max_sitemap_files=1, relevance_terms=("security",)),
        discovery_run_id="run-1",
        discovered_at="2026-07-03T00:00:00Z",
        vendor_id="vendor",
        clock=lambda: 0.0,
        sleeper=sleeps.append,
    )

    assert calls == [
        "https://vendor.example/robots.txt",
        "https://vendor.example/sitemap.xml",
    ]
    assert sleeps == [2.0]
    assert outcome.candidates == [
        {
            "url": "https://vendor.example/security",
            "discovered_from": "https://vendor.example/sitemap.xml",
        }
    ]


def test_worker_contract_does_not_publish_secret_member():
    worker = Path("infra/cloudflare/openva-web-bot-auth/worker.js").read_text(encoding="utf-8")
    assert "application/http-message-signatures-directory+json" in worker
    assert 'tag="http-message-signatures-directory"' in worker
    assert "Signature-Input" in worker
    assert 'const published = { kty: "OKP", crv: "Ed25519", x: signingJwk.x }' in worker
