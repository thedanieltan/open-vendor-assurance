import json
from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def test_each_written_plan_has_one_vendor_and_noncanonical_posture(tmp_path: Path) -> None:
    action = {
        "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
        "vendor_id": "acme",
        "source_type": "dpa",
        "candidate_source_id": "acme-dpa",
        "candidate_url": "https://acme.example/dpa",
        "requires_human_review": True,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }
    paths, _ = build_vendor_promotion_plans(
        {"actions": [action]},
        source_plan_path="raw.json",
        run_token="run-1",
        output_root=tmp_path,
    )
    plan = json.loads(paths[0].read_text(encoding="utf-8"))
    assert plan["vendor_id"] == "acme"
    assert plan["summary"]["vendor_count"] == 1
    assert plan["posture"]["writes_canonical_vendors"] is False
    assert plan["posture"]["writes_canonical_sources"] is False
