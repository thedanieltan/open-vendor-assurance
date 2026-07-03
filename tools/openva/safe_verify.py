"""Candidate-page verification over the bounded fetch boundary."""

from __future__ import annotations

from typing import Callable

from tools.openva import source_verification
from tools.openva.safe_fetch import SafeFetchError, SocketTransport, Transport, build_safe_fetcher
from tools.openva.web_bot_auth import wrap_transport

VERIFY_SAMPLE_BYTES = source_verification.MAX_SAMPLE_BYTES
VERIFY_MAX_BYTES = 2_000_000
_GZIP_MAGIC = b"\x1f\x8b"


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_safe_verify_fetcher(
    official_domains: list[str],
    *,
    max_redirects: int,
    timeout_seconds: float,
    max_bytes: int = VERIFY_MAX_BYTES,
    sample_bytes: int = VERIFY_SAMPLE_BYTES,
    transport: Transport | None = None,
    clock: Callable[[], float] | None = None,
) -> Callable[[str], source_verification.FetchResult]:
    """Return a same-authority fetcher, optionally decorated with Web Bot Auth."""
    signed_transport = wrap_transport(transport or SocketTransport())
    fetcher = build_safe_fetcher(
        official_domains,
        max_redirects=max_redirects,
        timeout_seconds=timeout_seconds,
        max_compressed_bytes=max_bytes,
        max_decompressed_bytes=max_bytes,
        accept_encoding="identity",
        transport=signed_transport,
        clock=clock,
    )

    def verify(url: str) -> source_verification.FetchResult:
        try:
            result = fetcher.fetch(url)
        except SafeFetchError as exc:
            return source_verification.FetchResult(
                requested_url=url,
                final_url=url,
                http_status=None,
                content_type=None,
                content_length=None,
                etag=None,
                last_modified=None,
                body_sample=b"",
                error=str(exc),
            )
        if (result.content_encoding or "").strip().lower() == "gzip" or result.body[:2] == _GZIP_MAGIC:
            return source_verification.FetchResult(
                requested_url=url,
                final_url=result.final_url,
                http_status=None,
                content_type=None,
                content_length=None,
                etag=None,
                last_modified=None,
                body_sample=b"",
                error="unexpected_gzip_despite_identity",
            )
        headers = result.headers or {}
        return source_verification.FetchResult(
            requested_url=url,
            final_url=result.final_url,
            http_status=result.status,
            content_type=headers.get("content-type"),
            content_length=_int_or_none(headers.get("content-length")),
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            body_sample=result.body[:sample_bytes],
            error=None,
        )

    return verify
