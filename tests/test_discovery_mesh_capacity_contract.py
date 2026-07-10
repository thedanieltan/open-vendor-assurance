from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_discovery_mesh_capacity_contract_is_unbounded() -> None:
    contract = yaml.safe_load(
        (ROOT / "docs" / "operations" / "contracts" / "discovery-mesh-capacity.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert contract["catalog_capacity"]["vendor_count_cap"] is None
    assert contract["catalog_capacity"]["posture"] == "unbounded"
    assert contract["execution"]["default_vendor_limit"] is None
    assert contract["execution"]["deterministic_sharding"] is True
    assert contract["mutation"]["candidate_staging_only"] is True
