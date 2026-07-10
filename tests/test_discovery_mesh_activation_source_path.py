import json
from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def test_written_plan_records_source_plan_path(tmp_path: Path) -> None:
    action = {
        "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
        "vendor_id": "alpha",
        "source_type": "dpa",
        "candidate_source_id": "alpha-dpa",
    }
    paths, _ = build_vendor_promotion_plans(
        {"actions": [action]},
        source_plan_path="reports/mesh-promotion-plan.raw.json",
        run_token="run-1",
        output_root=tmp_path,
    )
    assert json.loads(paths[0].read_text(encoding="utf-8"))["source_plan_path"] == "reports/mesh-promotion-plan.raw.json"
