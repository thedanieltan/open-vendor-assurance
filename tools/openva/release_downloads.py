from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, GENERATED_AT, ROOT, SCHEMA_VERSION

ADAPTER_PATHS = [
    ROOT / "adapters/python/openva_pack_reader",
    ROOT / "adapters/python/openva_csv_export",
]
for adapter_path in ADAPTER_PATHS:
    path_text = str(adapter_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from openva_csv_export import export_csvs  # noqa: E402

CSV_ZIP_NAME = "openva-csv.zip"
SAMPLE_INVENTORY_NAME = "openva-sample-inventory.csv"
TEMPLATE_INVENTORY_NAME = "openva-inventory-template.csv"
DOWNLOAD_MANIFEST_NAME = "openva-release-downloads-manifest.json"
DOWNLOAD_NAMES = [CSV_ZIP_NAME, SAMPLE_INVENTORY_NAME, TEMPLATE_INVENTORY_NAME]
EXPECTED_CSV_ZIP_MEMBERS = [
    "artifacts.csv",
    "candidate_sources.csv",
    "observations.csv",
    "source_coverage.csv",
    "sources.csv",
    "unavailable_sources.csv",
    "vendors.csv",
]

INVENTORY_COLUMNS = [
    "vendor_name",
    "business_entity_name",
    "domain",
    "jurisdiction",
    "registration_number",
    "registered_address",
]
SAMPLE_ROWS = [
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_inventory_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows_strict(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"{path}: CSV is empty")
    header = rows[0]
    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            raise ValueError(
                f"{path}: row {line_number} has {len(row)} columns; expected {len(header)}"
            )
    return header, rows[1:]


def build_release_downloads(
    pack_path: str | Path = ROOT, output_dir: str | Path = ROOT / "release-downloads"
) -> list[Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        csv_dir = Path(temp_dir) / "csv"
        csv_paths = export_csvs(pack_path, csv_dir)
        with zipfile.ZipFile(out_dir / CSV_ZIP_NAME, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for csv_path in sorted(csv_paths, key=lambda path: path.name):
                archive.write(csv_path, arcname=csv_path.name)

    write_inventory_csv(out_dir / SAMPLE_INVENTORY_NAME, SAMPLE_ROWS)
    write_inventory_csv(out_dir / TEMPLATE_INVENTORY_NAME, [])
    return [out_dir / name for name in DOWNLOAD_NAMES]


def build_download_manifest(output_dir: str | Path = ROOT / "release-downloads") -> dict[str, Any]:
    out_dir = Path(output_dir)
    artifacts = []
    for name in DOWNLOAD_NAMES:
        path = out_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"{path}: release download asset is missing")
        artifacts.append(
            {
                "path": name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": "0.1.0",
        "generated_at": GENERATED_AT,
        "profileId": EXPORT_PROFILE_ID,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "record_schema_version": SCHEMA_VERSION,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def check_inventory_csv(path: Path, *, expected_rows: list[dict[str, str]] | None) -> None:
    header, rows = read_csv_rows_strict(path)
    if header != INVENTORY_COLUMNS:
        raise ValueError(f"{path}: header mismatch: {header!r}")
    if expected_rows is None:
        return
    expected = [[row[column] for column in INVENTORY_COLUMNS] for row in expected_rows]
    if rows != expected:
        raise ValueError(f"{path}: row content mismatch")


def check_csv_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"{path}: not a valid zip file")
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
        if names != EXPECTED_CSV_ZIP_MEMBERS:
            raise ValueError(f"{path}: unexpected zip members: {names!r}")
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts or name.endswith("/"):
                raise ValueError(f"{path}: unsafe or directory zip member: {name}")
            with archive.open(name) as handle:
                text = handle.read().decode("utf-8")
            rows = list(csv.reader(text.splitlines()))
            if not rows:
                raise ValueError(f"{path}:{name}: CSV is empty")
            width = len(rows[0])
            for line_number, row in enumerate(rows[1:], start=2):
                if len(row) != width:
                    raise ValueError(
                        f"{path}:{name}: row {line_number} has {len(row)} columns; expected {width}"
                    )


def check_download_manifest(output_dir: Path) -> None:
    manifest_path = output_dir / DOWNLOAD_MANIFEST_NAME
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_count") != len(DOWNLOAD_NAMES):
        raise ValueError(f"{manifest_path}: artifact_count mismatch")
    artifacts = manifest.get("artifacts") or []
    paths = [artifact.get("path") for artifact in artifacts]
    if paths != DOWNLOAD_NAMES:
        raise ValueError(f"{manifest_path}: artifact path order mismatch: {paths!r}")
    for artifact in artifacts:
        name = artifact["path"]
        path = output_dir / name
        if artifact.get("sha256") != sha256_file(path):
            raise ValueError(f"{manifest_path}: sha256 mismatch for {name}")
        if artifact.get("size_bytes") != path.stat().st_size:
            raise ValueError(f"{manifest_path}: size mismatch for {name}")


def check_release_downloads(output_dir: str | Path = ROOT / "release-downloads") -> dict[str, Any]:
    out_dir = Path(output_dir)
    for name in DOWNLOAD_NAMES:
        path = out_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"{path}: release download asset is missing")
        if path.stat().st_size <= 0:
            raise ValueError(f"{path}: release download asset is empty")

    check_csv_zip(out_dir / CSV_ZIP_NAME)
    check_inventory_csv(out_dir / SAMPLE_INVENTORY_NAME, expected_rows=SAMPLE_ROWS)
    check_inventory_csv(out_dir / TEMPLATE_INVENTORY_NAME, expected_rows=[])
    check_download_manifest(out_dir)

    return {
        "schema_version": "0.1.0",
        "checked_assets": DOWNLOAD_NAMES,
        "manifest_checked": (out_dir / DOWNLOAD_MANIFEST_NAME).exists(),
        "ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-release-downloads")
    parser.add_argument("command", choices=["build", "manifest", "check"])
    parser.add_argument("--pack", default=str(ROOT), help="OpenVA pack directory or openva-pack.json")
    parser.add_argument("--out", default=str(ROOT / "release-downloads"), help="Directory for release download assets")
    args = parser.parse_args()

    if args.command == "build":
        paths = build_release_downloads(args.pack, args.out)
        for path in paths:
            print(path)
        return 0

    if args.command == "manifest":
        print(json.dumps(build_download_manifest(args.out), indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "check":
        print(json.dumps(check_release_downloads(args.out), indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())