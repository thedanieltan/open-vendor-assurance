"""Tests for the zero-install /v1 catalogue enrichment API (read-only, cached pack)."""

from __future__ import annotations

import asyncio
import shutil
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_pack_reader import OpenVAPack, PackError  # noqa: E402
from openva_vendor_inventory_matcher.matcher import MatcherIndex  # noqa: E402
from openva_vendor_inventory_matcher.core import legal_entity_record, vendor_record  # noqa: E402
from openva_match_service import cli  # noqa: E402
from openva_match_service.app import HEADER_ADVISORY_BOUNDARY, RequestSizeLimitMiddleware, create_app  # noqa: E402
from openva_match_service.config import ServiceConfig, parse_allowed_origins  # noqa: E402
from openva_match_service.service_state import (  # noqa: E402
    build_latest_observation_by_source,
    compute_snapshot_digest,
    load_service_state,
)

API_KEY = "test-api-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


def private_app():
    return create_app(ServiceConfig(pack_path=Path("."), api_key=API_KEY))


def public_app(**overrides):
    return create_app(ServiceConfig(pack_path=Path("."), api_key=API_KEY, public_read_enabled=True, **overrides))


def cors_app(origins):
    return create_app(
        ServiceConfig(pack_path=Path("."), api_key=API_KEY, public_read_enabled=True, allowed_origins=tuple(origins))
    )


def ambiguous_state(base):
    one = vendor_record({"vendor_id": "acme-a", "display_name": "Acme Corp", "legal_name": "Acme Corp", "catalog_status": "active", "official_domains": [], "manifest_path": ""})
    two = vendor_record({"vendor_id": "acme-b", "display_name": "Acme Corp", "legal_name": "Acme Corp", "catalog_status": "active", "official_domains": [], "manifest_path": ""})
    return replace(base, matcher_index=MatcherIndex([one, two], {}, {}, {}, {}, [], {}))


def legal_entity_state(base):
    """A vendor matchable ONLY by registration number (no domain/name overlap), plus a
    canonical source. Exercises the pack-backed legal-entity path that /v1 must keep."""
    vendor = vendor_record({"vendor_id": "regco", "display_name": "Reg Co", "legal_name": "Reg Co Limited", "catalog_status": "active", "official_domains": ["regco.example"], "manifest_path": ""})
    entity = legal_entity_record({"entity_id": "regco-le", "vendor_id": "regco", "legal_name": "Reg Co Limited", "jurisdiction": "GB", "registration_number": "RC-987654", "catalog_status": "active"})
    sources = {"regco": [{"source_id": "regco-dpa", "source_type": "dpa", "source_url": "https://regco.example/dpa", "effective_or_published_at": "2026-01-01"}]}
    return replace(base, matcher_index=MatcherIndex([vendor], {}, sources, {}, {}, [entity], {}))


# --------------------------------------------------------------------------- backward compat


def test_existing_pack_meta_and_match_and_headers_unchanged():
    with TestClient(private_app()) as client:
        meta = client.get("/pack/meta", headers=AUTH)
        assert meta.status_code == 200
        assert meta.json()["profile_id"] == "openva.public-metadata.v1"
        # CSV match is unchanged and still requires the key.
        assert client.post("/match", files={"inventory_csv": ("v.csv", "vendor_name\nStripe\n", "text/csv")}).status_code == 401
        csv = client.post("/match", headers=AUTH, files={"inventory_csv": ("v.csv", "vendor_name,domain\nStripe,stripe.com\n", "text/csv")})
        assert csv.status_code == 200
        assert csv.json()["rows"][0]["matched_vendor_id"] == "stripe"
        assert meta.headers[HEADER_ADVISORY_BOUNDARY] == "non_advisory"
        assert client.get("/healthz").status_code == 200


# --------------------------------------------------------------------------- access policy


def test_v1_requires_key_by_default():
    with TestClient(private_app()) as client:
        assert client.get("/v1/catalog/meta").status_code == 401
        assert client.get("/v1/catalog/meta", headers=AUTH).status_code == 200


def test_v1_public_read_when_enabled():
    with TestClient(public_app()) as client:
        assert client.get("/v1/catalog/meta").status_code == 200
        assert client.post("/v1/match", json={"vendor_name": "Stripe"}).status_code == 200


def test_public_mode_does_not_expose_any_write_endpoint():
    # There is no write/submission endpoint to expose; existing mutating verbs 404/405.
    with TestClient(public_app()) as client:
        assert client.post("/v1/vendors/stripe", json={}).status_code in {404, 405}
        assert client.put("/v1/catalog/meta", json={}).status_code in {404, 405}


# --------------------------------------------------------------------------- configuration


def test_allowed_origins_parsing():
    assert parse_allowed_origins("") == ()
    assert parse_allowed_origins("  ") == ()
    assert parse_allowed_origins("https://a.example, https://b.example ,") == ("https://a.example", "https://b.example")
    assert parse_allowed_origins("https://a.example, https://a.example") == ("https://a.example",)


def test_empty_cors_config_is_not_wildcard():
    with TestClient(private_app()) as client:
        resp = client.get("/v1/catalog/meta", headers={**AUTH, "Origin": "https://anything.example"})
        assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_invalid_commit_sha_rejected(monkeypatch):
    monkeypatch.setenv("OPENVA_PACK_PATH", ".")
    monkeypatch.setenv("OPENVA_SERVICE_API_KEY", "k")
    monkeypatch.setenv("OPENVA_CATALOG_COMMIT_SHA", "not-a-sha")
    with pytest.raises(RuntimeError):
        ServiceConfig.from_env()


def test_valid_commit_sha_accepted_and_surfaced(monkeypatch):
    sha = "a" * 40
    monkeypatch.setenv("OPENVA_PACK_PATH", ".")
    monkeypatch.setenv("OPENVA_SERVICE_API_KEY", API_KEY)
    monkeypatch.setenv("OPENVA_CATALOG_COMMIT_SHA", sha)
    config = ServiceConfig.from_env()
    assert config.catalog_commit_sha == sha
    with TestClient(create_app(config)) as client:
        assert client.get("/v1/catalog/meta", headers=AUTH).json()["snapshot"]["catalog_commit_sha"] == sha


def test_commit_sha_null_when_not_configured():
    with TestClient(private_app()) as client:
        assert client.get("/v1/catalog/meta", headers=AUTH).json()["snapshot"]["catalog_commit_sha"] is None


# --------------------------------------------------------------------------- catalogue metadata


def test_catalog_meta_returns_guarantees_and_snapshot_counts_match_pack():
    with TestClient(private_app()) as client:
        body = client.get("/v1/catalog/meta", headers=AUTH).json()
        pack_meta = client.get("/pack/meta", headers=AUTH).json()
    assert body["guarantees"] == {
        "public_sources_only": True,
        "metadata_first": True,
        "non_advisory": True,
        "raw_documents_mirrored_by_default": False,
    }
    snap = body["snapshot"]
    assert snap["vendor_count"] == pack_meta["counts"]["vendors"] > 0
    assert snap["source_count"] == pack_meta["counts"]["sources"] > 0
    assert snap["snapshot_digest"].startswith("sha256:")
    assert body["not_advice"] is True


def test_snapshot_digest_is_deterministic():
    assert compute_snapshot_digest(OpenVAPack.load(".")) == compute_snapshot_digest(OpenVAPack.load("."))
    assert load_service_state(".").snapshot_digest == load_service_state(".").snapshot_digest


def test_snapshot_digest_changes_when_pack_bytes_change(tmp_path):
    shutil.copy("openva-pack.json", tmp_path / "openva-pack.json")
    shutil.copytree("indexes", tmp_path / "indexes")
    pack = OpenVAPack.load(tmp_path)
    before = compute_snapshot_digest(pack)
    summary = tmp_path / "indexes" / "summary.json"
    summary.write_bytes(summary.read_bytes() + b" ")
    fake = types.SimpleNamespace(pack_root=pack.pack_root, manifest=pack.manifest)
    assert compute_snapshot_digest(fake) != before


# --------------------------------------------------------------------------- vendor access


def test_known_vendor_returns_canonical_sources_only():
    with TestClient(private_app()) as client:
        body = client.get("/v1/vendors/stripe", headers=AUTH).json()
    assert body["vendor"]["display_name"]
    assert all("_openva_path" not in key for key in body["vendor"])
    assert body["canonical_sources"]
    assert all(src["canonical"] is True and src["record_class"] == "canonical" for src in body["canonical_sources"])
    assert body["not_advice"] is True


def test_unknown_or_unsafe_vendor_returns_404():
    with TestClient(private_app()) as client:
        assert client.get("/v1/vendors/no-such-vendor-xyz", headers=AUTH).status_code == 404
        assert client.get("/v1/vendors/..", headers=AUTH).status_code == 404
        body = client.get("/v1/vendors/no-such-vendor-xyz", headers=AUTH).json()
    assert body == {"error": "http_error", "message": "vendor not found"}


def test_vendor_source_type_filter():
    with TestClient(private_app()) as client:
        only_dpa = client.get("/v1/vendors/stripe/sources", headers=AUTH, params={"source_type": "dpa"}).json()
        unknown = client.get("/v1/vendors/stripe/sources", headers=AUTH, params={"source_type": "made_up_type"}).json()
        all_sources = client.get("/v1/vendors/stripe/sources", headers=AUTH).json()
    assert only_dpa["source_types_requested"] == ["dpa"]
    assert {s["source_type"] for s in only_dpa["sources"]} == {"dpa"}
    assert unknown["sources"] == []  # unknown source type -> empty filtered result
    assert len(all_sources["sources"]) >= len(only_dpa["sources"])


# --------------------------------------------------------------------------- matching


def test_match_by_domain_name_and_business_entity():
    with TestClient(private_app()) as client:
        by_domain = client.post("/v1/match", headers=AUTH, json={"domain": "stripe.com"}).json()["match"]
        by_name = client.post("/v1/match", headers=AUTH, json={"vendor_name": "Stripe"}).json()["match"]
        by_entity = client.post("/v1/match", headers=AUTH, json={"business_entity_name": "Slack Technologies LLC"}).json()["match"]
    assert by_domain["status"] == "matched" and by_domain["method"] == "domain_exact" and by_domain["confidence"] == 1.0
    assert by_name["status"] == "matched" and by_name["vendor_id"] == "stripe"
    assert by_entity["status"] == "matched" and by_entity["vendor_id"] == "slack"


def test_no_match_is_not_forced():
    with TestClient(private_app()) as client:
        match = client.post("/v1/match", headers=AUTH, json={"vendor_name": "Definitely Not A Vendor 9000"}).json()["match"]
    assert match["status"] == "no_match"
    assert match["vendor_id"] is None and match["confidence"] is None


def test_ambiguous_match_keeps_candidates_and_is_not_collapsed():
    with TestClient(public_app()) as client:
        client.app.state.service_state = ambiguous_state(client.app.state.service_state)
        match = client.post("/v1/match", json={"vendor_name": "Acme Corp"}).json()["match"]
    assert match["status"] == "ambiguous"
    assert match["vendor_id"] is None
    assert {c["vendor_id"] for c in match["candidates"]} == {"acme-a", "acme-b"}


def test_match_requires_at_least_one_identity_field():
    with TestClient(private_app()) as client:
        empty = client.post("/v1/match", headers=AUTH, json={})
        blanks = client.post("/v1/match", headers=AUTH, json={"vendor_name": "  ", "domain": ""})
    assert empty.status_code == 422
    assert blanks.status_code == 422
    assert empty.json() == {"error": "validation_error", "message": "Invalid match service request"}


# --------------------------------------------------------------------------- enrichment


def test_enrich_preserves_order_row_ids_and_duplicates():
    payload = {
        "vendors": [
            {"row_id": "12", "vendor_name": "Stripe", "domain": "stripe.com"},
            {"row_id": 7, "vendor_name": "Stripe", "domain": "stripe.com"},  # duplicate, int row_id
            {"row_id": "x", "vendor_name": "Definitely Not A Vendor 9000"},
        ]
    }
    with TestClient(private_app()) as client:
        body = client.post("/v1/enrich", headers=AUTH, json=payload).json()
    results = body["results"]
    assert [r["row_id"] for r in results] == ["12", 7, "x"]  # preserved exactly, types intact
    assert results[0]["match"]["vendor_id"] == "stripe" and results[1]["match"]["vendor_id"] == "stripe"
    assert results[2]["match"]["status"] == "no_match"
    assert "snapshot" in body and all("snapshot" not in r for r in results)  # snapshot once, at response level
    assert all(r["not_advice"] is True for r in results) and body["not_advice"] is True


def test_enrich_source_type_selection_and_missing_types_are_null():
    payload = {"vendors": [{"row_id": "1", "domain": "stripe.com"}], "source_types": ["dpa", "trust_center"]}
    with TestClient(private_app()) as client:
        result = client.post("/v1/enrich", headers=AUTH, json=payload).json()["results"][0]
    assert result["spreadsheet"]["openva_dpa"]  # stripe has a DPA
    assert result["spreadsheet"]["openva_trust_center"] is None  # stripe has no trust centre
    assert "Matched vendor has no canonical trust centre source" in result["notes"]
    assert {s["source_type"] for s in result["sources"]} <= {"dpa", "trust_center"}
    assert "dpa" in result["primary_source_by_type"]  # reuses matcher primary choice
    assert result["source_urls_by_type"]["dpa"]


def test_enrich_ambiguous_and_no_match_projection_is_empty():
    with TestClient(public_app()) as client:
        client.app.state.service_state = ambiguous_state(client.app.state.service_state)
        amb = client.post("/v1/enrich", json={"vendors": [{"row_id": "1", "vendor_name": "Acme Corp"}]}).json()["results"][0]
    assert amb["match"]["status"] == "ambiguous"
    assert amb["sources"] == [] and amb["primary_source_by_type"] == {} and amb["source_urls_by_type"] == {}
    assert amb["spreadsheet"]["openva_dpa"] is None
    assert amb["notes"] == ["Ambiguous vendor match"]


def test_enrich_rejects_empty_list_and_enforces_row_cap():
    with TestClient(private_app()) as client:
        assert client.post("/v1/enrich", headers=AUTH, json={"vendors": []}).status_code == 422
    capped = create_app(ServiceConfig(pack_path=Path("."), api_key=API_KEY, max_rows=1))
    with TestClient(capped) as client:
        resp = client.post("/v1/enrich", headers=AUTH, json={"vendors": [{"vendor_name": "Stripe"}, {"vendor_name": "Slack"}]})
    assert resp.status_code == 413


def test_enrich_preserves_registration_number_matching():
    # Regression: /v1/enrich must keep the pack-backed registration-number match path.
    # A row with ONLY a registration number resolves via the legal entity to the vendor
    # and returns that vendor's sources — it must not silently become no_match.
    with TestClient(public_app()) as client:
        client.app.state.service_state = legal_entity_state(client.app.state.service_state)
        result = client.post(
            "/v1/enrich",
            json={"vendors": [{"row_id": "1", "registration_number": "RC-987654"}], "source_types": ["dpa"]},
        ).json()["results"][0]
    assert result["match"]["status"] == "matched"
    assert result["match"]["vendor_id"] == "regco"
    assert result["match"]["method"] == "registration_number_exact"
    assert result["spreadsheet"]["openva_dpa"] == "https://regco.example/dpa"
    assert result["source_urls_by_type"]["dpa"] == ["https://regco.example/dpa"]


def test_match_preserves_registration_number_matching():
    # The single-identity /v1/match path keeps the same capability.
    with TestClient(public_app()) as client:
        client.app.state.service_state = legal_entity_state(client.app.state.service_state)
        match = client.post("/v1/match", json={"registration_number": "RC-987654"}).json()["match"]
    assert match["status"] == "matched"
    assert match["vendor_id"] == "regco"
    assert match["method"] == "registration_number_exact"


def test_enrich_item_requires_identity_field():
    with TestClient(private_app()) as client:
        assert client.post("/v1/enrich", headers=AUTH, json={"vendors": [{"row_id": "1"}]}).status_code == 422


def test_enrich_row_rejects_unknown_workspace_fields():
    # Authority boundary: the shared row sets additionalProperties:false, so an
    # undeclared workspace column must be rejected, not silently ignored.
    with TestClient(private_app()) as client:
        resp = client.post(
            "/v1/enrich",
            headers=AUTH,
            json={"vendors": [{"row_id": "1", "vendor_name": "Stripe", "spreadsheet_id": "sheet-123"}]},
        )
    assert resp.status_code == 422
    assert resp.json() == {"error": "validation_error", "message": "Invalid match service request"}


def test_match_rejects_unknown_workspace_fields():
    with TestClient(private_app()) as client:
        resp = client.post("/v1/match", headers=AUTH, json={"vendor_name": "Stripe", "workspace_id": "ws-9"})
    assert resp.status_code == 422


def test_enrich_envelope_rejects_unknown_top_level_field():
    # The enrich envelope fails closed too: an undeclared top-level field (e.g. a
    # workspace token) must be rejected, not silently discarded (ADR-0004 boundary).
    with TestClient(private_app()) as client:
        resp = client.post(
            "/v1/enrich",
            headers=AUTH,
            json={"vendors": [{"vendor_name": "Stripe"}], "workspace_token": "secret"},
        )
    assert resp.status_code == 422


def test_enrich_row_id_rejects_non_string_non_integer():
    with TestClient(private_app()) as client:
        assert client.post("/v1/enrich", headers=AUTH, json={"vendors": [{"row_id": 1.5, "vendor_name": "Stripe"}]}).status_code == 422


# --------------------------------------------------------------------------- observation metadata


def test_observation_index_maps_latest_by_source_and_missing_is_null():
    fake = types.SimpleNamespace(
        observations=lambda: [
            {"source_id": "s1", "observed_at": "2026-01-01T00:00:00Z", "result": "ok"},
            {"source_id": "s1", "observed_at": "2026-02-01T00:00:00Z", "result": "unreachable"},
            {"source_id": "s2", "observed_at": "2026-01-15T00:00:00Z", "result": "ok"},
            {"observed_at": "2026-03-01T00:00:00Z", "result": "ok"},  # no source_id -> skipped
        ]
    )
    index = build_latest_observation_by_source(fake)
    assert index["s1"]["result"] == "unreachable"  # latest by observed_at
    assert index["s2"]["result"] == "ok"
    assert "absent" not in index


def test_real_pack_sources_report_null_observation_without_network():
    # Observations index is empty in the shipped pack; per-source fields are null and no
    # network call is made (the modules import no HTTP client).
    with TestClient(private_app()) as client:
        sources = client.get("/v1/vendors/stripe/sources", headers=AUTH).json()["sources"]
    assert all(s["last_observed_at"] is None and s["latest_observation_status"] is None for s in sources)
    for module in ("enrichment", "service_state"):
        text = Path(f"services/openva_match_service/openva_match_service/{module}.py").read_text(encoding="utf-8")
        for forbidden in ("import requests", "import httpx", "urllib.request", "socket."):
            assert forbidden not in text


# --------------------------------------------------------------------------- CORS


def test_cors_allows_configured_origin_and_preflight():
    origin = "https://sheets.example"
    with TestClient(cors_app([origin])) as client:
        simple = client.get("/v1/catalog/meta", headers={"Origin": origin})
        preflight = client.options(
            "/v1/enrich",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"},
        )
    assert simple.headers["access-control-allow-origin"] == origin
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert "POST" in preflight.headers.get("access-control-allow-methods", "")


def test_cors_does_not_permit_unconfigured_origin_or_credentialed_wildcard():
    with TestClient(cors_app(["https://sheets.example"])) as client:
        resp = client.get("/v1/catalog/meta", headers={"Origin": "https://evil.example"})
    headers = {k.lower(): v for k, v in resp.headers.items()}
    assert headers.get("access-control-allow-origin") != "*"
    assert "access-control-allow-origin" not in headers  # disallowed origin gets nothing
    assert headers.get("access-control-allow-credentials") != "true"


# --------------------------------------------------------------------------- OpenAPI


def test_openapi_describes_all_v1_endpoints_without_secrets():
    with TestClient(private_app()) as client:
        spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for route in ["/v1/catalog/meta", "/v1/vendors/{vendor_id}", "/v1/vendors/{vendor_id}/sources", "/v1/match", "/v1/enrich"]:
        assert route in paths, route
    schemas = spec["components"]["schemas"]
    for model in ["CatalogMetaResponse", "EnrichRequest", "EnrichResponse", "MatchResponse", "VendorDetailResponse", "VendorSourcesResponse", "Snapshot"]:
        assert model in schemas, model
    assert API_KEY not in client.get("/openapi.json").text


# --------------------------------------------------------------------------- no persistence


def test_enrich_does_not_persist_request_data_or_mutate_state(tmp_path):
    payload = {"vendors": [{"row_id": "1", "vendor_name": "SecretVendorName", "domain": "secret.example"}]}
    with TestClient(private_app()) as client:
        before = set(client.app.state._state.keys())
        client.post("/v1/enrich", headers=AUTH, json=payload)
        after = set(client.app.state._state.keys())
    # No per-request attributes accumulate on app.state (the invariant). The baseline is
    # the app-LEVEL state set up once at startup: config + service_state plus the WP-02H
    # provider-neutral controls (telemetry sink, rate-limit policy, concurrency limiter),
    # all constructed at app build time and never mutated per request.
    assert before == after
    assert after == {"config", "service_state", "telemetry", "rate_limiter", "verify_concurrency"}
    # No request payload is written into the service modules / no DB or store is created.
    for module in ("app", "enrichment", "service_state"):
        text = Path(f"services/openva_match_service/openva_match_service/{module}.py").read_text(encoding="utf-8")
        assert "sqlite" not in text.lower() and "open(" not in text.replace("read_bytes", "")


# --------------------------------------------------------------------------- request-size limit


def bounded_app(max_request_bytes):
    return create_app(ServiceConfig(pack_path=Path("."), api_key=API_KEY, max_request_bytes=max_request_bytes))


def test_oversize_v1_match_json_rejected_with_413_envelope_and_headers():
    with TestClient(bounded_app(300)) as client:
        resp = client.post("/v1/match", headers=AUTH, json={"vendor_name": "Z" * 5000})
    assert resp.status_code == 413
    assert resp.json() == {"error": "http_error", "message": "request body exceeds the maximum of 300 bytes"}
    assert resp.headers[HEADER_ADVISORY_BOUNDARY] == "non_advisory"


def test_oversize_v1_enrich_json_rejected_413():
    with TestClient(bounded_app(300)) as client:
        resp = client.post("/v1/enrich", headers=AUTH, json={"vendors": [{"row_id": "1", "vendor_name": "X" * 5000}]})
    assert resp.status_code == 413


def test_boundary_size_json_is_accepted():
    # A body comfortably under the cap is processed normally.
    with TestClient(bounded_app(2000)) as client:
        resp = client.post("/v1/match", headers=AUTH, json={"vendor_name": "Stripe", "domain": "stripe.com"})
    assert resp.status_code == 200
    assert resp.json()["match"]["status"] == "matched"


def test_chunked_oversize_without_content_length_is_rejected():
    # Drives the middleware directly with a streamed body and no Content-Length header.
    app_called = {"value": False}

    async def downstream(scope, receive, send):
        app_called["value"] = True

    middleware = RequestSizeLimitMiddleware(downstream, max_bytes=10)
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    messages = [
        {"type": "http.request", "body": b"x" * 6, "more_body": True},
        {"type": "http.request", "body": b"y" * 6, "more_body": False},
    ]
    iterator = iter(messages)

    async def receive():
        return next(iterator)

    scope = {"type": "http", "path": "/v1/enrich", "headers": []}  # no content-length
    asyncio.run(middleware(scope, receive, send))

    assert app_called["value"] is False  # downstream never invoked
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert starts and starts[0]["status"] == 413


def test_excessively_long_identity_field_is_rejected_422():
    with TestClient(private_app()) as client:
        resp = client.post("/v1/match", headers=AUTH, json={"vendor_name": "Z" * 600})
    assert resp.status_code == 422


def test_excessively_large_source_types_array_is_rejected_422():
    with TestClient(private_app()) as client:
        resp = client.post("/v1/enrich", headers=AUTH, json={"vendors": [{"vendor_name": "Stripe"}], "source_types": ["dpa"] * 100})
    assert resp.status_code == 422


def test_existing_csv_match_is_exempt_from_request_byte_limit():
    # /match keeps its own byte cap; the JSON request-byte limit does not bound it.
    csv_body = "vendor_name,domain\nStripe,stripe.com\n"  # ~37 bytes of content, larger multipart envelope
    with TestClient(bounded_app(50)) as client:
        resp = client.post("/match", headers=AUTH, files={"inventory_csv": ("v.csv", csv_body, "text/csv")})
    assert resp.status_code == 200
    assert resp.json()["rows"][0]["matched_vendor_id"] == "stripe"


# --------------------------------------------------------------------------- access logging


def test_access_log_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OPENVA_ACCESS_LOG_ENABLED", raising=False)
    assert cli.access_log_enabled() is False


def test_access_log_enabled_only_when_configured(monkeypatch):
    monkeypatch.setenv("OPENVA_ACCESS_LOG_ENABLED", "true")
    assert cli.access_log_enabled() is True
    monkeypatch.setenv("OPENVA_ACCESS_LOG_ENABLED", "false")
    assert cli.access_log_enabled() is False


def test_launcher_passes_access_log_false_by_default(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.delenv("OPENVA_ACCESS_LOG_ENABLED", raising=False)
    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    assert cli.main() == 0
    assert captured["access_log"] is False


# --------------------------------------------------------------------------- vendor 404 vs 500


def test_known_vendor_with_corrupt_manifest_is_500_without_leaking_paths():
    with TestClient(private_app(), raise_server_exceptions=False) as client:
        state = client.app.state.service_state
        # stripe is a known vendor; simulate pack corruption that references an internal path.
        state.pack.vendor = lambda vid: (_ for _ in ()).throw(PackError("escapes pack root: /secret/internal/manifest.json"))
        resp = client.get("/v1/vendors/stripe", headers=AUTH)
    assert resp.status_code == 500
    assert resp.json() == {"error": "internal_error", "message": "Internal OpenVA match service error"}
    assert "/secret" not in resp.text and "escapes pack root" not in resp.text
