from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SOURCE_SCHEMA_FIELDS = {
    "schema_version",
    "source_id",
    "vendor_id",
    "entity_id",
    "source_type",
    "title_native",
    "title_en",
    "source_url",
    "source_language",
    "effective_or_published_at",
    "source_authority_class",
    "access_class",
    "rights_class",
    "catalog_tier",
    "review_state",
    "advisory_boundary",
    "summary_native",
    "summary_en",
    "provenance",
    "not_advice",
}


@dataclass(frozen=True)
class MaterializeResult:
    written: tuple[str, ...]
    skipped_existing: tuple[str, ...]
    conflicts: tuple[str, ...]
    invalid_items: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "written": list(self.written),
            "skipped_existing": list(self.skipped_existing),
            "conflicts": list(self.conflicts),
            "invalid_items": list(self.invalid_items),
            "summary": {
                "written": len(self.written),
                "skipped_existing": len(self.skipped_existing),
                "conflicts": len(self.conflicts),
                "invalid_items": len(self.invalid_items),
            },
            "posture": {
                "writes_canonical_source_files": True,
                "opens_pull_requests": False,
                "auto_merge": False,
                "non_advisory": True,
            },
        }


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_path(root: Path, source: dict[str, Any]) -> Path:
    vendor_id = str(source["vendor_id"])
    source_id = str(source["source_id"])
    return root / "data" / "vendors" / vendor_id / "sources" / f"{source_id}.yaml"


def sanitize_source(source: dict[str, Any]) -> dict[str, Any]:
    clean = {key: source.get(key) for key in SOURCE_SCHEMA_FIELDS if key in source}
    required = [
        "schema_version",
        "source_id",
        "vendor_id",
        "source_type",
        "title_native",
        "source_url",
        "source_language",
        "source_authority_class",
        "access_class",
        "rights_class",
        "provenance",
        "not_advice",
    ]
    missing = [field for field in required if clean.get(field) in (None, "")]
    if missing:
        raise ValueError(f"missing required source fields: {','.join(missing)}")
    if clean.get("catalog_tier") != "machine_validated":
        raise ValueError("source catalog_tier must be machine_validated")
    if clean.get("review_state") != "auto_validated":
        raise ValueError("source review_state must be auto_validated")
    if clean.get("advisory_boundary") != "non_advisory":
        raise ValueError("source advisory_boundary must be non_advisory")
    if clean.get("not_advice") is not True:
        raise ValueError("source not_advice must be true")
    return clean


def materialize_queue(
    queue: dict[str, Any],
    *,
    root: Path,
    apply: bool = False,
    overwrite: bool = False,
) -> MaterializeResult:
    written: list[str] = []
    skipped_existing: list[str] = []
    conflicts: list[str] = []
    invalid_items: list[str] = []

    for index, item in enumerate(queue.get("machine_validated_promotions", []) or []):
        if not isinstance(item, dict) or not isinstance(item.get("source"), dict):
            invalid_items.append(f"item[{index}]:missing_source")
            continue
        try:
            source = sanitize_source(item["source"])
        except ValueError as exc:
            invalid_items.append(f"item[{index}]:{exc}")
            continue

        path = source_path(root, source)
        display_path = path.relative_to(root).as_posix()
        if path.exists():
            existing = load_yaml(path)
            if existing.get("source_url") == source.get("source_url") and existing.get("source_type") == source.get("source_type"):
                skipped_existing.append(display_path)
                continue
            if not overwrite:
                conflicts.append(display_path)
                continue

        if apply:
            write_yaml(path, source)
        written.append(display_path)

    return MaterializeResult(
        written=tuple(written),
        skipped_existing=tuple(skipped_existing),
        conflicts=tuple(conflicts),
        invalid_items=tuple(invalid_items),
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-contribution-promotion-materializer")
    parser.add_argument("materialize", choices={"materialize"})
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=Path(".openva-promotion-queue/materialize-report.json"))
    parser.add_argument("--apply", action="store_true", help="Write source YAML files. Without this, report only.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing conflicting source files.")
    args = parser.parse_args()

    queue = load_json(args.queue)
    result = materialize_queue(queue, root=args.root, apply=args.apply, overwrite=args.overwrite)
    report = result.as_dict()
    write_json(args.out, report)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 1 if result.conflicts or result.invalid_items else 0


if __name__ == "__main__":
    raise SystemExit(main())
