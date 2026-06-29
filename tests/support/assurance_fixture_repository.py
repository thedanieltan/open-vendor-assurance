from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from tests.support.assurance_fixture_runner import NormalizedSchemaError, normalize_schema_errors
from tools.openva import assurance_validation

FIXTURE_DIR_TO_KIND = {
    "vendors": assurance_validation.VENDOR.kind,
    "sources": assurance_validation.SOURCE.kind,
    "source_observations": assurance_validation.SOURCE_OBSERVATION.kind,
    "assurances": assurance_validation.ASSURANCE.kind,
    "assurance_observations": assurance_validation.ASSURANCE_OBSERVATION.kind,
    "assurance_changes": assurance_validation.ASSURANCE_CHANGE_EVENT.kind,
}
SUPPORTED_EXTENSIONS = {".json", ".yaml", ".yml"}


@dataclass(frozen=True, slots=True)
class RawFixtureDocument:
    path: Path
    kind: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FixtureStructuralError:
    path: Path
    kind: str
    errors: tuple[NormalizedSchemaError, ...]


@dataclass(frozen=True, slots=True)
class FixtureRepositoryResult:
    raw_documents: tuple[RawFixtureDocument, ...]
    structural_errors: tuple[FixtureStructuralError, ...]
    build_result: assurance_validation.RepositoryBuildResult | None
    semantic_diagnostics: tuple[assurance_validation.ValidationDiagnostic, ...]


def _load_document(path: Path) -> Any:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_raw_fixture_documents(root: Path) -> tuple[RawFixtureDocument, ...]:
    root_files = sorted(path.name for path in root.iterdir() if path.is_file())
    if root_files:
        raise ValueError(f"fixture root contains files: {root_files}")

    documents: list[RawFixtureDocument] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        if directory.name not in FIXTURE_DIR_TO_KIND:
            raise ValueError(f"unknown fixture directory {directory.name}")
        nested = sorted(path.name for path in directory.iterdir() if path.is_dir())
        if nested:
            raise ValueError(f"nested fixture directories are not supported in {directory.name}: {nested}")
        kind = FIXTURE_DIR_TO_KIND[directory.name]
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if path.suffix not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"unsupported fixture extension for {path.name}")
            payload = _load_document(path)
            if not isinstance(payload, Mapping):
                raise TypeError(f"{path} must contain a mapping/object")
            documents.append(RawFixtureDocument(path=path, kind=kind, payload=payload))
    return tuple(documents)


def load_assurance_fixture_repository(
    root: Path,
    *,
    validator_factory: Callable[[str], Draft202012Validator],
) -> FixtureRepositoryResult:
    raw_documents = load_raw_fixture_documents(root)
    structural_errors: list[FixtureStructuralError] = []
    validators = {kind: validator_factory(kind) for kind in FIXTURE_DIR_TO_KIND.values()}

    for document in raw_documents:
        errors = normalize_schema_errors(
            validators[document.kind].iter_errors(document.payload),
            include_aggregate_errors=False,
        )
        if errors:
            structural_errors.append(
                FixtureStructuralError(
                    path=document.path,
                    kind=document.kind,
                    errors=tuple(errors),
                )
            )

    if structural_errors:
        return FixtureRepositoryResult(
            raw_documents=raw_documents,
            structural_errors=tuple(structural_errors),
            build_result=None,
            semantic_diagnostics=(),
        )

    records_by_kind = {kind: [] for kind in FIXTURE_DIR_TO_KIND.values()}
    for document in raw_documents:
        spec = assurance_validation.RECORD_KIND_SPEC_BY_KIND[document.kind]
        records_by_kind[document.kind].append(
            assurance_validation.RepositoryRecord.from_raw(
                spec=spec,
                payload=document.payload,
                source_path=document.path,
            )
        )

    build_result = assurance_validation.build_repository_snapshot(records_by_kind)
    if build_result.snapshot is None:
        return FixtureRepositoryResult(
            raw_documents=raw_documents,
            structural_errors=(),
            build_result=build_result,
            semantic_diagnostics=(),
        )

    return FixtureRepositoryResult(
        raw_documents=raw_documents,
        structural_errors=(),
        build_result=build_result,
        semantic_diagnostics=assurance_validation.validate_assurance_repository(build_result.snapshot),
    )
