from tools.openva.discovery_mesh_activation import CANDIDATE_PATH_RE, PLAN_PATH_RE


def test_intake_path_regexes_are_anchored() -> None:
    assert CANDIDATE_PATH_RE.fullmatch("data/vendors/acme/candidate_sources/acme-dpa.yaml")
    assert not CANDIDATE_PATH_RE.fullmatch("x/data/vendors/acme/candidate_sources/acme-dpa.yaml")
    assert PLAN_PATH_RE.fullmatch("maintenance/reviewed/discovery-mesh/run-1/acme.json")
    assert not PLAN_PATH_RE.fullmatch("maintenance/reviewed/discovery-mesh/run-1/nested/acme.json")
