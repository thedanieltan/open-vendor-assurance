import codecs
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_jsonl_export").resolve()))

import openva_jsonl_export.exporter as exporter  # noqa: E402
from openva_jsonl_export import export_jsonl  # noqa: E402

EXPECTED_FILES = {
    "openva-vendors.jsonl",
    "openva-sources.jsonl",
    "openva-artifacts.jsonl",
    "openva-observations.jsonl",
    "openva-candidates.jsonl",
    "openva-unavailable-sources.jsonl",
    "openva-source-coverage.jsonl",
}


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            row = json.loads(line)
            assert isinstance(row, dict)
            rows.append(row)
    return rows


def test_export_jsonl_creates_expected_files(tmp_path):
    written = export_jsonl(".", tmp_path)

    assert {path.name for path in written} == EXPECTED_FILES
    assert {path.name for path in tmp_path.iterdir()} == EXPECTED_FILES


def test_export_preserves_adapter_annotations_and_record_classes(tmp_path):
    export_jsonl(".", tmp_path)

    cases = {
        "openva-vendors.jsonl": ("vendor", False),
        "openva-sources.jsonl": ("canonical", True),
        "openva-artifacts.jsonl": ("artifact", False),
        "openva-candidates.jsonl": ("candidate", False),
        "openva-unavailable-sources.jsonl": ("unavailable", False),
        "openva-source-coverage.jsonl": ("coverage", False),
    }
    for filename, (record_class, canonical) in cases.items():
        rows = read_jsonl(tmp_path / filename)
        for row in rows:
            assert row["record_class"] == record_class
            assert row["canonical"] is canonical
            assert row["advisory_boundary"] == "non_advisory"

    assert read_jsonl(tmp_path / "openva-sources.jsonl")
    assert read_jsonl(tmp_path / "openva-unavailable-sources.jsonl")
    assert read_jsonl(tmp_path / "openva-source-coverage.jsonl")


def test_unavailable_sources_renames_status_field(tmp_path):
    export_jsonl(".", tmp_path)

    rows = read_jsonl(tmp_path / "openva-unavailable-sources.jsonl")
    assert rows
    for row in rows:
        assert "unavailability_status" in row
        assert "status" not in row
        assert row["unavailability_status"]


def test_deprecated_aliases_are_not_exported(tmp_path):
    export_jsonl(".", tmp_path)

    for path in tmp_path.iterdir():
        for row in read_jsonl(path):
            assert "materiality" not in row
            if path.name in {"openva-vendors.jsonl", "openva-unavailable-sources.jsonl"}:
                assert "status" not in row


def test_list_and_object_values_remain_native_json(tmp_path):
    export_jsonl(".", tmp_path)

    vendor = read_jsonl(tmp_path / "openva-vendors.jsonl")[0]
    assert isinstance(vendor["official_domains"], list)
    assert isinstance(vendor["vendor_categories"], list)

    artifact = read_jsonl(tmp_path / "openva-artifacts.jsonl")[0]
    assert isinstance(artifact["hashes"], dict)
    assert isinstance(artifact["storage"], dict)

    coverage = read_jsonl(tmp_path / "openva-source-coverage.jsonl")[0]
    assert isinstance(coverage["canonical_source_types"], list)


def test_none_values_export_as_json_null(monkeypatch, tmp_path):
    class NullValuePack:
        def vendor_search(self):
            return []

        def vendors(self):
            return [
                {
                    "record_class": "vendor",
                    "canonical": False,
                    "advisory_boundary": "non_advisory",
                    "vendor_id": "null-value-vendor",
                    "display_name": None,
                }
            ]

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

    monkeypatch.setattr(exporter.OpenVAPack, "load", lambda _: NullValuePack())

    export_jsonl("unused-pack-path", tmp_path)

    raw_line = (tmp_path / "openva-vendors.jsonl").read_text(encoding="utf-8")
    assert '"display_name":null' in raw_line
    assert read_jsonl(tmp_path / "openva-vendors.jsonl")[0]["display_name"] is None


def test_jsonl_files_use_utf8_without_bom_and_lf_only(tmp_path):
    export_jsonl(".", tmp_path)

    for path in tmp_path.iterdir():
        content = path.read_bytes()
        assert not content.startswith(codecs.BOM_UTF8)
        assert b"\r\n" not in content
        if content:
            assert content.endswith(b"\n")
            assert all(line.startswith(b"{") and line.endswith(b"}") for line in content.splitlines())


def test_each_line_parses_as_one_json_object(tmp_path):
    export_jsonl(".", tmp_path)

    for path in tmp_path.iterdir():
        with path.open("r", encoding="utf-8", newline="") as handle:
            content = handle.read()
        assert not content.startswith("[")
        for line in content.splitlines():
            assert not line.endswith(",")
            parsed = json.loads(line)
            assert isinstance(parsed, dict)


def test_empty_exports_write_zero_byte_files(monkeypatch, tmp_path):
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

    export_jsonl("unused-pack-path", tmp_path)

    assert {path.name for path in tmp_path.iterdir()} == EXPECTED_FILES
    for filename in [
        "openva-observations.jsonl",
        "openva-candidates.jsonl",
        "openva-source-coverage.jsonl",
    ]:
        path = tmp_path / filename
        assert path.is_file()
        assert path.read_bytes() == b""


def test_console_script_entrypoint_is_declared():
    pyproject = tomllib.loads(
        Path("adapters/python/openva_jsonl_export/pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["scripts"]["openva-jsonl-export"] == "openva_jsonl_export.cli:main"


def test_module_cli_writes_to_output_directory(tmp_path):
    env_pythonpath = os.pathsep.join(
        [
            str(Path("adapters/python/openva_pack_reader").resolve()),
            str(Path("adapters/python/openva_jsonl_export").resolve()),
        ]
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = env_pythonpath

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "openva_jsonl_export",
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
    assert (tmp_path / "openva-vendors.jsonl").is_file()
    assert {path.name for path in tmp_path.iterdir()} == EXPECTED_FILES
