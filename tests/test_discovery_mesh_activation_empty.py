from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans


def test_empty_reviewed_plan_is_non_mutating(tmp_path: Path) -> None:
    paths, manifest = build_vendor_promotion_plans(
        {"actions": []},
        source_plan_path="raw.json",
        run_token="empty",
        output_root=tmp_path,
    )
    assert paths == []
    assert manifest["summary"]["vendor_plan_count"] == 0
    assert manifest["summary"]["reviewed_action_count"] == 0
