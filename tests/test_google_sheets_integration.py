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


def test_agent_can_read_public_catalog_metadata() -> None:
    app = create_app(
        ServiceConfig(
            pack_path=Path("."),
            api_key="smoke-key",
            public_read_enabled=True,
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/catalog/meta")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshot"]["vendor_count"] > 0
    assert body["snapshot"]["source_count"] > 0
