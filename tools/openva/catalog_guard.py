from __future__ import annotations

import argparse
from pathlib import PurePosixPath

ALLOWED_PREFIXES = (
    "catalog-batches/",
    "data/vendors/",
    "indexes/",
)

ALLOWED_FILES = {
    "openva-pack.json",
    "docs/coverage-map.md",
    "docs/vendor-expansion-backlog.md",
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


def normalize_path(path: str) -> str:
    return str(PurePosixPath(path.strip()))


def is_allowed_catalog_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in ALLOWED_FILES or any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def is_explicitly_prohibited_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in PROHIBITED_FILES or any(normalized.startswith(prefix) for prefix in PROHIBITED_PREFIXES)


def validate_catalog_paths(paths: list[str]) -> list[str]:
    failures: list[str] = []
    for raw_path in paths:
        path = normalize_path(raw_path)
        if not path or path == ".":
            continue
        if is_explicitly_prohibited_path(path):
            failures.append(f"{path}: catalog PRs must not modify substrate, policy, workflow, or governance files")
            continue
        if not is_allowed_catalog_path(path):
            failures.append(f"{path}: catalog PR path is outside the allowed catalog-agent file set")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-guard")
    parser.add_argument("paths", nargs="*", help="Changed repository paths to validate")
    args = parser.parse_args()

    failures = validate_catalog_paths(args.paths)
    if failures:
        for failure in failures:
            print(failure)
        print(f"Catalog PR guard failed: {len(failures)} issue(s).")
        return 1

    print("Catalog PR guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
