"""WP-02A hosted verify transport tests.

Mirrors the existing match-service harness (tests/test_openva_match_service.py).
The verify transport is behind OPENVA_VERIFY_TRANSPORT_ENABLED (default OFF); these
tests build a flag-ON app explicitly and additionally assert the flag-OFF (rollback)
posture leaves the service cached-only.

Security focus: header-only token transport, constant-time digest comparison,
digest-only storage, generic auth failures, the SSRF identity-only boundary, and the
non-advisory boundary on every verify response.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
import yaml
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
    _iso_z,
    create_app,
)
from openva_match_service.config import (  # noqa: E402
    VERIFY_RETAINED_WINDOW_HOURS,
    VERIFY_ROWS_HARD_CEILING,
    ServiceConfig,
)
from openva_match_service.models import MAX_VERIFY_SOURCE_TYPES  # noqa: E402
from openva_match_service.verify_transport import (  # noqa: E402
    JobRecord,
    digests_match,
    extract_bearer_token,
    new_job_id,
    new_job_token,
    new_ref,
    token_digest,
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

JOB_RECORD_SCHEMA = json.loads(
    Path("schemas/openva/hosted-job-record.schema.json").read_text(encoding="utf-8")
)


def assert_required_headers(response) -> None:
    for header in REQUIRED_HEADERS:
        assert header in response.headers
    assert response.headers[HEADER_ADVISORY_BOUNDARY] == "non_advisory"
    assert response.headers[HEADER_PACK_PROFILE] == "openva.public-metadata.v1"
    assert response.headers[HEADER_PACK_SCHEMA_VERSION] == "openva-export-pack.v1"


def make_verify_app(**overrides):
    return create_app(
        ServiceConfig(pack_path=Path("."), api_key=API_KEY, verify_transport_enabled=True, **overrides)
    )


def make_cached_only_app():
    # The default config: verify transport OFF.
    return create_app(ServiceConfig(pack_path=Path("."), api_key=API_KEY))


def create_job(client):
    return client.post(
        "/v1/verify",
        headers=AUTH_HEADERS,
        json={"rows": [{"vendor_name": "Stripe", "domain": "stripe.com"}]},
    )


# 1. Flag OFF (default) -> verify endpoints 404; cached endpoints still work.
def test_flag_off_returns_404_and_cached_endpoints_work():
    with TestClient(make_cached_only_app()) as client:
        post = client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={"rows": [{"vendor_name": "Stripe"}]},
        )
        get = client.get(
            "/v1/verify/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": "Bearer anything"},
        )
        assert post.status_code == 404
        assert get.status_code == 404
        assert_required_headers(post)
        assert_required_headers(get)

        # Existing cached endpoints are unaffected when the flag is off.
        meta = client.get("/v1/catalog/meta", headers=AUTH_HEADERS)
        assert meta.status_code == 200
        assert meta.json()["not_advice"] is True
        match = client.post("/v1/match", headers=AUTH_HEADERS, json={"vendor_name": "Stripe"})
        assert match.status_code == 200


# 2. Create returns job_id (UUID) + job_token + state received + not_advice + headers.
def test_create_returns_job_id_token_and_state():
    with TestClient(make_verify_app()) as client:
        response = create_job(client)

    assert response.status_code == 200
    assert_required_headers(response)
    body = response.json()
    # job_id is a UUID.
    import uuid

    uuid.UUID(body["job_id"])
    assert body["state"] == "received"
    assert body["not_advice"] is True
    assert "snapshot" in body
    # The token is high-entropy and NOT equal to the API key.
    assert body["job_token"] != API_KEY
    assert len(body["job_token"]) >= 32
    assert "expires_at" in body


# 3. Poll with the correct Bearer token -> 200; headers; no token/digest in body.
def test_poll_with_correct_token_returns_status():
    with TestClient(make_verify_app()) as client:
        created = create_job(client).json()
        response = client.get(
            f"/v1/verify/{created['job_id']}",
            headers={"Authorization": f"Bearer {created['job_token']}"},
        )

    assert response.status_code == 200
    assert_required_headers(response)
    body = response.json()
    assert body["job_id"] == created["job_id"]
    assert body["state"] == "received"
    assert body["row_count"] == 1
    assert body["not_advice"] is True
    # The status projection never exposes the token, the digest, or lease fields.
    serialized = json.dumps(body)
    assert created["job_token"] not in serialized
    assert "job_token" not in body
    assert "job_token_digest" not in body
    assert "lease_owner" not in body
    assert "lease_expires_at" not in body
    assert "request_ref" not in body


# 4. Poll auth failures on an EXISTING job stay 401; an UNKNOWN job is 404.
#    Both are CONTENT-FREE (empty body) and still carry the advisory-boundary header.
def test_poll_auth_failures_and_unknown_job():
    with TestClient(make_verify_app()) as client:
        created = create_job(client).json()
        job_id = created["job_id"]

        no_auth = client.get(f"/v1/verify/{job_id}")
        wrong = client.get(f"/v1/verify/{job_id}", headers={"Authorization": "Bearer not-the-token"})

    # Missing-token and wrong-token on an EXISTING live job stay generic 401.
    assert no_auth.status_code == 401
    assert wrong.status_code == 401
    assert_required_headers(no_auth)
    assert_required_headers(wrong)
    # Content-free: empty body, no token echo, no existence disclosure; the advisory
    # header is still present.
    for resp in (no_auth, wrong):
        assert resp.content == b""
        assert resp.headers["X-OpenVA-Advisory-Boundary"] == "non_advisory"
        assert created["job_token"] not in resp.text
    # An UNKNOWN (or deleted) job is a content-free 404 — job_id is not a credential, so a
    # 404 leaks nothing. It is checked before the token, so no token is echoed.
    with TestClient(make_verify_app()) as client:
        unknown = client.get(
            "/v1/verify/11111111-1111-1111-1111-111111111111",
            headers={"Authorization": "Bearer whatever"},
        )
    assert unknown.status_code == 404
    assert unknown.content == b""
    assert unknown.headers["X-OpenVA-Advisory-Boundary"] == "non_advisory"
    assert "whatever" not in unknown.text


# 5. Token in the query string OR in the path does NOT authenticate (header-only).
def test_token_in_query_or_path_does_not_authenticate():
    with TestClient(make_verify_app()) as client:
        created = create_job(client).json()
        token = created["job_token"]
        job_id = created["job_id"]

        # As a query parameter (no Authorization header): must NOT authenticate.
        # The job exists, but with no Bearer header the token in the query is ignored.
        via_query = client.get(f"/v1/verify/{job_id}?job_token={token}")
        # As the path component: a token in the path is just an unknown (non-UUID) job
        # id — it never authenticates and resolves to a content-free 404.
        via_path = client.get(f"/v1/verify/{token}")

    assert via_query.status_code == 401
    assert via_path.status_code == 404
    # Both poll failures are content-free with the advisory-boundary header.
    for resp in (via_query, via_path):
        assert resp.content == b""
        assert resp.headers["X-OpenVA-Advisory-Boundary"] == "non_advisory"


# 6. Row limit: max_verify_rows + 1 rows -> 413 row_limit_exceeded; no job created.
def test_row_limit_rejected_before_job_creation():
    app = make_verify_app(max_verify_rows=2)
    rows = [{"vendor_name": f"Vendor {i}"} for i in range(3)]  # 3 > 2
    with TestClient(app) as client:
        response = client.post("/v1/verify", headers=AUTH_HEADERS, json={"rows": rows})
        # No job was created.
        assert client.app.state.verify_jobs.active_count() == 0

    assert response.status_code == 413
    assert_required_headers(response)
    body = response.json()
    assert "job_id" not in body
    assert body["error"] == "row_limit_exceeded"
    assert "exceeds the maximum of 2 rows" in body["message"]


# 7. SSRF-negative: a verify row with a url field -> 422 (extra="forbid").
def test_url_field_in_row_is_rejected_422():
    app = make_verify_app()
    with TestClient(app) as client:
        for field in ("url", "candidate_url", "source_url"):
            resp = client.post(
                "/v1/verify",
                headers=AUTH_HEADERS,
                json={"rows": [{"vendor_name": "Stripe", field: "https://evil.invalid/"}]},
            )
            assert resp.status_code == 422, field
        # Any other non-identity field is also rejected.
        resp = client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={"rows": [{"vendor_name": "Stripe", "workspace_id": "ws-1"}]},
        )
        assert resp.status_code == 422
        # An undeclared top-level field is rejected too.
        resp = client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={"rows": [{"vendor_name": "Stripe"}], "callback_url": "https://evil.invalid/"},
        )
        assert resp.status_code == 422


# 8. Constant-time: digests_match unit behaviour + poll uses the digest.
def test_digests_match_unit_and_poll_uses_digest():
    token = new_job_token()
    digest = token_digest(token)
    other = token_digest(new_job_token())
    assert digests_match(digest, digest) is True
    assert digests_match(digest, other) is False

    # Seed a job directly in the in-memory store; poll with its token returns it.
    app = make_verify_app()
    with TestClient(app) as client:
        seeded_token = new_job_token()
        now = datetime.now(timezone.utc)
        record = JobRecord(
            job_id=new_job_id(),
            job_token_digest=token_digest(seeded_token),
            state="received",
            request_ref=new_ref(),
            row_count=1,
            created_at=_iso_z(now),
            updated_at=_iso_z(now),
            expires_at=_iso_z(now + timedelta(hours=1)),
        )
        client.app.state.verify_jobs.create(record)
        response = client.get(
            f"/v1/verify/{record.job_id}",
            headers={"Authorization": f"Bearer {seeded_token}"},
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == record.job_id


# 9. Completed-job poll returns the result blob.
def test_completed_job_poll_returns_result():
    app = make_verify_app()
    with TestClient(app) as client:
        token = new_job_token()
        result_ref = new_ref()
        now = datetime.now(timezone.utc)
        record = JobRecord(
            job_id=new_job_id(),
            job_token_digest=token_digest(token),
            state="completed",
            request_ref=None,
            row_count=1,
            result_ref=result_ref,
            created_at=_iso_z(now),
            updated_at=_iso_z(now),
            expires_at=_iso_z(now + timedelta(hours=1)),
        )
        client.app.state.verify_jobs.create(record)
        client.app.state.verify_results.put(result_ref, {"rows": [{"status": "ok"}]})
        response = client.get(
            f"/v1/verify/{record.job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert body["result"] == {"rows": [{"status": "ok"}]}


# 10. Expired-but-retained job -> content-free 410. Use a recent expiry (a few minutes
#     ago) so the record is still within the retained window (not yet purged to 404).
def test_expired_job_returns_410():
    app = make_verify_app()
    with TestClient(app) as client:
        token = new_job_token()
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        record = JobRecord(
            job_id=new_job_id(),
            job_token_digest=token_digest(token),
            state="received",
            request_ref=new_ref(),
            row_count=1,
            created_at=_iso_z(past - timedelta(hours=1)),
            updated_at=_iso_z(past - timedelta(hours=1)),
            expires_at=_iso_z(past),
        )
        client.app.state.verify_jobs.create(record)
        response = client.get(
            f"/v1/verify/{record.job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 410
    assert_required_headers(response)
    # Content-free: empty body, advisory header present, no token echo.
    assert response.content == b""
    assert response.headers["X-OpenVA-Advisory-Boundary"] == "non_advisory"
    assert token not in response.text


# 11. to_record_dict() validates against the hosted-job-record schema.
def test_record_dict_validates_against_schema():
    now = datetime.now(timezone.utc)
    received = JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(new_job_token()),
        state="received",
        request_ref=new_ref(),
        row_count=1,
        created_at=_iso_z(now),
        updated_at=_iso_z(now),
        expires_at=_iso_z(now + timedelta(hours=24)),
    )
    completed = JobRecord(
        job_id=new_job_id(),
        job_token_digest=token_digest(new_job_token()),
        state="completed",
        request_ref=None,
        row_count=3,
        result_ref=new_ref(),
        created_at=_iso_z(now),
        updated_at=_iso_z(now),
        expires_at=_iso_z(now + timedelta(hours=24)),
    )
    # Both must validate (and the schema's state-dependent invariants must hold).
    jsonschema.validate(received.to_record_dict(), JOB_RECORD_SCHEMA)
    jsonschema.validate(completed.to_record_dict(), JOB_RECORD_SCHEMA)


# 12. CORS preflight from an allowed origin gets the allow-origin header; disallowed not.
def test_cors_preflight_for_verify():
    app = make_verify_app(allowed_origins=("https://example.test",))
    with TestClient(app) as client:
        allowed = client.options(
            "/v1/verify",
            headers={
                "Origin": "https://example.test",
                "Access-Control-Request-Method": "POST",
            },
        )
        disallowed = client.options(
            "/v1/verify",
            headers={
                "Origin": "https://evil.test",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert allowed.headers.get("access-control-allow-origin") == "https://example.test"
    assert disallowed.headers.get("access-control-allow-origin") is None


# 13. Every verify response carries the non-advisory boundary HEADER; success payloads
#     additionally carry not_advice: true in the BODY, while the content-free poll error
#     carries the header but an empty body (no not_advice field).
def test_all_verify_responses_are_non_advisory():
    app = make_verify_app(max_verify_rows=1)
    with TestClient(app) as client:
        created = create_job(client)
        poll_ok = client.get(
            f"/v1/verify/{created.json()['job_id']}",
            headers={"Authorization": f"Bearer {created.json()['job_token']}"},
        )
        poll_401 = client.get(f"/v1/verify/{created.json()['job_id']}")
        over_limit = client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={"rows": [{"vendor_name": "A"}, {"vendor_name": "B"}]},
        )

    assert over_limit.status_code == 413
    # Every response carries the advisory-boundary header.
    for resp in (created, poll_ok, poll_401, over_limit):
        assert resp.headers[HEADER_ADVISORY_BOUNDARY] == "non_advisory"
    # Successful responses (create, poll-200) carry not_advice: true in the body.
    for resp in (created, poll_ok):
        assert resp.status_code == 200
        assert resp.json()["not_advice"] is True
    # The content-free poll error carries the advisory HEADER but an empty body — no
    # not_advice field (no body at all).
    assert poll_401.status_code == 401
    assert poll_401.content == b""


# Pure helper coverage for extract_bearer_token (header-only parsing).
def test_extract_bearer_token_parsing():
    assert extract_bearer_token("Bearer abc123") == "abc123"
    assert extract_bearer_token("bearer abc123") == "abc123"  # case-insensitive scheme
    assert extract_bearer_token("BEARER  abc123 ") == "abc123"  # trims value
    assert extract_bearer_token(None) is None
    assert extract_bearer_token("") is None
    assert extract_bearer_token("Basic abc123") is None
    assert extract_bearer_token("abc123") is None
    assert extract_bearer_token("Bearer ") is None


# 14. Public-read mode does NOT enable verify SUBMISSION (always needs the API key);
#     cached read still works unauthenticated.
def test_public_read_mode_does_not_allow_verify_submission():
    app = make_verify_app(public_read_enabled=True)
    with TestClient(app) as client:
        # Verify submission with NO auth is rejected even in public-read mode.
        no_auth = client.post("/v1/verify", json={"rows": [{"vendor_name": "Stripe"}]})
        # With the API key it is accepted.
        with_key = client.post(
            "/v1/verify", headers=AUTH_HEADERS, json={"rows": [{"vendor_name": "Stripe"}]}
        )
        # Public cached read still works with no auth.
        meta = client.get("/v1/catalog/meta")

    assert no_auth.status_code == 401
    assert with_key.status_code == 200
    assert meta.status_code == 200


# 15. Source types are capped at the hosted verify budget (4): >4 -> 422; 4 -> 200.
def test_verify_source_types_capped_at_budget():
    app = make_verify_app()
    with TestClient(app) as client:
        too_many = client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={
                "rows": [{"vendor_name": "Stripe"}],
                "source_types": ["a", "b", "c", "d", "e"],
            },
        )
        at_budget = client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={
                "rows": [{"vendor_name": "Stripe"}],
                "source_types": ["a", "b", "c", "d"],
            },
        )

    assert too_many.status_code == 422
    assert at_budget.status_code == 200


# 16. Config fails closed if OPENVA_MAX_VERIFY_ROWS exceeds the hard ceiling (20).
def test_config_rejects_verify_rows_above_ceiling():
    with pytest.raises(RuntimeError):
        ServiceConfig(pack_path=Path("."), api_key=API_KEY, max_verify_rows=21)
    # The ceiling itself is accepted.
    accepted = ServiceConfig(pack_path=Path("."), api_key=API_KEY, max_verify_rows=20)
    assert accepted.max_verify_rows == 20


# 17. The active-job cap is NOT enforced in WP-02A (no worker => never wedge).
def test_active_job_cap_not_enforced():
    # Default max_active_jobs is 3; creating 5 jobs must all succeed (no 429).
    app = make_verify_app()
    with TestClient(app) as client:
        for _ in range(5):
            resp = create_job(client)
            assert resp.status_code == 200


# 18. The verify ceilings match the authoritative hosted-deployment contract.
def test_verify_ceilings_match_contract():
    contract = yaml.safe_load(
        Path("docs/operations/contracts/hosted-deployment.yaml").read_text(encoding="utf-8")
    )
    limits = contract["hosted_verify_limits"]
    assert VERIFY_ROWS_HARD_CEILING == limits["max_verify_rows"] == 20
    assert MAX_VERIFY_SOURCE_TYPES == limits["max_source_types_per_verify_row"] == 4


# 19. Minimisation: creating a verify job does NOT retain the submitted identities.
#     WP-02A has no worker to consume the rows, so the transport validates then discards
#     them; only non-identifying metadata (row_count) is retained.
def test_verify_create_does_not_retain_submitted_identities():
    secret_name = "SecretVendorXYZ"
    secret_domain = "secret.example"
    app = make_verify_app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/verify",
            headers=AUTH_HEADERS,
            json={"rows": [{"vendor_name": secret_name, "domain": secret_domain}]},
        )
        assert response.status_code == 200

        # Serialize the FULL internal contents of every verify store and assert the
        # distinctive identity strings appear nowhere.
        jobs = client.app.state.verify_jobs
        envelopes = client.app.state.verify_envelopes
        results = client.app.state.verify_results
        job_records = [record.to_record_dict() for record in jobs._records.values()]
        serialized = json.dumps(
            {
                "jobs": job_records,
                "envelopes": envelopes._envelopes,
                "results": results._results,
            },
            default=str,
        )

    assert secret_name not in serialized
    assert secret_domain not in serialized
    # The minimised envelope retains only row_count (no identities, no raw rows).
    assert list(envelopes._envelopes.values()) == [{"row_count": 1}]
    # The job record still carries its non-null request_ref (schema requires it for
    # `received`) and the row_count, but no identity content.
    assert job_records and job_records[0]["request_ref"] is not None
    assert job_records[0]["row_count"] == 1


# 20. The expiry lifecycle is PHYSICAL, not status-only: a record within the retained
#     window polls 410 and still exists; a record past expires_at + the retained window
#     polls 404 and is physically purged (record + envelope + result gone).
def test_expired_retained_then_physically_deleted_lifecycle():
    app = make_verify_app()
    with TestClient(app) as client:
        now = datetime.now(timezone.utc)
        jobs = client.app.state.verify_jobs
        envelopes = client.app.state.verify_envelopes
        results = client.app.state.verify_results

        # (a) Retained: expired a few minutes ago, still within the retained window.
        retained_token = new_job_token()
        retained_ref = new_ref()
        retained = JobRecord(
            job_id=new_job_id(),
            job_token_digest=token_digest(retained_token),
            state="received",
            request_ref=retained_ref,
            row_count=1,
            created_at=_iso_z(now - timedelta(hours=2)),
            updated_at=_iso_z(now - timedelta(hours=2)),
            expires_at=_iso_z(now - timedelta(minutes=5)),
        )
        jobs.create(retained)
        envelopes.put(retained_ref, {"row_count": 1})

        # (b) Deleted: expired older than expires_at + VERIFY_RETAINED_WINDOW. Carry BOTH
        # a request_ref and a result_ref so the purge is shown to delete the record AND
        # both its referenced transient blobs (the helper reads the refs off the record).
        deleted_token = new_job_token()
        deleted_ref = new_ref()
        deleted_result_ref = new_ref()
        deleted = JobRecord(
            job_id=new_job_id(),
            job_token_digest=token_digest(deleted_token),
            state="received",
            request_ref=deleted_ref,
            result_ref=deleted_result_ref,
            row_count=1,
            created_at=_iso_z(now - timedelta(hours=5)),
            updated_at=_iso_z(now - timedelta(hours=5)),
            expires_at=_iso_z(now - timedelta(hours=VERIFY_RETAINED_WINDOW_HOURS, minutes=5)),
        )
        jobs.create(deleted)
        envelopes.put(deleted_ref, {"row_count": 1})
        results.put(deleted_result_ref, {"rows": [{"status": "ok"}]})

        retained_resp = client.get(
            f"/v1/verify/{retained.job_id}",
            headers={"Authorization": f"Bearer {retained_token}"},
        )
        deleted_resp = client.get(
            f"/v1/verify/{deleted.job_id}",
            headers={"Authorization": f"Bearer {deleted_token}"},
        )

        # Retained: content-free 410, record still present.
        assert retained_resp.status_code == 410
        assert retained_resp.content == b""
        assert retained_resp.headers["X-OpenVA-Advisory-Boundary"] == "non_advisory"
        assert jobs.get(retained.job_id) is not None

        # Deleted: content-free 404, record + envelope + result physically purged.
        assert deleted_resp.status_code == 404
        assert deleted_resp.content == b""
        assert deleted_resp.headers["X-OpenVA-Advisory-Boundary"] == "non_advisory"
        assert jobs.get(deleted.job_id) is None
        assert envelopes.get(deleted_ref) is None
        assert results.get(deleted_result_ref) is None
