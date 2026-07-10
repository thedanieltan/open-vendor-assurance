from tools.openva.discovery_mesh_activation import PLAN_ROOT


def test_activation_reviewed_plan_root_is_explicit() -> None:
    assert PLAN_ROOT.as_posix() == "maintenance/reviewed/discovery-mesh"
