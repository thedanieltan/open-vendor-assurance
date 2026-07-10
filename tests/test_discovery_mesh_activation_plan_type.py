from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans


def test_activation_manifest_type_is_stable(tmp_path: Path) -> None:
    _, manifest = build_vendor_promotion_plans(
        {"actions": []}, source_plan_path="raw.json", run_token="run-1", output_root=tmp_path
    )
    assert manifest["report_type"] == "discovery_mesh_intake_manifest"
