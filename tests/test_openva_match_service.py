from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_pack_reader import PackError  # noqa: E402
from openva_match_service.app import (  # noqa: E402
    HEADER_ADVISORY_BOUNDARY,
    HEADER_PACK_GENERATED_AT,
    HEADER_PACK_PROFILE,
    HEADER_PACK_SCHEMA_VERSION,
    HEADER_SERVICE_VERSION,
    create_app,
)
from openva_match_service.config import ServiceConfig  # noqa: E402
from openva_match_service.conversion import typed_row  # noqa: E402

API_KEY = "test-api-key"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}
REQUIRED_HEADERS = {
    HEADER_SERVICE_VERSION,
    HEADER_PACK_PROFILE,
    HEADER_PACK_SCHEMA_VERSION,
    HEADER_PACK_GENERATED_AT,
    HEADER_ADVISORY_BOUNDARY,
}


def test_startup_fails_when_pack_path_is_invalid(tmp_path):
    app = create_app(ServiceConfig(pack_path=tmp_path / "missing-pack", api_key=API_KEY))

    with pytest.raises(PackError), TestClient(app):
        pass


def test_pack_meta_returns_metadata_and_required_headers():
    with TestClient(make_test_app()) as client:
        response = client.get("/pack/meta", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert_required_headers(response)
    data = response.json()
    assert data["profile_id"] == "openva.public-metadata.v1"
    assert data["schema_version"] == "openva-export-pack.v1"
    assert data["generated_at"] == "1970-01-01T00:00:00Z"
    assert data["non_advisory"] is True
    assert data["counts"]["vendors"] > 0
    assert data["counts"]["sources"] > 0
    assert "candidate_sources" in data["counts"]
    assert "unavailable_sources" in data["counts"]


def test_match_requires_valid_api_key():
    with TestClient(make_test_app()) as client:
        missing = client.get("/pack/meta")
        invalid = client.get("/pack/meta", headers={"Authorization": "Bearer wrong"})

    for response in [missing, invalid]:
        assert response.status_code == 401
        assert_required_headers(response)
        assert response.json() == {"error": "http_error", "message": "missing or invalid API key"}


def test_match_csv_upload_matches_stripe_and_slack():
    csv_body = "vendor_name,business_entity_name,domain\nStripe,,\n,Slack Technologies LLC,\n"

    with TestClient(make_test_app()) as client:
        response = client.post(
            "/match",
            headers=AUTH_HEADERS,
            files={"inventory_csv": ("vendors.csv", csv_body, "text/csv")},
        )

    assert response.status_code == 200
    assert_required_headers(response)
    payload = response.json()
    assert payload["meta"]["advisory_boundary"] == "non_advisory"
    rows = payload["rows"]
    assert [row["matched_vendor_id"] for row in rows] == ["stripe", "slack"]
    assert [row["match_status"] for row in rows] == ["matched", "matched"]
    assert rows[0]["match_confidence"] == 0.9
    assert rows[1]["business_entity_name"] == "Slack Technologies LLC"
    assert rows[0]["canonical"] is False
    assert rows[0]["canonical_sources_available"] is True


def test_match_response_uses_native_json_fields_and_strips_json_suffixes():
    csv_body = "vendor_name,domain,category\nStripe,stripe.com,payments\n"

    with TestClient(make_test_app()) as client:
        response = client.post(
            "/match",
            headers=AUTH_HEADERS,
            files={"inventory_csv": ("vendors.csv", csv_body, "text/csv")},
        )

    row = response.json()["rows"][0]
    assert "candidate_matches_json" not in row
    assert "canonical_sources_json" not in row
    assert "primary_source_by_type_json" not in row
    assert "legal_entities_json" not in row
    assert "candidate_legal_entities_json" not in row
    assert "legal_entity_match_basis" not in row
    assert "legal_entity_match_status" not in row
    assert "dpa_contracting_entity_verification_status" not in row
    assert "dpa_contracting_entity_verification_note" not in row
    assert isinstance(row["candidate_matches"], list)
    assert isinstance(row["official_domains"], list)
    assert isinstance(row["canonical_sources"], list)
    assert isinstance(row["candidate_sources"], list)
    assert isinstance(row["primary_source_by_type"], dict)
    assert isinstance(row["legal_entities"], list)
    assert isinstance(row["candidate_legal_entities"], list)
    assert row["legal_entity_match_method"] == "unresolved"
    assert row["legal_entity_resolution_confidence"] == "unresolved"
    assert "dpa" in row["primary_source_by_type"]


def test_match_accepts_business_entity_name_without_domain_or_vendor_name():
    csv_body = "business_entity_name\nStripe Inc\n"

    with TestClient(make_test_app()) as client:
        response = client.post(
            "/match",
            headers=AUTH_HEADERS,
            files={"inventory_csv": ("vendors.csv", csv_body, "text/csv")},
        )

    row = response.json()["rows"][0]
    assert row["business_entity_name"] == "Stripe Inc"
    assert row["match_status"] == "matched"
    assert row["matched_vendor_id"] == "stripe"


def test_no_match_row_survives_csv_to_json_conversion():
    csv_body = "vendor_name,domain,category\nNo Such Vendor,nosuchvendor.invalid,unknown\n"

    with TestClient(make_test_app()) as client:
        response = client.post(
            "/match",
            headers=AUTH_HEADERS,
            files={"inventory_csv": ("vendors.csv", csv_body, "text/csv")},
        )

    row = response.json()["rows"][0]
    assert row["match_status"] == "no_match"
    assert row["matched_vendor_id"] is None
    assert row["match_confidence"] is None
    assert row["candidate_matches"] == []
    assert row["canonical_sources"] is None


def test_ambiguous_row_conversion_keeps_native_candidates():
    converted = typed_row(
        {
            "vendor_name": "Shared Name",
            "domain": "",
            "match_status": "ambiguous",
            "matched_vendor_id": "",
            "matched_display_name": "",
            "match_confidence": "",
            "match_method": "",
            "candidate_matches_json": (
                '[{"display_name":"Shared Name","match_confidence":0.9,'
                '"match_method":"name_exact","vendor_id":"shared-a"}]'
            ),
            "canonical": "false",
            "advisory_boundary": "non_advisory",
        },
        ["vendor_name", "domain"],
    )

    assert converted["match_status"] == "ambiguous"
    assert converted["matched_vendor_id"] is None
    assert converted["match_confidence"] is None
    assert converted["candidate_matches"] == [
        {
            "display_name": "Shared Name",
            "match_confidence": 0.9,
            "match_method": "name_exact",
            "vendor_id": "shared-a",
        }
    ]
    assert converted["canonical"] is False


def test_match_rejects_non_csv_upload():
    with TestClient(make_test_app()) as client:
        response = client.post(
            "/match",
            headers=AUTH_HEADERS,
            files={"inventory_csv": ("vendors.txt", "hello", "text/plain")},
        )

    assert response.status_code == 400
    assert_required_headers(response)
    assert response.json() == {"error": "http_error", "message": "inventory_csv must be a CSV upload"}


def test_missing_upload_uses_contract_error_shape():
    with TestClient(make_test_app()) as client:
        response = client.post("/match", headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert_required_headers(response)
    assert response.json() == {"error": "validation_error", "message": "Invalid match service request"}


def assert_required_headers(response) -> None:
    for header in REQUIRED_HEADERS:
        assert header in response.headers
    assert response.headers[HEADER_ADVISORY_BOUNDARY] == "non_advisory"
    assert response.headers[HEADER_PACK_PROFILE] == "openva.public-metadata.v1"
    assert response.headers[HEADER_PACK_SCHEMA_VERSION] == "openva-export-pack.v1"


def make_test_app():
    return create_app(ServiceConfig(pack_path=Path("."), api_key=API_KEY))
