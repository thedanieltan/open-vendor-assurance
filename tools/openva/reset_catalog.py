from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.openva.indexes import build_indexes

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT / "catalog-reset-report.json"

RESET_PATHS = (
    ROOT / "data" / "vendors",
    ROOT / "catalog-batches",
)

PRESERVE_PATHS = (
    ROOT / "catalog-batches" / "backlog" / "README.md",
)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def existing_reset_targets() -> list[Path]:
    return [path for path in RESET_PATHS if path.exists()]


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.is_file())


def build_reset_report(*, dry_run: bool) -> dict[str, Any]:
    targets = existing_reset_targets()
    files: list[str] = []
    preserved: list[str] = []
    preserve_set = {path.resolve() for path in PRESERVE_PATHS if path.exists()}

    for target in targets:
        for file_path in collect_files(target):
            if file_path.resolve() in preserve_set:
                preserved.append(relative(file_path))
                continue
            files.append(relative(file_path))

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "controlled_catalog_layer_reset",
        "dry_run": dry_run,
        "posture": {
            "public_sources_only": True,
            "non_advisory": True,
            "network_fetch_performed": False,
            "raw_documents_mirrored": False,
            "gated_materials_excluded": True,
            "preserves_repository_substrate": True,
        },
        "reset_targets": [relative(path) for path in targets],
        "preserved_files": preserved,
        "files_to_remove": files,
        "summary": {
            "reset_target_count": len(targets),
            "files_to_remove_count": len(files),
            "preserved_file_count": len(preserved),
        },
    }


def remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file():
        path.unlink()
        return
    if path.name == "catalog-batches":
        for child in path.iterdir():
            if child == ROOT / "catalog-batches" / "backlog":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        return
    shutil.rmtree(path)


def run_reset(*, dry_run: bool, output: Path) -> dict[str, Any]:
    report = build_reset_report(dry_run=dry_run)
    if not dry_run:
        for target in RESET_PATHS:
            remove_path(target)
        build_indexes()
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-reset-catalog")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    report = run_reset(dry_run=args.dry_run, output=args.output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
