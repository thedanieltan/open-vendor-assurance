from pathlib import Path

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans


def test_empty_activation_manifest_is_non_advisory(tmp_path: Path) -> None:
    _, manifest = build_vendor_promotion_plans(
        {"actions": []}, source_plan_path="raw.json", run_token="run-1", output_root=tmp_path
    )
    assert manifest["posture"]["canonical_mutation_performed"] is False
    assert manifest["posture"]["non_advisory"] is True
