"""Cloudflare-compatible Web Bot Auth request signing for OpenVA crawlers.

The module is deliberately dependency-light: Ed25519 signing is delegated to the
OpenSSL command already present on GitHub-hosted runners and common Linux images.
Private key material is supplied only through environment variables, decoded into
a mode-0600 temporary file for the duration of one signature operation, and never
written to the repository, command line, logs, exceptions, or observation output.

Configuration is all-or-nothing. When no Web Bot Auth variables are present,
OpenVA preserves its existing unsigned behavior. A partial configuration fails
closed rather than emitting malformed identity headers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

DIRECTORY_SUFFIX = "/.well-known/http-message-signatures-directory"
DEFAULT_EXPIRES_SECONDS = 60
SIGNATURE_LABEL = "openva"

ENV_DIRECTORY_URL = "OPENVA_WEB_BOT_AUTH_DIRECTORY_URL"
ENV_PUBLIC_JWK = "OPENVA_WEB_BOT_AUTH_PUBLIC_JWK_JSON"
ENV_PRIVATE_KEY = "OPENVA_WEB_BOT_AUTH_PRIVATE_KEY_PEM_B64"


class WebBotAuthConfigurationError(RuntimeError):
    """Web Bot Auth was partially or invalidly configured."""


class SignBytes(Protocol):
    def __call__(self, payload: bytes) -> bytes: ...


class TransportLike(Protocol):
    def resolve(self, host: str) -> list[str]: ...

    def open(
        self,
        *,
        url: str,
        ip: str,
        host: str,
        headers: Mapping[str, str],
        deadline: float,
        clock: Callable[[], float],
    ): ...


def _b64url_no_padding(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _canonical_public_jwk(jwk: Mapping[str, object]) -> dict[str, str]:
    required = {"crv": "Ed25519", "kty": "OKP"}
    for name, expected in required.items():
        if jwk.get(name) != expected:
            raise WebBotAuthConfigurationError(f"public JWK {name} must equal {expected}")
    x = jwk.get("x")
    if not isinstance(x, str) or not x:
        raise WebBotAuthConfigurationError("public JWK x must be a non-empty base64url string")
    try:
        base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise WebBotAuthConfigurationError("public JWK x is not valid base64url") from exc
    # RFC 7638 requires lexicographic member ordering and only required members.
    return {"crv": "Ed25519", "kty": "OKP", "x": x}


def jwk_thumbprint(jwk: Mapping[str, object]) -> str:
    canonical = json.dumps(
        _canonical_public_jwk(jwk), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return _b64url_no_padding(hashlib.sha256(canonical).digest())


def _authority(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise WebBotAuthConfigurationError("Web Bot Auth signs HTTPS requests only")
    if not parts.hostname:
        raise WebBotAuthConfigurationError("request URL has no hostname")
    host = parts.hostname.lower()
    if parts.port is not None and parts.port != 443:
        return f"{host}:{parts.port}"
    return host


def _quoted_directory_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise WebBotAuthConfigurationError("key directory URL must use HTTPS")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise WebBotAuthConfigurationError("key directory URL must not contain credentials, query, or fragment")
    normalized_path = parts.path.rstrip("/") or DIRECTORY_SUFFIX
    if normalized_path != DIRECTORY_SUFFIX:
        raise WebBotAuthConfigurationError(
            f"key directory URL path must be {DIRECTORY_SUFFIX}"
        )
    normalized = f"https://{parts.netloc.lower()}{DIRECTORY_SUFFIX}"
    return f'"{normalized}"'


def _openssl_sign(private_key_pem: bytes, payload: bytes) -> bytes:
    if b"PRIVATE KEY" not in private_key_pem:
        raise WebBotAuthConfigurationError("private key is not PEM-encoded")
    with tempfile.TemporaryDirectory(prefix="openva-web-bot-auth-") as directory:
        key_path = Path(directory) / "private-key.pem"
        payload_path = Path(directory) / "signature-base.bin"
        key_path.write_bytes(private_key_pem)
        payload_path.write_bytes(payload)
        key_path.chmod(0o600)
        payload_path.chmod(0o600)
        try:
            completed = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-sign",
                    "-rawin",
                    "-inkey",
                    str(key_path),
                    "-in",
                    str(payload_path),
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError as exc:
            raise WebBotAuthConfigurationError("OpenSSL is required for Web Bot Auth signing") from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            # Never include stderr: some OpenSSL builds may echo key-file details.
            raise WebBotAuthConfigurationError("Ed25519 signing failed") from exc
    if len(completed.stdout) != 64:
        raise WebBotAuthConfigurationError("Ed25519 signer returned an invalid signature length")
    return completed.stdout


@dataclass(frozen=True)
class WebBotAuthSigner:
    directory_url: str
    public_jwk: Mapping[str, object]
    sign_bytes: SignBytes
    expires_seconds: int = DEFAULT_EXPIRES_SECONDS
    clock: Callable[[], float] = time.time
    nonce_factory: Callable[[], bytes] = lambda: secrets.token_bytes(32)

    @property
    def key_id(self) -> str:
        return jwk_thumbprint(self.public_jwk)

    def headers_for_url(self, url: str) -> dict[str, str]:
        authority = _authority(url)
        signature_agent = _quoted_directory_url(self.directory_url)
        created = int(self.clock())
        expires = created + self.expires_seconds
        if self.expires_seconds <= 0 or self.expires_seconds > 300:
            raise WebBotAuthConfigurationError("signature lifetime must be between 1 and 300 seconds")
        nonce = base64.b64encode(self.nonce_factory()).decode("ascii")
        params = (
            '("@authority" "signature-agent")'
            f';created={created};keyid="{self.key_id}";alg="ed25519"'
            f';expires={expires};nonce="{nonce}";tag="web-bot-auth"'
        )
        signature_base = (
            f'"@authority": {authority}\n'
            f'"signature-agent": {signature_agent}\n'
            f'"@signature-params": {params}'
        ).encode("ascii")
        signature = self.sign_bytes(signature_base)
        if len(signature) != 64:
            raise WebBotAuthConfigurationError("Ed25519 signer returned an invalid signature length")
        return {
            "Signature-Agent": signature_agent,
            "Signature-Input": f"{SIGNATURE_LABEL}={params}",
            "Signature": f"{SIGNATURE_LABEL}=:{base64.b64encode(signature).decode('ascii')}:",
        }

    @classmethod
    def from_environment(cls) -> "WebBotAuthSigner | None":
        values = {
            ENV_DIRECTORY_URL: os.environ.get(ENV_DIRECTORY_URL, "").strip(),
            ENV_PUBLIC_JWK: os.environ.get(ENV_PUBLIC_JWK, "").strip(),
            ENV_PRIVATE_KEY: os.environ.get(ENV_PRIVATE_KEY, "").strip(),
        }
        configured = [name for name, value in values.items() if value]
        if not configured:
            return None
        if len(configured) != len(values):
            missing = sorted(name for name, value in values.items() if not value)
            raise WebBotAuthConfigurationError(
                "partial Web Bot Auth configuration; missing " + ", ".join(missing)
            )
        try:
            jwk = json.loads(values[ENV_PUBLIC_JWK])
        except json.JSONDecodeError as exc:
            raise WebBotAuthConfigurationError("public JWK JSON is invalid") from exc
        if not isinstance(jwk, dict):
            raise WebBotAuthConfigurationError("public JWK JSON must be an object")
        _canonical_public_jwk(jwk)
        try:
            private_key = base64.b64decode(values[ENV_PRIVATE_KEY], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise WebBotAuthConfigurationError("private key environment value is not valid base64") from exc

        def sign(payload: bytes) -> bytes:
            return _openssl_sign(private_key, payload)

        return cls(
            directory_url=values[ENV_DIRECTORY_URL],
            public_jwk=jwk,
            sign_bytes=sign,
        )


class WebBotAuthTransport:
    """Transport decorator that signs every request, including each redirect hop."""

    def __init__(self, delegate: TransportLike, signer: WebBotAuthSigner) -> None:
        self.delegate = delegate
        self.signer = signer

    def resolve(self, host: str) -> list[str]:
        return self.delegate.resolve(host)

    def open(
        self,
        *,
        url: str,
        ip: str,
        host: str,
        headers: Mapping[str, str],
        deadline: float,
        clock: Callable[[], float],
    ):
        signed_headers = dict(headers)
        signed_headers.update(self.signer.headers_for_url(url))
        return self.delegate.open(
            url=url,
            ip=ip,
            host=host,
            headers=signed_headers,
            deadline=deadline,
            clock=clock,
        )


def wrap_transport(
    transport: TransportLike,
    signer: WebBotAuthSigner | None = None,
) -> TransportLike:
    effective = signer if signer is not None else WebBotAuthSigner.from_environment()
    return WebBotAuthTransport(transport, effective) if effective is not None else transport


def signed_headers_for_url(url: str) -> dict[str, str]:
    signer = WebBotAuthSigner.from_environment()
    return signer.headers_for_url(url) if signer is not None else {}
