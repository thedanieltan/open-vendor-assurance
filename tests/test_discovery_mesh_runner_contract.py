from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_discovery_mesh_runner_contract_has_no_vendor_cap() -> None:
    contract = yaml.safe_load(
        (ROOT / "docs" / "operations" / "contracts" / "discovery-mesh-runner.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert contract["runner"]["catalog_vendor_cap"] is None
    assert contract["runner"]["default_vendor_limit"] is None
    assert contract["runner"]["writes_canonical_state"] is False
    assert contract["aggregate"]["stages_candidate_sources"] is True
    assert contract["promotion"]["authority_workflow"] == "candidate-promotion-pr.yml"
