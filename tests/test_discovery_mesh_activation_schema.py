from pathlib import Path

from tools.openva.discovery_mesh_activation import SCHEMA_VERSION, build_vendor_promotion_plans


def test_activation_schema_version_is_stable(tmp_path: Path) -> None:
    _, manifest = build_vendor_promotion_plans(
        {"actions": []}, source_plan_path="raw.json", run_token="run-1", output_root=tmp_path
    )
    assert SCHEMA_VERSION == "0.1.0"
    assert manifest["schema_version"] == SCHEMA_VERSION
