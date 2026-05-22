import csv
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_csv_export").resolve()))

import openva_csv_export.exporter as exporter  # noqa: E402
from openva_csv_export import export_csvs  # noqa: E402
from openva_csv_export.exporter import CANDIDATE_SOURCE_COLUMNS, OBSERVATION_COLUMNS, SOURCE_COVERAGE_COLUMNS  # noqa: E402

EXPECTED_FILES = {
    "vendors.csv",
    "sources.csv",
    "artifacts.csv",
    "observations.csv",
    "candidate_sources.csv",
    "unavailable_sources.csv",
    "source_coverage.csv",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_csvs_creates_expected_files(tmp_path):
    written = export_csvs(".", tmp_path)

    assert {path.name for path in written} == EXPECTED_FILES
    assert {path.name for path in tmp_path.iterdir()} == EXPECTED_FILES


def test_export_preserves_adapter_annotations_and_record_classes(tmp_path):
    export_csvs(".", tmp_path)

    source = read_csv(tmp_path / "sources.csv")[0]
    assert source["record_class"] == "canonical"
    assert source["canonical"] == "true"
    assert source["catalog_tier"] == "human_reviewed"
    assert source["review_state"] == "human_reviewed"
    assert source["advisory_boundary"] == "non_advisory"

    unavailable = read_csv(tmp_path / "unavailable_sources.csv")[0]
    assert unavailable["record_class"] == "unavailable"
    assert unavailable["canonical"] == "false"
    assert unavailable["catalog_tier"] == "human_reviewed"
    assert unavailable["review_state"] == "human_reviewed"
    assert unavailable["advisory_boundary"] == "non_advisory"

    coverage = read_csv(tmp_path / "source_coverage.csv")[0]
    assert coverage["record_class"] == "coverage"
    assert coverage["canonical"] == "false"
    assert coverage["catalog_tier"] == "human_reviewed"
    assert coverage["review_state"] == "human_reviewed"
    assert coverage["advisory_boundary"] == "non_advisory"


def test_unavailable_sources_renames_status_column(tmp_path):
    export_csvs(".", tmp_path)

    with (tmp_path / "unavailable_sources.csv").open("r", encoding="utf-8", newline="") as handle:
        fieldnames = csv.DictReader(handle).fieldnames

    assert fieldnames is not None
    assert "unavailability_status" in fieldnames
    assert "status" not in fieldnames

    row = read_csv(tmp_path / "unavailable_sources.csv")[0]
    assert row["unavailability_status"]


def test_list_and_object_cells_are_json_strings(tmp_path):
    export_csvs(".", tmp_path)

    vendor = read_csv(tmp_path / "vendors.csv")[0]
    assert isinstance(json.loads(vendor["official_domains"]), list)
    assert isinstance(json.loads(vendor["vendor_categories"]), list)

    artifact = read_csv(tmp_path / "artifacts.csv")[0]
    assert isinstance(json.loads(artifact["hashes"]), dict)
    assert isinstance(json.loads(artifact["storage"]), dict)

    coverage = read_csv(tmp_path / "source_coverage.csv")[0]
    assert isinstance(json.loads(coverage["canonical_source_types"]), list)


def test_empty_exports_write_headers(monkeypatch, tmp_path):
    class EmptyPack:
        def vendor_search(self):
            return []

        def vendors(self):
            return []

        def canonical_sources(self):
            return []

        def artifacts(self):
            return []

        def observations(self):
            return []

        def candidate_sources(self):
            return []

        def unavailable_sources(self):
            return []

        def source_coverage(self):
            return {"vendor_coverage": []}

    monkeypatch.setattr(exporter.OpenVAPack, "load", lambda _: EmptyPack())

    export_csvs("unused-pack-path", tmp_path)

    cases = {
        "observations.csv": OBSERVATION_COLUMNS,
        "candidate_sources.csv": CANDIDATE_SOURCE_COLUMNS,
        "source_coverage.csv": SOURCE_COVERAGE_COLUMNS,
    }
    for filename, columns in cases.items():
        path = tmp_path / filename
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == columns
            assert list(reader) == []


def test_console_script_entrypoint_is_declared():
    pyproject = tomllib.loads(
        Path("adapters/python/openva_csv_export/pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["scripts"]["openva-csv-export"] == "openva_csv_export.cli:main"


def test_module_cli_writes_to_output_directory(tmp_path):
    env_pythonpath = os.pathsep.join(
        [
            str(Path("adapters/python/openva_pack_reader").resolve()),
            str(Path("adapters/python/openva_csv_export").resolve()),
        ]
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = env_pythonpath
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "openva_csv_export",
            "--pack",
            ".",
            "--out",
            str(tmp_path),
        ],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "vendors.csv").is_file()
    assert {path.name for path in tmp_path.iterdir()} == EXPECTED_FILES
