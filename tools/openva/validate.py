from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva.indexes import build_indexes, check_generated_current, records_for

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_MAP = {
    "vendor": ROOT / "schemas/openva/vendor-public-profile.schema.json",
    "source": ROOT / "schemas/openva/source-reference.schema.json",
    "artifact": ROOT / "schemas/openva/artifact-reference.schema.json",
    "observation": ROOT / "schemas/openva/observation.schema.json",
    "change": ROOT / "schemas/openva/change-event.schema.json",
    "pack": ROOT / "schemas/openva/openva-pack.schema.json",
}

FIXTURE_GLOBS = {
    "vendor": ["examples/vendors/*/vendor.yaml", "data/vendors/*/vendor.yaml"],
    "source": ["examples/vendors/*/sources/*.yaml", "data/vendors/*/sources/*.yaml"],
    "artifact": ["examples/vendors/*/artifacts/*.yaml", "data/vendors/*/artifacts/*.yaml"],
    "observation": ["examples/vendors/*/observations/*.yaml", "data/vendors/*/observations/*.yaml"],
    "change": ["examples/vendors/*/changes/*.yaml", "data/vendors/*/changes/*.yaml"],
}

RECORD_TEXT_FILE_GLOBS = ["examples/**/*.yaml", "data/**/*.yaml"]
ALLOWED_PROHIBITED_CONTEXTS = ("not a real vendor record", "fixture for schema validation only")


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

    if kind == "pack":
        pack_path = ROOT / "openva-pack.json"
        paths = [pack_path] if pack_path.exists() else []
    else:
        paths = iter_paths(FIXTURE_GLOBS[kind])

    for path in paths:
        data = load_json(path) if path.suffix == ".json" else load_yaml(path)
        errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
        for error in errors:
            location = ".".join(str(part) for part in error.path) or "<root>"
            failures.append(f"{path}: {location}: {error.message}")

    return failures


def validate_cross_references() -> list[str]:
    failures: list[str] = []
    vendors = {record["vendor_id"] for record in records_for("vendor")}
    sources = {record["source_id"] for record in records_for("source")}
    artifacts = {record["artifact_id"] for record in records_for("artifact")}

    for source in records_for("source"):
        if source["vendor_id"] not in vendors:
            failures.append(f"{source['_openva_path']}: unknown vendor_id {source['vendor_id']}")

    for artifact in records_for("artifact"):
        if artifact["vendor_id"] not in vendors:
            failures.append(f"{artifact['_openva_path']}: unknown vendor_id {artifact['vendor_id']}")
        if artifact["source_id"] not in sources:
            failures.append(f"{artifact['_openva_path']}: unknown source_id {artifact['source_id']}")

    for observation in records_for("observation"):
        if observation["vendor_id"] not in vendors:
            failures.append(f"{observation['_openva_path']}: unknown vendor_id {observation['vendor_id']}")
        if observation["source_id"] not in sources:
            failures.append(f"{observation['_openva_path']}: unknown source_id {observation['source_id']}")
        artifact_id = observation.get("artifact_id")
        if artifact_id and artifact_id not in artifacts:
            failures.append(f"{observation['_openva_path']}: unknown artifact_id {artifact_id}")

    for change in records_for("change"):
        if change["vendor_id"] not in vendors:
            failures.append(f"{change['_openva_path']}: unknown vendor_id {change['vendor_id']}")
        if change["source_id"] not in sources:
            failures.append(f"{change['_openva_path']}: unknown source_id {change['source_id']}")
        artifact_id = change.get("artifact_id")
        if artifact_id and artifact_id not in artifacts:
            failures.append(f"{change['_openva_path']}: unknown artifact_id {artifact_id}")

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
    failures.extend(validate_cross_references())
    failures.extend(check_prohibited_language())
    failures.extend(check_generated_current())

    if failures:
        for failure in failures:
            print(failure)
        print(f"Validation failed: {len(failures)} issue(s).")
        return 1

    print("OpenVA validation passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva")
    parser.add_argument("command", choices=["validate", "build-indexes"])
    args = parser.parse_args()

    if args.command == "validate":
        return validate_all()
    if args.command == "build-indexes":
        return build_indexes()

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
