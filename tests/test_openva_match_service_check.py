"""WP-02J ``/v1/check`` live-verify-mode tests.

Mirrors the existing match-service harness (tests/test_openva_match_service_verify.py).
``/v1/check`` ALWAYS serves the cached answer and EXPLICITLY LABELS each row's freshness
as ``cached`` vs ``verify``. The live-verify augmentation is OFF by default: it runs only
when the verify transport is enabled, the kill-switch is off, AND a synchronous verify
runner (the existing worker over the existing TTL stores) is wired via
``create_app(verify_runner_factory=...)``.

Frozen acceptance criteria exercised here:
  - cached-vs-verify labelling (the label is always present and accurate);
  - honest degradation (transport off / kill-switched / no runner -> cached, never
    stale-as-live; cached/static endpoints unaffected);
  - SSRF-negative (no url/fetch-target param; the live path uses the SSRF-safe boundary);
  - non-advisory (not_advice: true; no scoring/ranking);
  - access / bounded rows / public-read parity / over-limit rejection.

All tests are DETERMINISTIC with NO real network: the worker's resolver is a FAKE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service.app import (  # noqa: E402
    HEADER_ADVISORY_BOUNDARY,
    HEADER_PACK_GENERATED_AT,
    HEADER_PACK_PROFILE,
    HEADER_PACK_SCHEMA_VERSION,
    HEADER_SERVICE_VERSION,
    create_app,
)
from openva_match_service import worker as wk  # noqa: E402
from openva_match_service.check_service import TransportVerifyRunner  # noqa: E402
from openva_match_service.config import ServiceConfig  # noqa: E402
from openva_match_service.queue import InMemoryQueue  # noqa: E402
from openva_match_service.verify_transport import (  # noqa: E402
    InMemoryJobStore,
    InMemoryRequestEnvelopeStore,
    InMemoryResultStore,
)

API_KEY = "test-api-key"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}
REQUIRED_HEADERS = {
    HEADER_SERVICE_VERSION,
    HEADER_PACK_PROFILE,
    HEADER_PACK_SCHEMA_VERSION,
    HEADER_PACK_GENERATED_AT,
    HEADER_ADVISORY_BOUNDARY,
}


def assert_required_headers(response) -> None:
    for header in REQUIRED_HEADERS:
        assert header in response.headers
    assert response.headers[HEADER_ADVISORY_BOUNDARY] == "non_advisory"


# --- Fake resolver (deterministic, NO network) ---------------------------------


class FakeResolver:
    """Deterministic stand-in for vendor_resolution.resolve_vendor_sources.

    Records every call so a test can assert the worker ALWAYS passed the SSRF-safe
    fetcher_factory and NEVER a fetch-target URL. Returns a plain dict."""

    def __init__(self):
        self.calls = []

    def __call__(self, request, *, catalog=None, fetcher_factory=None, **kwargs):
        self.calls.append({"request": request, "fetcher_factory": fetcher_factory, "kwargs": kwargs})
        return {
            "resolution_status": "verified_live",
            "freshness_mode": "verify",
            "vendor": request.get("vendor", {}),
            "not_advice": True,
        }


def _live_runner_factory(resolver: FakeResolver):
    """Return a ``verify_runner_factory`` that builds a synchronous TransportVerifyRunner
    over the app's existing TTL stores + queue, driving the EXISTING worker with the fake
    resolver. The worker is the real VerifyWorker (only the resolver/clock are faked)."""

    def factory(app):
        worker = wk.VerifyWorker(
            app.state.verify_jobs,
            app.state.verify_envelopes,
            app.state.verify_results,
            app.state.verify_queue,
            catalog=None,
            resolve=resolver,
        )
        return TransportVerifyRunner(
            jobs=app.state.verify_jobs,
            envelopes=app.state.verify_envelopes,
            results=app.state.verify_results,
            queue=app.state.verify_queue,
            worker=worker,
            config=app.state.config,
        )

    return factory


def make_cached_only_app(**overrides):
    """Default config: verify transport OFF; no runner -> /check serves cached only."""
    return create_app(ServiceConfig(pack_path=Path("."), api_key=API_KEY, **overrides))


def make_live_app(resolver: FakeResolver | None = None, **overrides):
    """Verify transport ON + a live runner wired -> /check performs live verification."""
    resolver = resolver or FakeResolver()
    return create_app(
        ServiceConfig(pack_path=Path("."), api_key=API_KEY, verify_transport_enabled=True, **overrides),
        verify_runner_factory=_live_runner_factory(resolver),
    )


CHECK_BODY = {"rows": [{"row_id": "1", "vendor_name": "Stripe", "domain": "stripe.com"}]}


# --- cached-vs-verify labelling ------------------------------------------------


def test_check_labels_cached_when_no_live_runner():
    # Transport off (default) -> no runner -> every row labelled `cached`, no verification.
    with TestClient(make_cached_only_app()) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=CHECK_BODY)
    assert response.status_code == 200
    assert_required_headers(response)
    body = response.json()
    assert body["freshness_mode"] == "cached"
    assert body["verify_enabled"] is False
    assert body["not_advice"] is True
    row = body["results"][0]
    assert row["freshness"] == "cached"
    assert row["verification"] is None
    assert "match" in row  # the cached answer is always available


def test_check_labels_verify_when_live_runner_present():
    resolver = FakeResolver()
    with TestClient(make_live_app(resolver)) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=CHECK_BODY)
    assert response.status_code == 200
    assert_required_headers(response)
    body = response.json()
    assert body["freshness_mode"] == "verify"
    assert body["verify_enabled"] is True
    row = body["results"][0]
    assert row["freshness"] == "verify"
    # The label is accurate: a live verification payload is present and carries the live data.
    assert row["verification"] is not None
    assert row["verification"]["resolution"]["resolution_status"] == "verified_live"
    # The cached match is still present alongside the live verification.
    assert "match" in row
    # The resolver was actually called for the row.
    assert len(resolver.calls) == 1


# --- honest degradation --------------------------------------------------------


def test_check_degrades_to_cached_when_kill_switched():
    # Kill-switch armed -> the runner is never built -> cached only, clearly labelled.
    resolver = FakeResolver()
    with TestClient(make_live_app(resolver, verify_kill_switch=True)) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=CHECK_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["freshness_mode"] == "cached"
    assert body["verify_enabled"] is False
    assert body["results"][0]["freshness"] == "cached"
    assert body["results"][0]["verification"] is None
    # Honest degradation: the kill switch means no live fetch ran at all.
    assert resolver.calls == []


def test_check_degrades_when_runner_factory_absent_even_if_transport_on():
    # Transport ON but no runner wired -> still cached only (the live path is opt-in).
    app = create_app(
        ServiceConfig(pack_path=Path("."), api_key=API_KEY, verify_transport_enabled=True)
    )
    with TestClient(app) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=CHECK_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["freshness_mode"] == "cached"
    assert body["verify_enabled"] is False
    assert body["results"][0]["freshness"] == "cached"


def test_check_row_degrades_honestly_when_live_verification_unavailable():
    # The runner is present but the worker fails the job closed (resolver raises) -> the
    # row degrades HONESTLY to cached, never stale-as-live.
    class FailingResolver:
        def __call__(self, request, *, catalog=None, fetcher_factory=None, **kwargs):
            raise RuntimeError("upstream down")

    with TestClient(make_live_app(FailingResolver())) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=CHECK_BODY)
    assert response.status_code == 200
    body = response.json()
    # verify_enabled reflects that the live path was AVAILABLE, but the row fell back.
    assert body["verify_enabled"] is True
    assert body["freshness_mode"] == "cached"
    row = body["results"][0]
    assert row["freshness"] == "cached"
    assert row["verification"] is None


def test_cached_and_static_endpoints_unaffected_by_check():
    # /check never disturbs the cached/static endpoints.
    with TestClient(make_live_app()) as client:
        meta = client.get("/v1/catalog/meta", headers=AUTH_HEADERS)
        match = client.post("/v1/match", headers=AUTH_HEADERS, json={"vendor_name": "Stripe"})
    assert meta.status_code == 200 and meta.json()["not_advice"] is True
    assert match.status_code == 200


# --- SSRF-negative -------------------------------------------------------------


def test_check_rejects_a_fetch_target_url_parameter():
    # The endpoint exposes NO url/fetch-target parameter: any url/candidate_url/source_url
    # (or other undeclared field) on a row is a 422 (the SSRF boundary).
    for bad in ("url", "candidate_url", "source_url", "fetch_url"):
        with TestClient(make_live_app()) as client:
            response = client.post(
                "/v1/check",
                headers=AUTH_HEADERS,
                json={"rows": [{"vendor_name": "Stripe", bad: "http://169.254.169.254/"}]},
            )
        assert response.status_code == 422, bad


def test_check_live_path_uses_ssrf_safe_boundary_and_no_url():
    # The live path forwards IDENTITIES ONLY and ALWAYS the SSRF-safe fetcher_factory —
    # never an arbitrary fetcher and never a caller-supplied fetch target.
    resolver = FakeResolver()
    with TestClient(make_live_app(resolver)) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=CHECK_BODY)
    assert response.status_code == 200
    assert len(resolver.calls) == 1
    call = resolver.calls[0]
    # The SSRF-safe fetcher_factory was passed (the worker default), never overridden.
    assert call["fetcher_factory"] is wk.default_fetcher_factory
    # Only identity fields reach the resolver; no url/fetch target of any kind.
    vendor = call["request"]["vendor"]
    assert set(vendor).issubset({"vendor_name", "domain", "business_entity_name", "registration_number"})
    assert not any("url" in key for key in vendor)


# --- non-advisory --------------------------------------------------------------


def test_check_is_non_advisory_with_no_scoring_or_ranking():
    with TestClient(make_live_app()) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=CHECK_BODY)
    body = response.json()
    assert body["not_advice"] is True
    assert response.headers[HEADER_ADVISORY_BOUNDARY] == "non_advisory"
    for row in body["results"]:
        assert row["not_advice"] is True
        # No advisory verdict/score/rank keys anywhere on a row.
        for forbidden in ("score", "ranking", "rank", "verdict", "risk", "recommendation"):
            assert forbidden not in row


# --- access / limits -----------------------------------------------------------


def test_check_requires_api_key_when_not_public():
    with TestClient(make_cached_only_app()) as client:
        response = client.post("/v1/check", json=CHECK_BODY)
    assert response.status_code == 401


def test_check_public_read_mode_allows_unauthenticated_cached_read():
    # Public-read parity with the other /v1 read endpoints (cached read is public).
    with TestClient(make_cached_only_app(public_read_enabled=True)) as client:
        response = client.post("/v1/check", json=CHECK_BODY)
    assert response.status_code == 200
    assert response.json()["freshness_mode"] == "cached"


def test_check_over_row_limit_is_rejected_before_work():
    rows = [{"row_id": str(i), "vendor_name": f"v{i}"} for i in range(25)]
    with TestClient(make_live_app(max_verify_rows=20)) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json={"rows": rows})
    assert response.status_code == 413
    assert response.json()["error"] == "row_limit_exceeded"


def test_check_empty_rows_is_422():
    with TestClient(make_cached_only_app()) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json={"rows": []})
    assert response.status_code == 422


def test_check_too_many_source_types_is_422():
    body = {
        "rows": [{"vendor_name": "Stripe"}],
        "source_types": ["a", "b", "c", "d", "e"],  # > 4 (the hosted verify budget)
    }
    with TestClient(make_cached_only_app()) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json=body)
    assert response.status_code == 422


def test_check_multi_row_each_row_labelled_and_id_preserved():
    rows = [
        {"row_id": "a", "vendor_name": "Stripe"},
        {"row_id": "b", "vendor_name": "Acme"},
    ]
    with TestClient(make_live_app()) as client:
        response = client.post("/v1/check", headers=AUTH_HEADERS, json={"rows": rows})
    body = response.json()
    assert [r["row_id"] for r in body["results"]] == ["a", "b"]
    for row in body["results"]:
        assert row["freshness"] in ("cached", "verify")
        assert "freshness" in row  # always present
