from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_unbounded_capacity_fixture() -> None:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "discovery-mesh" / "unbounded-capacity.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["catalog_capacity"]["vendor_count_cap"] is None
    assert fixture["catalog_capacity"]["posture"] == "unbounded"
    assert fixture["execution"]["default_vendor_limit"] is None
