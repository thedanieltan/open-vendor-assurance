from tools.openva.validate import validate_all


def test_validate_all_passes():
    assert validate_all() == 0
