import json
import os
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path("adapters/python/openva_pack_reader").resolve()))
sys.path.insert(0, str(Path("adapters/python/openva_sqlite_export").resolve()))

import openva_sqlite_export.exporter as exporter  # noqa: E402
from openva_sqlite_export import export_sqlite  # noqa: E402

EXPECTED_TABLES = {
    "artifacts",
    "candidate_sources",
    "canonical_sources",
    "changes",
    "observations",
    "source_coverage",
    "unavailable_sources",
    "vendors",
}


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
    ).fetchall()
    return {row["name"] for row in rows}


def table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    return [row["name"] for row in connection.execute(f"pragma table_info({table_name})")]


def current_pack_counts() -> dict[str, int]:
    return {
        "vendors": json.loads(Path("indexes/vendors.json").read_text(encoding="utf-8"))["count"],
        "canonical_sources": json.loads(
            Path("indexes/sources.json").read_text(encoding="utf-8")
        )["count"],
        "artifacts": json.loads(Path("indexes/artifacts.json").read_text(encoding="utf-8"))[
            "count"
        ],
        "unavailable_sources": json.loads(
            Path("indexes/unavailable-sources.json").read_text(encoding="utf-8")
        )["count"],
        "source_coverage": len(
            json.loads(Path("indexes/source-coverage.json").read_text(encoding="utf-8"))[
                "vendor_coverage"
            ]
        ),
    }


def test_export_sqlite_creates_expected_tables_and_counts(tmp_path):
    db_path = export_sqlite(".", tmp_path / "openva.sqlite")
    counts = current_pack_counts()

    assert db_path == tmp_path / "openva.sqlite"
    with connect(db_path) as connection:
        assert table_names(connection) == EXPECTED_TABLES
        for table_name, expected_count in counts.items():
            assert connection.execute(f"select count(*) from {table_name}").fetchone()[0] == expected_count


def test_export_sqlite_replaces_existing_database(tmp_path):
    db_path = tmp_path / "openva.sqlite"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("create table stale_table (id integer primary key)")
        connection.execute("insert into stale_table (id) values (1)")
        connection.commit()
    finally:
        connection.close()

    export_sqlite(".", db_path)
    counts = current_pack_counts()

    with connect(db_path) as connection:
        names = table_names(connection)
        assert names == EXPECTED_TABLES
        assert "stale_table" not in names
        for table_name in ("vendors", "canonical_sources", "source_coverage"):
            assert connection.execute(f"select count(*) from {table_name}").fetchone()[0] == counts[table_name]


def test_export_preserves_adapter_annotations_and_record_classes(tmp_path):
    db_path = export_sqlite(".", tmp_path / "openva.sqlite")

    with connect(db_path) as connection:
        source = connection.execute(
            "select record_class, canonical, advisory_boundary from canonical_sources limit 1"
        ).fetchone()
        assert dict(source) == {
            "record_class": "canonical",
            "canonical": 1,
            "advisory_boundary": "non_advisory",
        }

        unavailable = connection.execute(
            "select record_class, canonical, advisory_boundary from unavailable_sources limit 1"
        ).fetchone()
        assert dict(unavailable) == {
            "record_class": "unavailable",
            "canonical": 0,
            "advisory_boundary": "non_advisory",
        }

        coverage = connection.execute(
            "select record_class, canonical, advisory_boundary from source_coverage limit 1"
        ).fetchone()
        assert dict(coverage) == {
            "record_class": "coverage",
            "canonical": 0,
            "advisory_boundary": "non_advisory",
        }


def test_unavailable_sources_renames_status_column(tmp_path):
    db_path = export_sqlite(".", tmp_path / "openva.sqlite")

    with connect(db_path) as connection:
        columns = table_columns(connection, "unavailable_sources")
        assert "unavailability_status" in columns
        assert "status" not in columns
        value = connection.execute(
            "select unavailability_status from unavailable_sources limit 1"
        ).fetchone()[0]
        assert value


def test_deprecated_aliases_are_not_primary_columns(tmp_path):
    db_path = export_sqlite(".", tmp_path / "openva.sqlite")

    with connect(db_path) as connection:
        assert "status" not in table_columns(connection, "vendors")
        assert "materiality" not in table_columns(connection, "changes")
        assert "catalog_status" in table_columns(connection, "vendors")
        assert "catalog_change_significance" in table_columns(connection, "changes")


def test_list_and_object_cells_are_json_strings(tmp_path):
    db_path = export_sqlite(".", tmp_path / "openva.sqlite")

    with connect(db_path) as connection:
        vendor = connection.execute(
            "select official_domains, vendor_categories from vendors limit 1"
        ).fetchone()
        assert isinstance(json.loads(vendor["official_domains"]), list)
        assert isinstance(json.loads(vendor["vendor_categories"]), list)

        artifact = connection.execute("select hashes, storage from artifacts limit 1").fetchone()
        assert isinstance(json.loads(artifact["hashes"]), dict)
        assert isinstance(json.loads(artifact["storage"]), dict)

        coverage = connection.execute(
            "select canonical_source_types from source_coverage limit 1"
        ).fetchone()
        assert isinstance(json.loads(coverage["canonical_source_types"]), list)


def test_empty_exports_create_empty_tables(monkeypatch, tmp_path):
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

        def changes(self):
            return []

        def source_coverage(self):
            return {"vendor_coverage": []}

    monkeypatch.setattr(exporter.OpenVAPack, "load", lambda _: EmptyPack())

    db_path = export_sqlite("unused-pack-path", tmp_path / "empty.sqlite")

    with connect(db_path) as connection:
        assert table_names(connection) == EXPECTED_TABLES
        for table_name in EXPECTED_TABLES:
            assert connection.execute(f"select count(*) from {table_name}").fetchone()[0] == 0


def test_module_cli_writes_database(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path("adapters/python/openva_pack_reader").resolve()),
            str(Path("adapters/python/openva_sqlite_export").resolve()),
        ]
    )
    db_path = tmp_path / "openva.sqlite"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "openva_sqlite_export",
            "--pack",
            ".",
            "--out",
            str(db_path),
        ],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    with connect(db_path) as connection:
        assert table_names(connection) == EXPECTED_TABLES


def test_console_script_entrypoint_is_declared():
    pyproject = tomllib.loads(
        Path("adapters/python/openva_sqlite_export/pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["scripts"]["openva-sqlite-export"] == "openva_sqlite_export.cli:main"
