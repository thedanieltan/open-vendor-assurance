"""Tier A: candidate-page verification over the SSRF-safe fetch boundary.

The sitemap lane must verify nominated candidate URLs through the SAME network
protections as discovery — DNS-resolved + pinned IP, rejection of private /
loopback / link-local / reserved and mixed public+private answers, same-authority
redirects with per-hop revalidation, no credentials/cookies, bounded bytes, and
the whole-exchange monotonic deadline — never the legacy unrestricted urllib
client. This adapter wraps ``SafeFetcher`` and returns the existing
``source_verification.FetchResult`` shape, so all ordinary semantic
classification and candidate-record logic is reused unchanged.

A safety, bound, or transport failure is surfaced as a ``FetchResult`` with
``http_status=None`` and an ``error``, which the ordinary classifier treats as
not-a-candidate: a sitemap locator therefore stays zero-weight until this safe
verification actually succeeds.

Web Bot Auth is inherited from ``build_safe_fetcher`` at the shared transport
boundary. The same SSRF, authority, redirect, deadline, and byte-boundary checks
therefore continue to run, while every HTTPS request and redirect hop receives a
fresh authority-bound signature. HTTP requests retain the existing bounded,
unsigned behavior.
"""

from __future__ import annotations

from typing import Callable

from tools.openva import source_verification
from tools.openva.safe_fetch import SafeFetchError, Transport, build_safe_fetcher

# Candidate verification classifies a bounded sample, like the legacy verifier.
VERIFY_SAMPLE_BYTES = source_verification.MAX_SAMPLE_BYTES
# Hard wire bound for a candidate page; larger responses are refused (a bounded,
# DoS-resistant fetch — not a silent sample of an unbounded body).
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
    """A candidate-verification fetcher bound to a vendor's own authority.

    Reuses ``SafeFetcher`` (same-authority redirects, DNS-pinned IP, mixed-answer
    rejection, deadline, byte bound) and requests identity encoding so the body
    it classifies is readable text. The shared constructor applies Web Bot Auth
    once when configured. Returns ``source_verification.FetchResult``.
    """
    fetcher = build_safe_fetcher(
        official_domains,
        max_redirects=max_redirects,
        timeout_seconds=timeout_seconds,
        # The candidate page is read under one wire bound; identity-only so the
        # classifier sees text, not gzip bytes.
        max_compressed_bytes=max_bytes,
        max_decompressed_bytes=max_bytes,
        accept_encoding="identity",
        transport=transport,
        clock=clock,
    )

    def verify(url: str) -> source_verification.FetchResult:
        try:
            result = fetcher.fetch(url)
        except SafeFetchError as exc:
            # Unsafe target, off-authority redirect, bound hit, or transport
            # failure: not a candidate. Zero weight until safe verification works.
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
            # The server returned gzip despite an identity request; the classifier
            # would see undecodable bytes. Record an explicit, auditable rejection
            # rather than a silent semantic mismatch (the lane does not decompress
            # candidate pages — only sitemaps are decompressed, under their own bounds).
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
