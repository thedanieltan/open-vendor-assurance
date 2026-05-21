import csv
import sys
import zipfile
from pathlib import Path

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
        {"vendor_name": "Stripe", "business_entity_name": "", "domain": ""},
        {"vendor_name": "", "business_entity_name": "Slack Technologies, LLC", "domain": ""},
    ]
    assert read_csv(template_path) == []

    match_inventory(".", sample_path, matched_path)
    matched_rows = read_csv(matched_path)
    assert matched_rows[0]["matched_vendor_id"] == "stripe"
    assert matched_rows[1]["matched_vendor_id"] == "slack"
    assert "category" not in matched_rows[0]


def test_release_download_manifest_has_checksums(tmp_path):
    release_downloads.build_release_downloads(".", tmp_path)
    manifest = release_downloads.build_download_manifest(tmp_path)

    assert manifest["artifact_count"] == 3
    assert [artifact["path"] for artifact in manifest["artifacts"]] == release_downloads.DOWNLOAD_NAMES
    for artifact in manifest["artifacts"]:
        assert artifact["sha256"].startswith("sha256:")
        assert artifact["size_bytes"] > 0
