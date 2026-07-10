"""Temporary agent-user smoke against current OpenVA main."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service.app import create_app  # noqa: E402
from openva_match_service.config import ServiceConfig  # noqa: E402


def test_agent_enrichment_returns_identity_and_source_references() -> None:
    app = create_app(
        ServiceConfig(
            pack_path=Path("."),
            api_key="smoke-key",
            public_read_enabled=True,
        )
    )
    payload = {
        "vendors": [
            {"row_id": "known", "vendor_name": "Stripe", "domain": "stripe.com"},
            {"row_id": "unknown", "vendor_name": "Definitely Not A Vendor 9000"},
        ],
        "source_types": ["dpa", "privacy_notice"],
    }

    with TestClient(app) as client:
        meta = client.get("/v1/catalog/meta")
        response = client.post("/v1/enrich", json=payload)

    assert meta.status_code == 200
    assert meta.json()["snapshot"]["vendor_count"] > 0
    assert meta.json()["snapshot"]["source_count"] > 0
    assert response.status_code == 200

    body = response.json()
    known, unknown = body["results"]
    assert [known["row_id"], unknown["row_id"]] == ["known", "unknown"]
    assert known["identity"]["match_status"] == "match"
    assert known["identity"]["matched_vendor_id"] == "stripe"
    assert known["source_references"]["dpa"]["status"] == "indexed"
    assert known["source_references"]["dpa"]["url"].startswith("https://")
    assert unknown["identity"]["match_status"] == "no_match"
    assert unknown["identity"]["no_match_reason"] in {
        "no_indexed_openva_match",
        "insufficient_indexed_identity_evidence",
    }
    assert known["not_advice"] is True
    assert unknown["not_advice"] is True
    assert body["not_advice"] is True
