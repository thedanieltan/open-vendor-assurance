from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans


def test_output_root_is_created_only_for_non_empty_plan(tmp_path: Path) -> None:
    output_root = tmp_path / "plans"
    paths, _ = build_vendor_promotion_plans(
        {"actions": []}, source_plan_path="raw.json", run_token="run-1", output_root=output_root
    )
    assert paths == []
    assert not output_root.exists()
