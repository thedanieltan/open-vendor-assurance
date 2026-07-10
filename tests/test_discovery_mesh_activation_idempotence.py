import json
from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def test_rebuilding_same_run_replaces_deterministic_vendor_plan(tmp_path: Path) -> None:
    action = {
        "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
        "vendor_id": "alpha",
        "candidate_source_id": "alpha-dpa",
        "source_type": "dpa",
    }
    first, _ = build_vendor_promotion_plans(
        {"actions": [action]}, source_plan_path="raw.json", run_token="run-1", output_root=tmp_path
    )
    second, _ = build_vendor_promotion_plans(
        {"actions": [action]}, source_plan_path="raw.json", run_token="run-1", output_root=tmp_path
    )
    assert first == second
    assert json.loads(first[0].read_text(encoding="utf-8"))["vendor_id"] == "alpha"
