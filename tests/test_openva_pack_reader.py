import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))

from openva_pack_reader import OpenVAPack, PackError  # noqa: E402


def test_pack_reader_loads_current_pack_with_adapter_annotations():
    pack = OpenVAPack.load(".")

    vendor = pack.vendors()[0]
    assert vendor["record_class"] == "vendor"
    assert vendor["canonical"] is False
    assert vendor["catalog_tier"] == "human_reviewed"
    assert vendor["review_state"] == "human_reviewed"
    assert vendor["advisory_boundary"] == "non_advisory"
    assert "catalog_status" in vendor

    source = pack.canonical_sources()[0]
    assert source["record_class"] == "canonical"
    assert source["canonical"] is True
    assert source["catalog_tier"] == "human_reviewed"
    assert source["review_state"] == "human_reviewed"
    assert source["advisory_boundary"] == "non_advisory"


def test_pack_reader_exposes_candidate_and_unavailable_indexes():
    pack = OpenVAPack.load(".")

    assert pack.candidate_sources() == []
    unavailable = pack.unavailable_sources()
    assert unavailable
    assert unavailable[0]["record_class"] == "unavailable"
    assert unavailable[0]["canonical"] is False
    assert unavailable[0]["catalog_tier"] == "human_reviewed"
    assert unavailable[0]["review_state"] == "human_reviewed"


def test_pack_reader_normalizes_vendor_manifests_and_coverage_rows():
    pack = OpenVAPack.load(".")

    stripe = pack.vendor("stripe")
    assert stripe["vendor"]["record_class"] == "vendor"
    assert stripe["canonical_sources"][0]["record_class"] == "canonical"
    assert stripe["canonical_sources"][0]["canonical"] is True

    coverage = pack.source_coverage()
    assert coverage["vendor_coverage"]
    assert coverage["vendor_coverage"][0]["record_class"] == "coverage"
    assert coverage["vendor_coverage"][0]["canonical"] is False
    assert coverage["vendor_coverage"][0]["catalog_tier"] == "human_reviewed"
    assert coverage["vendor_coverage"][0]["review_state"] == "human_reviewed"


def test_pack_reader_rejects_invalid_fixture():
    with pytest.raises(PackError, match="non_advisory"):
        OpenVAPack.load("fixtures/packs/invalid-missing-guarantee")
