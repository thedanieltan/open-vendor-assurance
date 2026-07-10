import json
from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def test_actions_are_sorted_within_vendor_plan(tmp_path: Path) -> None:
    actions = [
        {
            "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
            "vendor_id": "alpha",
            "source_type": source_type,
            "candidate_source_id": candidate_id,
        }
        for source_type, candidate_id in (("privacy_notice", "z"), ("dpa", "b"), ("dpa", "a"))
    ]
    paths, _ = build_vendor_promotion_plans(
        {"actions": actions}, source_plan_path="raw.json", run_token="run-1", output_root=tmp_path
    )
    plan = json.loads(paths[0].read_text(encoding="utf-8"))
    assert [(a["source_type"], a["candidate_source_id"]) for a in plan["actions"]] == [
        ("dpa", "a"),
        ("dpa", "b"),
        ("privacy_notice", "z"),
    ]
