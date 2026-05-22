import csv
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_vendor_inventory_matcher").resolve()))

from openva_vendor_inventory_matcher import match_inventory  # noqa: E402
from tools.openva import release_downloads  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_release_download_builder_creates_expected_assets(tmp_path):
    paths = release_downloads.build_release_downloads(".", tmp_path)

    assert {path.name for path in paths} == {
        "openva-csv.zip",
        "openva-sample-inventory.csv",
        "openva-inventory-template.csv",
    }
    for path in paths:
        assert path.is_file()
        assert path.stat().st_size > 0


def test_release_csv_zip_contains_curated_csv_exports(tmp_path):
    release_downloads.build_release_downloads(".", tmp_path)

    with zipfile.ZipFile(tmp_path / "openva-csv.zip") as archive:
        assert sorted(archive.namelist()) == [
            "artifacts.csv",
            "candidate_sources.csv",
            "observations.csv",
            "source_coverage.csv",
            "sources.csv",
            "unavailable_sources.csv",
            "vendors.csv",
        ]


def test_release_inventory_files_are_valid_csv_and_matcher_compatible(tmp_path):
    release_downloads.build_release_downloads(".", tmp_path)
    sample_path = tmp_path / "openva-sample-inventory.csv"
    template_path = tmp_path / "openva-inventory-template.csv"
    matched_path = tmp_path / "matched.csv"

    assert read_csv(sample_path) == [
        {
            "vendor_name": "Stripe",
            "business_entity_name": "",
            "domain": "stripe.com",
            "jurisdiction": "SG",
            "registration_number": "",
            "registered_address": "",
        },
        {
            "vendor_name": "",
            "business_entity_name": "Slack Technologies, LLC",
            "domain": "",
            "jurisdiction": "",
            "registration_number": "",
            "registered_address": "",
        },
    ]
    assert read_csv(template_path) == []

    match_inventory(".", sample_path, matched_path)
    matched_rows = read_csv(matched_path)
    assert matched_rows[0]["matched_vendor_id"] == "stripe"
    assert matched_rows[1]["matched_vendor_id"] == "slack"
    assert "registered_address" in matched_rows[0]
    assert "category" not in matched_rows[0]


def test_release_download_manifest_has_checksums(tmp_path):
    release_downloads.build_release_downloads(".", tmp_path)
    manifest = release_downloads.build_download_manifest(tmp_path)

    assert manifest["artifact_count"] == 3
    assert [artifact["path"] for artifact in manifest["artifacts"]] == release_downloads.DOWNLOAD_NAMES
    for artifact in manifest["artifacts"]:
        assert artifact["sha256"].startswith("sha256:")
        assert artifact["size_bytes"] > 0


def test_release_download_check_accepts_generated_assets_and_manifest(tmp_path):
    release_downloads.build_release_downloads(".", tmp_path)
    manifest = release_downloads.build_download_manifest(tmp_path)
    (tmp_path / "openva-release-downloads-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = release_downloads.check_release_downloads(tmp_path)

    assert report["ok"] is True
    assert report["checked_assets"] == release_downloads.DOWNLOAD_NAMES
    assert report["manifest_checked"] is True


def test_release_download_check_rejects_template_with_example_rows(tmp_path):
    release_downloads.build_release_downloads(".", tmp_path)
    (tmp_path / "openva-inventory-template.csv").write_text(
        "vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address\n"
        "Stripe,,stripe.com,SG,,\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="row content mismatch"):
        release_downloads.check_release_downloads(tmp_path)


def test_release_download_check_rejects_misaligned_inventory_rows(tmp_path):
    release_downloads.build_release_downloads(".", tmp_path)
    (tmp_path / "openva-sample-inventory.csv").write_text(
        "vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address\n"
        "Stripe,,stripe.com,SG\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="row 2 has 4 columns; expected 6"):
        release_downloads.check_release_downloads(tmp_path)
