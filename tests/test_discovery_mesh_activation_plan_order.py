from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def test_vendor_plan_order_is_deterministic(tmp_path: Path) -> None:
    actions = [
        {
            "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
            "vendor_id": vendor,
            "candidate_source_id": f"{vendor}-dpa",
            "source_type": "dpa",
        }
        for vendor in ("zeta", "alpha", "middle")
    ]
    paths, _ = build_vendor_promotion_plans(
        {"actions": actions},
        source_plan_path="raw.json",
        run_token="ordered",
        output_root=tmp_path,
    )
    assert [path.stem for path in paths] == ["alpha", "middle", "zeta"]
