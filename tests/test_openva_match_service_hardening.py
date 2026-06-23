"""WP-02H provider-neutral application-hardening tests.

Covers the telemetry redaction (no prohibited_telemetry_fields value can be emitted),
the application request + concurrency limits, the rate-limit / abuse-control policy,
cost-exhaustion bounds, and the kill-switch fail-closed-to-cached-only behaviour.

Everything new is OFF or GENEROUS by default; these tests build flag-ON apps/policies
explicitly and additionally assert the DEFAULT posture is unchanged. Deterministic:
the rate-limit clock is injected; no wall-clock sleeps; no network egress.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service.app import create_app  # noqa: E402
from openva_match_service.config import ServiceConfig  # noqa: E402
from openva_match_service.hardening import (  # noqa: E402
    ConcurrencyLimitExceeded,
    ConcurrencyLimiter,
    RateLimitPolicy,
    client_key,
)
from openva_match_service.telemetry import (  # noqa: E402
    PROHIBITED_TELEMETRY_FIELDS,
    InMemoryTelemetry,
    NullTelemetry,
    redact,
    redact_metric_labels,
)

API_KEY = "test-api-key"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# A request body carrying a vendor identity AND a bearer credential — the exact content
# that must never reach telemetry.
VENDOR_ROW = {
    "vendor_name": "Acme Secret Corp",
    "domain": "acme-secret.example",
    "business_entity_name": "Acme Secret Holdings Ltd",
    "registration_number": "REG-999-SECRET",
}
SECRET_TOKEN = "supersecret-job-token-value-1234567890"


def make_app(*, telemetry=None, **overrides):
    return create_app(
        ServiceConfig(pack_path=Path("."), api_key=API_KEY, verify_transport_enabled=True, **overrides),
        telemetry=telemetry,
    )


# --- Redaction unit tests ------------------------------------------------------


def test_redact_drops_every_prohibited_field():
    payload = {
        "request_body": "raw csv bytes",
        "vendor_identity": VENDOR_ROW,
        "inventory_row": "acme,acme.com",
        "uploaded_inventory": [VENDOR_ROW],
        "tool_arguments": {"x": 1},
        "candidate_url": "https://acme-secret.example/dpa",
        "authorization_header": f"Bearer {SECRET_TOKEN}",
        "job_token": SECRET_TOKEN,
        "job_id": "11111111-1111-1111-1111-111111111111",
        "row_count": 3,
        "state": "received",
    }
    out = redact(payload)
    for field in PROHIBITED_TELEMETRY_FIELDS:
        assert field not in out, f"{field} survived redaction"
    # Safe operational metadata is preserved.
    assert out["job_id"] == "11111111-1111-1111-1111-111111111111"
    assert out["row_count"] == 3
    assert out["state"] == "received"
    # No prohibited VALUE survives anywhere in the rendered output.
    rendered = json.dumps(out)
    assert SECRET_TOKEN not in rendered
    assert "Acme Secret" not in rendered
    assert "acme-secret.example" not in rendered


def test_redact_is_recursive_and_masks_bearer_values():
    payload = {
        "outer": {
            "rows": [VENDOR_ROW],  # 'rows' is a prohibited content key -> dropped
            "note": f"Authorization: Bearer {SECRET_TOKEN}",  # bearer value -> masked
            "safe": "ok",
        }
    }
    out = redact(payload)
    rendered = json.dumps(out)
    assert "rows" not in rendered
    assert SECRET_TOKEN not in rendered
    assert out["outer"]["safe"] == "ok"
    assert out["outer"]["note"] == "[redacted]"


def test_redact_does_not_mutate_input():
    payload = {"job_token": SECRET_TOKEN, "job_id": "abc"}
    snapshot = json.dumps(payload, sort_keys=True)
    redact(payload)
    assert json.dumps(payload, sort_keys=True) == snapshot


def test_redact_bounds_recursion_on_cyclic_structure():
    a: dict = {"job_id": "x"}
    a["self"] = a  # cyclic
    # Must not raise / recurse forever.
    out = redact(a)
    assert isinstance(out, dict)


def test_metric_labels_drop_prohibited_and_job_id():
    labels = redact_metric_labels(
        {"job_token": SECRET_TOKEN, "job_id": "abc", "outcome": "created", "state": "received"}
    )
    assert "job_token" not in labels
    # job_id is loggable but NEVER a metric label (unbounded cardinality).
    assert "job_id" not in labels
    assert labels["outcome"] == "created"
    assert labels["state"] == "received"


def test_in_memory_telemetry_never_emits_prohibited_values():
    tel = InMemoryTelemetry()
    tel.log(
        "verify_job_created",
        job_id="job-1",
        job_token=SECRET_TOKEN,
        vendor_identity=VENDOR_ROW,
        authorization_header=f"Bearer {SECRET_TOKEN}",
        row_count=2,
    )
    tel.increment("verify_requests_total", outcome="created", job_token=SECRET_TOKEN)
    tel.observe("verify_duration_ms", 42.0, state="received", candidate_url="https://x/y")
    text = tel.emitted_text()
    assert SECRET_TOKEN not in text
    assert "Acme Secret" not in text
    for field in PROHIBITED_TELEMETRY_FIELDS:
        assert field not in text


# --- Leakage tests (end-to-end through the app) --------------------------------


def test_no_prohibited_value_in_telemetry_for_a_real_verify_request():
    tel = InMemoryTelemetry()
    with TestClient(make_app(telemetry=tel)) as client:
        resp = client.post(
            "/v1/verify",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"rows": [VENDOR_ROW]},
        )
        assert resp.status_code == 200
    text = tel.emitted_text()
    # The returned job_token, vendor identity, and the Authorization header are all absent.
    assert resp.json()["job_token"] not in text
    assert API_KEY not in text
    assert "Acme Secret" not in text
    assert "acme-secret.example" not in text
    assert "REG-999-SECRET" not in text
    for field in PROHIBITED_TELEMETRY_FIELDS:
        assert field not in text
    # Something WAS emitted (the redactor removes data, it does not silence the signal).
    assert tel.counter_value("verify_requests_total", outcome="created") == 1


# --- Rate-limit policy unit tests (deterministic injected clock) ---------------


def test_rate_limit_allows_under_limit_and_rejects_over():
    clock = {"t": 0.0}
    policy = RateLimitPolicy(capacity=3, refill_per_second=1.0, enabled=True, now=lambda: clock["t"])
    assert policy.check("k").allowed
    assert policy.check("k").allowed
    assert policy.check("k").allowed
    rejected = policy.check("k")
    assert not rejected.allowed
    assert rejected.retry_after_seconds > 0


def test_rate_limit_refills_over_time():
    clock = {"t": 0.0}
    policy = RateLimitPolicy(capacity=1, refill_per_second=1.0, enabled=True, now=lambda: clock["t"])
    assert policy.check("k").allowed
    assert not policy.check("k").allowed
    clock["t"] = 1.0  # one second -> one token back
    assert policy.check("k").allowed


def test_rate_limit_is_per_key():
    clock = {"t": 0.0}
    policy = RateLimitPolicy(capacity=1, refill_per_second=1.0, enabled=True, now=lambda: clock["t"])
    assert policy.check("a").allowed
    assert policy.check("b").allowed  # different key, own bucket
    assert not policy.check("a").allowed


def test_rate_limit_disabled_always_allows():
    policy = RateLimitPolicy(capacity=1, refill_per_second=1.0, enabled=False)
    for _ in range(100):
        assert policy.check("k").allowed


def test_client_key_is_opaque_and_never_the_raw_credential():
    key = client_key(f"Bearer {SECRET_TOKEN}")
    assert SECRET_TOKEN not in key
    assert key.startswith("client:")
    # Stable for the same credential, distinct for a different one.
    assert key == client_key(f"Bearer {SECRET_TOKEN}")
    assert key != client_key("Bearer other")
    assert client_key(None) == "anonymous"


# --- Concurrency limiter unit tests --------------------------------------------


def test_concurrency_limiter_bounds_in_flight():
    limiter = ConcurrencyLimiter(2)
    s1 = limiter.acquire()
    s2 = limiter.acquire()
    assert limiter.in_flight == 2
    with pytest.raises(ConcurrencyLimitExceeded):
        limiter.acquire()
    s1.__exit__()
    assert limiter.in_flight == 1
    # A freed slot can be re-acquired.
    limiter.acquire()
    s2.__exit__()


def test_concurrency_limiter_unbounded_by_default():
    limiter = ConcurrencyLimiter(0)
    assert not limiter.bounded
    for _ in range(50):
        limiter.acquire()  # never raises, never tracks
    assert limiter.in_flight == 0


# --- Application enforcement (rate limit + concurrency on verify) --------------


def test_rate_limit_enforced_on_verify_endpoint():
    with TestClient(
        make_app(rate_limit_enabled=True, rate_limit_capacity=2, rate_limit_refill_per_second=0.001)
    ) as client:
        ok1 = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        ok2 = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        limited = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        assert ok1.status_code == 200
        assert ok2.status_code == 200
        assert limited.status_code == 429
        assert limited.json()["error"] == "rate_limited"
        assert "Retry-After" in limited.headers


def test_concurrency_cap_bounds_active_jobs():
    # WP-02A ships no worker, so created jobs stay non-terminal (active) and the cap holds.
    with TestClient(make_app(verify_concurrency_limit=2)) as client:
        a = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        b = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        c = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        assert a.status_code == 200
        assert b.status_code == 200
        assert c.status_code == 503  # cost-exhaustion bound: flood is rejected, not queued
        assert c.json()["error"] == "rate_limited"


def test_cost_exhaustion_flood_is_bounded():
    with TestClient(make_app(verify_concurrency_limit=3)) as client:
        accepted = 0
        for _ in range(50):
            r = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
            if r.status_code == 200:
                accepted += 1
            else:
                assert r.status_code == 503
        # A 50-request flood never creates more than the cap of active jobs.
        assert accepted == 3


# --- Request limits (existing caps still enforced) -----------------------------


def test_oversized_verify_row_count_rejected():
    with TestClient(make_app()) as client:
        rows = [VENDOR_ROW for _ in range(21)]  # > max_verify_rows (20)
        r = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": rows})
        assert r.status_code == 413
        assert r.json()["error"] == "row_limit_exceeded"


# --- Kill-switch fail-closed-to-cached-only ------------------------------------


def test_kill_switch_fails_verify_closed_to_cached_only():
    tel = InMemoryTelemetry()
    with TestClient(make_app(telemetry=tel, verify_kill_switch=True)) as client:
        # verify create returns a clean disabled/anonymous response; NO job is created.
        resp = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "disabled"
        assert body["verify_enabled"] is False
        assert body["not_advice"] is True
        assert "job_id" not in body and "job_token" not in body

        # The cached/static read layer keeps working.
        meta = client.get("/v1/catalog/meta", headers=AUTH_HEADERS)
        assert meta.status_code == 200
        assert meta.json()["not_advice"] is True
        match = client.post("/v1/match", headers=AUTH_HEADERS, json={"vendor_name": "Stripe"})
        assert match.status_code == 200
        healthz = client.get("/healthz")
        assert healthz.status_code == 200

    # Even the disabled response leaks nothing into telemetry.
    text = tel.emitted_text()
    assert "Acme Secret" not in text
    assert tel.counter_value("verify_requests_total", outcome="kill_switch_disabled") == 1


def test_kill_switch_default_off_is_normal():
    with TestClient(make_app()) as client:
        resp = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": [VENDOR_ROW]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "received"
        assert "job_id" in body and "job_token" in body


def test_default_build_has_controls_off_and_null_telemetry():
    cfg = ServiceConfig(pack_path=Path("."), api_key=API_KEY)
    assert cfg.verify_kill_switch is False
    assert cfg.verify_concurrency_limit == 0
    assert cfg.rate_limit_enabled is False
    # No telemetry injected -> the no-op sink is wired at lifespan (default build emits nothing).
    with TestClient(create_app(cfg)) as client:
        assert isinstance(client.app.state.telemetry, NullTelemetry)


# --- Negative tests ------------------------------------------------------------


def test_kill_switch_does_not_read_or_leak_submitted_rows():
    tel = InMemoryTelemetry()
    with TestClient(make_app(telemetry=tel, verify_kill_switch=True)) as client:
        client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={"rows": [VENDOR_ROW]},
        )
    text = tel.emitted_text()
    for value in (SECRET_TOKEN, "Acme Secret", "acme-secret.example", "REG-999-SECRET"):
        assert value not in text


def test_redaction_cannot_be_bypassed_via_nested_or_aliased_keys():
    # A caller-controlled structure trying to smuggle the token under nested/safe-looking
    # keys is still stripped: the bearer value is masked and content keys are dropped.
    tel = InMemoryTelemetry()
    tel.log(
        "evt",
        details={"note": f"token=Bearer {SECRET_TOKEN}", "rows": [VENDOR_ROW]},
        meta=[{"authorization": f"Bearer {SECRET_TOKEN}"}],
    )
    text = tel.emitted_text()
    assert SECRET_TOKEN not in text
    assert "Acme Secret" not in text


def test_null_telemetry_is_a_noop():
    tel = NullTelemetry()
    tel.log("evt", job_token=SECRET_TOKEN)
    tel.increment("m", outcome="x")
    tel.observe("m", 1.0)
    # No exception, nothing captured (no inspection surface) -> just confirm it is a Telemetry.
    assert tel.log("evt2") is None
