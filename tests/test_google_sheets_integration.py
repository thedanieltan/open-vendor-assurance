"""Temporary exact smoke for PR #617; this branch is never merged."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service.app import create_app  # noqa: E402
from openva_match_service.config import ServiceConfig  # noqa: E402


def test_repaired_agent_contract_end_to_end() -> None:
    app = create_app(ServiceConfig(pack_path=Path("."), api_key="smoke-key", public_read_enabled=True))
    payload = {
        "vendors": [
            {"row_id": "known", "vendor_name": "ADP", "domain": "adp.com"},
            {"row_id": "unknown", "vendor_name": "Definitely Not A Vendor 9000"},
        ],
        "source_types": ["dpa", "privacy_notice"],
    }

    with TestClient(app) as client:
        meta = client.get("/v1/catalog/meta")
        response = client.post("/v1/enrich", json=payload)

    assert meta.status_code == 200, meta.text
    assert meta.json()["snapshot"]["vendor_count"] > 0
    assert meta.json()["snapshot"]["source_count"] > 0
    assert response.status_code == 200, response.text

    body = response.json()
    known, unknown = body["results"]
    assert known["identity"]["match_status"] == "match", known
    assert known["identity"]["matched_vendor_id"] == "adp", known
    assert known["source_references"]["dpa"]["status"] == "indexed", known
    assert known["source_references"]["dpa"]["url"].startswith("https://"), known
    assert unknown["identity"]["match_status"] == "no_match", unknown
    assert unknown["source_references"] == {}, unknown
    assert body["not_advice"] is True
    assert known["not_advice"] is True
    assert unknown["not_advice"] is True
