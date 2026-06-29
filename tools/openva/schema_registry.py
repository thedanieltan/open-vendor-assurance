from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[2]

ASSURANCE_SCHEMA_PATHS: tuple[Path, ...] = (
    ROOT / "schemas/openva/vocabularies/assurance-v1.schema.json",
    ROOT / "schemas/openva/vocabularies/assurance-projection-v1.schema.json",
    ROOT / "schemas/openva/assurance-record.schema.json",
    ROOT / "schemas/openva/assurance-observation.schema.json",
    ROOT / "schemas/openva/assurance-change-event.schema.json",
    ROOT / "schemas/openva/assurance-projection-request.schema.json",
    ROOT / "schemas/openva/assurance-projection.schema.json",
    ROOT / "schemas/openva/assurance-projection-policy.schema.json",
    ROOT / "schemas/openva/assurance-projection-latest-index.schema.json",
)


def load_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise TypeError(f"{path} must contain a JSON object schema")
    return schema


def build_openva_schema_registry(
    schema_paths: Iterable[Path] = ASSURANCE_SCHEMA_PATHS,
) -> Registry[Any]:
    resources: list[tuple[str, Any]] = []
    for schema_path in schema_paths:
        schema = load_schema(schema_path)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError(f"{schema_path} must define a non-empty $id")
        Draft202012Validator.check_schema(schema)
        resources.append((schema_id, DRAFT202012.create_resource(schema)))
    return Registry().with_resources(resources)


def build_openva_validator(
    schema_path: Path,
    *,
    registry: Registry[Any] | None = None,
) -> Draft202012Validator:
    schema = load_schema(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=registry or build_openva_schema_registry(),
        format_checker=FormatChecker(),
    )
