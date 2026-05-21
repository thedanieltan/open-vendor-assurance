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
DOWNLOAD_NAMES = [CSV_ZIP_NAME, SAMPLE_INVENTORY_NAME, TEMPLATE_INVENTORY_NAME]

INVENTORY_COLUMNS = ["vendor_name", "business_entity_name", "registered_address", "domain"]
SAMPLE_ROWS = [
    {"vendor_name": "Stripe", "business_entity_name": "", "registered_address": "", "domain": ""},
    {"vendor_name": "", "business_entity_name": "Slack Technologies, LLC", "registered_address": "", "domain": ""},
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


def build_release_downloads(pack_path: str | Path = ROOT, output_dir: str | Path = ROOT / "release-downloads") -> list[Path]:
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


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-release-downloads")
    parser.add_argument("command", choices=["build", "manifest"])
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

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
