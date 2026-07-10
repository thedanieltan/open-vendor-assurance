from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans


def test_activation_api_exposes_no_catalog_ceiling() -> None:
    _, manifest = build_vendor_promotion_plans(
        {"actions": []},
        source_plan_path="raw.json",
        run_token="empty-run",
        output_root=__import__("pathlib").Path("/tmp/openva-empty-run"),
    )
    assert manifest["summary"]["vendor_count_cap"] is None
    assert manifest["summary"]["action_count_cap"] is None
