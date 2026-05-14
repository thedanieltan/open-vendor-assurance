from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, GENERATED_AT, ROOT, SCHEMA_VERSION

MANIFEST_PATH = ROOT / "release-artifacts.json"
MANIFEST_SCHEMA_VERSION = "0.1.0"

ARTIFACT_PATTERNS = [
    "openva-pack.json",
    "indexes/*.json",
    "schemas/openva/*.json",
    "fixtures/packs/**/*.json",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def artifact_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in ARTIFACT_PATTERNS:
        for path in ROOT.glob(pattern):
            if path.is_file() and path != MANIFEST_PATH:
                paths.add(path)
    return sorted(paths, key=lambda item: item.relative_to(ROOT).as_posix())


def build_manifest() -> dict[str, Any]:
    artifacts = []
    for path in artifact_paths():
        rel_path = path.relative_to(ROOT).as_posix()
        artifacts.append(
            {
                "path": rel_path,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": GENERATED_AT,
        "profileId": EXPORT_PROFILE_ID,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "record_schema_version": SCHEMA_VERSION,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def write_manifest() -> None:
    manifest = build_manifest()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def load_committed_manifest() -> dict[str, Any] | None:
    if not MANIFEST_PATH.exists():
        return None
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("release-artifacts.json must be a JSON object")
    return data


def check_manifest_current() -> list[str]:
    expected = build_manifest()
    current = load_committed_manifest()
    if current == expected:
        return []
    if current is None:
        return ["release-artifacts.json is missing; run python -m tools.openva.release_artifacts build"]
    return ["release-artifacts.json is not current; run python -m tools.openva.release_artifacts build"]


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-release-artifacts")
    parser.add_argument("command", choices=["build", "check"])
    args = parser.parse_args()

    if args.command == "build":
        write_manifest()
        print("Built release-artifacts.json.")
        return 0

    if args.command == "check":
        failures = check_manifest_current()
        if failures:
            for failure in failures:
                print(failure)
            return 1
        print("Release artifact manifest is current.")
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
