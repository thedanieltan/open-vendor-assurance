"""Temporary isolated agent-user transport smoke; this branch is never merged."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))
sys.path.insert(0, str(Path("services/openva_match_service").resolve()))

from openva_match_service.app import create_app  # noqa: E402
from openva_match_service.config import ServiceConfig  # noqa: E402


def test_agent_can_call_enrichment_endpoint() -> None:
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
        response = client.post("/v1/enrich", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["not_advice"] is True
    assert len(body["results"]) == 2
    assert [row["row_id"] for row in body["results"]] == ["known", "unknown"]
