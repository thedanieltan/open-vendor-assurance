from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def test_vendor_plan_builder_is_exhaustive_above_one_thousand_vendors(tmp_path: Path) -> None:
    plan = {
        "actions": [
            {
                "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
                "vendor_id": f"vendor-{index}",
                "source_type": "dpa",
                "candidate_source_id": f"vendor-{index}-dpa",
                "candidate_url": f"https://vendor-{index}.example/dpa",
                "requires_human_review": True,
                "writes_canonical_sources": False,
                "non_advisory": True,
            }
            for index in range(1_501)
        ]
    }

    paths, manifest = build_vendor_promotion_plans(
        plan,
        source_plan_path="raw.json",
        run_token="scale-run",
        output_root=tmp_path,
    )

    assert len(paths) == 1_501
    assert manifest["summary"]["vendor_plan_count"] == 1_501
    assert manifest["summary"]["vendor_count_cap"] is None
