from tools.openva.validate import validate_cross_references, validate_quality_gates


def test_current_catalog_accepts_absent_candidate_and_unavailable_ledgers():
    assert validate_cross_references() == []
    assert validate_quality_gates() == []
