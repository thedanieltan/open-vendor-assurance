from pathlib import Path

import pytest

from tools.openva.validate import load_prohibited_terms


@pytest.mark.parametrize(
    "term",
    [
        "best-in-class",
        "industry-leading",
        "trusted by",
        "fully compliant",
        "audit-ready",
    ],
)
def test_vendor_promotional_terms_are_prohibited(term):
    assert term in load_prohibited_terms()


def test_prohibited_claims_config_exists():
    assert Path("config/prohibited-claims.yaml").exists()
