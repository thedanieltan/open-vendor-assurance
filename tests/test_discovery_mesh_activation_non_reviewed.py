from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans


def test_non_reviewed_actions_do_not_enter_mesh_intake(tmp_path: Path) -> None:
    paths, manifest = build_vendor_promotion_plans(
        {"actions": [{"action": "manual_review_required", "vendor_id": "alpha"}]},
        source_plan_path="raw.json",
        run_token="run-1",
        output_root=tmp_path,
    )
    assert paths == []
    assert manifest["summary"]["reviewed_action_count"] == 0
