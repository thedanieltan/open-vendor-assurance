from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from tools.openva.paths import normalize_repo_path, relative_repo_path

ROOT = Path(__file__).resolve().parents[2]

ALLOWED_PREFIXES = (
    "catalog-batches/",
    "data/vendors/",
    "indexes/",
    "dist/",
)

ALLOWED_FILES = {
    "openva-pack.json",
    "docs/coverage-map.md",
    "docs/vendor-expansion-backlog.md",
    "maintenance/applied/applied-plans.json",
    "maintenance/source-observations/latest-observations.json",
}

PROHIBITED_PREFIXES = (
    "schemas/",
    "tools/",
    "tests/",
    ".github/workflows/",
    "policy/",
)

PROHIBITED_FILES = {
    ".github/CODEOWNERS",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
}

GENERATED_OUTPUT_HINT = (
    "run python -m tools.openva.validate build-indexes, then commit openva-pack.json indexes/ dist/"
)
OBSERVATION_BASELINE_HINT = (
    "verify the new source(s), run python -m tools.openva.observation_ledger build, "
    "install latest-observations.json, then commit maintenance/source-observations/latest-observations.json"
)


def normalize_path(path: str) -> str:
    return normalize_repo_path(path)


def is_allowed_catalog_path(path: str) -> bool:
    normalized = normalize_path(path)
    return (
        normalized in ALLOWED_FILES
        or any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES)
        or (
            normalized.startswith("maintenance/generated/strict-growth-")
            and normalized.endswith(".json")
        )
        or (
            normalized.startswith("maintenance/machine-decisions/")
            and normalized.endswith(".ndjson")
        )
    )


def is_explicitly_prohibited_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in PROHIBITED_FILES or any(
        normalized.startswith(prefix) for prefix in PROHIBITED_PREFIXES
    )


def is_catalog_batch_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized.startswith("catalog-batches/") and normalized.endswith((".yaml", ".yml"))


def is_catalog_data_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized.startswith("data/vendors/") and normalized.endswith((".yaml", ".yml"))


def is_source_record_path(path: str) -> bool:
    normalized = normalize_path(path)
    return (
        normalized.startswith("data/vendors/")
        and "/sources/" in normalized
        and normalized.endswith((".yaml", ".yml"))
    )


def is_generated_output_path(path: str) -> bool:
    normalized = normalize_path(path)
    return (
        normalized == "openva-pack.json"
        or normalized.startswith("indexes/")
        or normalized.startswith("dist/vendors/")
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{relative_repo_path(path, ROOT)}: expected YAML mapping")
    return data


def load_latest_observed_source_ids(root: Path = ROOT) -> set[str]:
    path = root / "maintenance" / "source-observations" / "latest-observations.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(entry.get("source_id"))
        for entry in data.get("sources", [])
        if isinstance(entry, dict) and entry.get("source_id")
    }


def validate_catalog_paths(paths: list[str]) -> list[str]:
    failures: list[str] = []
    for raw_path in paths:
        path = normalize_path(raw_path)
        if not path or path == ".":
            continue
        if is_explicitly_prohibited_path(path):
            failures.append(
                f"{path}: catalog PRs must not modify substrate, policy, workflow, or governance files"
            )
            continue
        if not is_allowed_catalog_path(path):
            failures.append(f"{path}: catalog PR path is outside the allowed catalog-agent file set")
    return failures


def validate_catalog_generated_outputs(paths: list[str]) -> list[str]:
    normalized = [normalize_path(path) for path in paths]
    if any(is_catalog_data_path(path) for path in normalized) and not any(
        is_generated_output_path(path) for path in normalized
    ):
        return [f"catalog data changed but generated outputs are absent; {GENERATED_OUTPUT_HINT}"]
    return []


def validate_changed_source_observations(paths: list[str], *, root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    observed_source_ids = load_latest_observed_source_ids(root)
    for raw_path in paths:
        path = normalize_path(raw_path)
        if not is_source_record_path(path):
            continue
        record_path = root / path
        if not record_path.exists():
            continue
        try:
            source = load_yaml(record_path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        source_id = str(source.get("source_id") or "")
        if source_id and source_id not in observed_source_ids:
            failures.append(
                f"{path}: source_id {source_id} has no latest-observations baseline; "
                f"{OBSERVATION_BASELINE_HINT}"
            )
    return failures


def validate_catalog_batch_duplicates(paths: list[str], *, root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    changed_paths = {normalize_path(path) for path in paths}

    for raw_path in paths:
        path = normalize_path(raw_path)
        if not is_catalog_batch_path(path):
            continue

        manifest_path = root / path
        if not manifest_path.exists():
            continue

        try:
            manifest = load_yaml(manifest_path)
        except ValueError as exc:
            failures.append(str(exc))
            continue

        vendors = manifest.get("vendors", [])
        if not isinstance(vendors, list):
            continue

        vendor_ids = [vendor.get("vendor_id") for vendor in vendors if isinstance(vendor, dict)]
        duplicate_ids = sorted(
            vendor_id
            for vendor_id, count in Counter(vendor_ids).items()
            if vendor_id and count > 1
        )
        for vendor_id in duplicate_ids:
            failures.append(f"{path}: {vendor_id}: duplicate vendor_id in batch manifest")

        for vendor_id in sorted(
            {vendor_id for vendor_id in vendor_ids if isinstance(vendor_id, str)}
        ):
            vendor_record_path = f"data/vendors/{vendor_id}/vendor.yaml"
            if vendor_record_path in changed_paths:
                continue
            vendor_path = root / vendor_record_path
            if vendor_path.exists():
                failures.append(
                    f"{path}: {vendor_id}: vendor_id already exists at "
                    f"{relative_repo_path(vendor_path, root)}"
                )

    return failures


def validate_catalog_pr(paths: list[str], *, root: Path = ROOT) -> list[str]:
    failures = validate_catalog_paths(paths)
    failures.extend(validate_catalog_generated_outputs(paths))
    failures.extend(validate_changed_source_observations(paths, root=root))
    failures.extend(validate_catalog_batch_duplicates(paths, root=root))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-guard")
    parser.add_argument("paths", nargs="*", help="Changed repository paths to validate")
    args = parser.parse_args()

    failures = validate_catalog_pr(args.paths)
    if failures:
        for failure in failures:
            print(failure)
        print(f"Catalog PR guard failed: {len(failures)} issue(s).")
        return 1

    print("Catalog PR guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
