from tools.openva.discovery_mesh_activation import allowed_intake_path


def test_only_candidate_and_reviewed_mesh_plan_paths_are_allowed() -> None:
    assert allowed_intake_path("data/vendors/acme/candidate_sources/acme-dpa.yaml")
    assert allowed_intake_path("maintenance/reviewed/discovery-mesh/run-1/acme.json")
    assert not allowed_intake_path("data/vendors/acme/sources/acme-dpa.yaml")
    assert not allowed_intake_path("data/vendors/acme/vendor.yaml")
    assert not allowed_intake_path("maintenance/machine-decisions/acme.ndjson")
    assert not allowed_intake_path("indexes/sources.json")
