from tools.openva.indexes import build_indexes
from tools.openva.validate import validate_all


def test_build_indexes_passes():
    assert build_indexes() == 0


def test_validate_all_passes():
    assert validate_all() == 0
