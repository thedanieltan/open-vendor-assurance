from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError

COMBINATOR_KEYWORDS = frozenset(
    {
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "contains",
        "dependentSchemas",
    }
)


@dataclass(frozen=True, slots=True)
class NormalizedSchemaError:
    instance_path: str
    schema_path: str
    keyword: str
    message: str
    additional_property: str | None = None
    missing_property: str | None = None
    combinator_ancestry: tuple[str, ...] = ()


def _json_pointer(parts: Iterable[Any]) -> str:
    encoded = []
    for part in parts:
        text = str(part)
        encoded.append(text.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(encoded) if encoded else ""


def _missing_property(error: ValidationError) -> str | None:
    if error.validator != "required":
        return None
    match = re.search(r"'([^']+)' is a required property", error.message)
    return match.group(1) if match else None


def _additional_properties(error: ValidationError) -> tuple[str | None, ...]:
    if error.validator != "additionalProperties":
        return (None,)
    match = re.search(r"\((.*?) (?:was|were) unexpected\)", error.message)
    if not match:
        return (None,)
    names = tuple(re.findall(r"'([^']+)'", match.group(1)))
    return names or (None,)


def _schema_pointer(error: ValidationError) -> str:
    pointer = _json_pointer(error.absolute_schema_path)
    title = error.schema.get("title") if isinstance(error.schema, dict) else None
    if isinstance(title, str) and title and title not in pointer:
        pointer = f"{pointer}#{title}"
    return pointer


def _normalize_single_error(
    error: ValidationError,
    *,
    combinator_ancestry: tuple[str, ...],
) -> tuple[NormalizedSchemaError, ...]:
    errors: list[NormalizedSchemaError] = []
    for property_name in _additional_properties(error):
        errors.append(
            NormalizedSchemaError(
                instance_path=_json_pointer(error.absolute_path),
                schema_path=_schema_pointer(error),
                keyword=str(error.validator),
                message=error.message,
                additional_property=property_name,
                missing_property=_missing_property(error),
                combinator_ancestry=combinator_ancestry,
            )
        )
    return tuple(errors)


def normalize_schema_errors(
    errors: Iterable[ValidationError],
    *,
    include_aggregate_errors: bool = False,
) -> list[NormalizedSchemaError]:
    normalized: set[NormalizedSchemaError] = set()

    def visit(error: ValidationError, ancestry: tuple[str, ...]) -> None:
        keyword = str(error.validator)
        next_ancestry = ancestry + (keyword,) if keyword in COMBINATOR_KEYWORDS else ancestry
        if include_aggregate_errors or not error.context:
            normalized.update(_normalize_single_error(error, combinator_ancestry=ancestry))
        for child in error.context:
            visit(child, next_ancestry)

    for error in errors:
        visit(error, ())

    return sorted(
        normalized,
        key=lambda err: (
            err.instance_path,
            err.keyword,
            err.additional_property or "",
            err.missing_property or "",
            err.schema_path,
            err.message,
            err.combinator_ancestry,
        ),
    )


def matches_expected(
    actual: NormalizedSchemaError,
    expected: dict[str, Any],
) -> bool:
    if "instance_path" in expected and actual.instance_path != expected["instance_path"]:
        return False
    if "keyword" in expected and actual.keyword != expected["keyword"]:
        return False
    if "keywords_any_of" in expected and actual.keyword not in expected["keywords_any_of"]:
        return False
    if "additional_property" in expected and actual.additional_property != expected["additional_property"]:
        return False
    if "missing_property" in expected and actual.missing_property != expected["missing_property"]:
        return False
    if "schema_path_contains" in expected and expected["schema_path_contains"] not in actual.schema_path:
        return False
    if (
        "combinator_ancestry_contains" in expected
        and expected["combinator_ancestry_contains"] not in actual.combinator_ancestry
    ):
        return False
    return True


def assert_expected_schema_errors(
    actual: list[NormalizedSchemaError],
    expected: list[dict[str, Any]],
) -> None:
    missing = []
    for expected_error in expected:
        if not any(matches_expected(actual_error, expected_error) for actual_error in actual):
            missing.append(expected_error)
    if missing:
        formatted_actual = "\n".join(repr(error) for error in actual)
        formatted_missing = "\n".join(repr(error) for error in missing)
        raise AssertionError(
            "Expected schema errors were not observed.\n"
            f"Missing:\n{formatted_missing}\n\nActual:\n{formatted_actual}"
        )
