from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_MAP = {
    "vendor": ROOT / "schemas/openva/vendor-public-profile.schema.json",
    "source": ROOT / "schemas/openva/source-reference.schema.json",
    "artifact": ROOT / "schemas/openva/artifact-reference.schema.json",
    "observation": ROOT / "schemas/openva/observation.schema.json",
    "change": ROOT / "schemas/openva/change-event.schema.json",
}

FIXTURE_GLOBS = {
    "vendor": ["examples/vendors/*/vendor.yaml", "data/vendors/*/vendor.yaml"],
    "source": ["examples/vendors/*/sources/*.yaml", "data/vendors/*/sources/*.yaml"],
    "artifact": ["examples/vendors/*/artifacts/*.yaml", "data/vendors/*/artifacts/*.yaml"],
    "observation": ["examples/vendors/*/observations/*.yaml", "data/vendors/*/observations/*.yaml"],
    "change": ["examples/vendors/*/changes/*.yaml", "data/vendors/*/changes/*.yaml"],
}

RECORD_TEXT_FILE_GLOBS = [
    "examples/**/*.yaml",
    "data/**/*.yaml",
]

ALLOWED_PROHIBITED_CONTEXTS = (
    "not a real vendor record",
    "fixture for schema validation only",
)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def validate_schema(kind: str) -> list[str]:
    schema = load_json(SCHEMA_MAP[kind])
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    failures: list[str] = []

    for path in iter_paths(FIXTURE_GLOBS[kind]):
        data = load_yaml(path)
        errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
        for error in errors:
            location = ".".join(str(part) for part in error.path) or "<root>"
            failures.append(f"{path}: {location}: {error.message}")

    return failures


def load_prohibited_terms() -> list[str]:
    config = load_yaml(ROOT / "config/prohibited-claims.yaml")
    return [str(term).lower() for term in config.get("prohibited_terms", [])]


def check_prohibited_language() -> list[str]:
    terms = load_prohibited_terms()
    failures: list[str] = []

    for path in iter_paths(RECORD_TEXT_FILE_GLOBS):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        if any(context in lower for context in ALLOWED_PROHIBITED_CONTEXTS):
            continue
        for term in terms:
            pattern = r"(?<![a-z0-9-])" + re.escape(term) + r"(?![a-z0-9-])"
            if re.search(pattern, lower):
                failures.append(f"{path}: prohibited advisory wording detected: {term}")

    return failures


def validate_all() -> int:
    failures: list[str] = []
    for kind in SCHEMA_MAP:
        failures.extend(validate_schema(kind))
    failures.extend(check_prohibited_language())

    if failures:
        for failure in failures:
            print(failure)
        print(f"Validation failed: {len(failures)} issue(s).")
        return 1

    print("OpenVA validation passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-validate")
    parser.add_argument("command", choices=["validate"])
    args = parser.parse_args()

    if args.command == "validate":
        return validate_all()

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
