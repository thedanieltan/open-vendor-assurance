from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

JsonFrozen = Mapping[str, Any] | tuple[Any, ...] | str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class RecordKindSpec:
    kind: str
    schema_kind: str
    id_field: str


VENDOR = RecordKindSpec("vendor", "vendor", "vendor_id")
SOURCE = RecordKindSpec("source", "source", "source_id")
SOURCE_OBSERVATION = RecordKindSpec("source_observation", "observation", "observation_id")
ASSURANCE = RecordKindSpec("assurance", "assurance", "assurance_id")
ASSURANCE_OBSERVATION = RecordKindSpec(
    "assurance_observation",
    "assurance_observation",
    "assurance_observation_id",
)
ASSURANCE_CHANGE_EVENT = RecordKindSpec(
    "assurance_change_event",
    "assurance_change",
    "change_event_id",
)

RECORD_KIND_SPECS: tuple[RecordKindSpec, ...] = (
    VENDOR,
    SOURCE,
    SOURCE_OBSERVATION,
    ASSURANCE,
    ASSURANCE_OBSERVATION,
    ASSURANCE_CHANGE_EVENT,
)
RECORD_KIND_SPEC_BY_KIND = {spec.kind: spec for spec in RECORD_KIND_SPECS}
RECORD_KIND_SPEC_BY_SCHEMA_KIND = {spec.schema_kind: spec for spec in RECORD_KIND_SPECS}

REPOSITORY_DUPLICATE_ID = "REPOSITORY_DUPLICATE_ID"
ASSURANCE_VENDOR_UNKNOWN = "ASSURANCE_VENDOR_UNKNOWN"
ASSURANCE_SOURCE_UNKNOWN = "ASSURANCE_SOURCE_UNKNOWN"
ASSURANCE_PRIMARY_SOURCE_NOT_IN_EVIDENCE_SET = "ASSURANCE_PRIMARY_SOURCE_NOT_IN_EVIDENCE_SET"


@dataclass(frozen=True, slots=True)
class SemanticDiagnostic:
    code: str
    record_kind: str
    record_id: str
    instance_path: str
    message: str
    related_ids: tuple[str, ...] = ()
    record_path: str | None = None

    @property
    def source_path(self) -> str | None:
        return self.record_path


ValidationDiagnostic = SemanticDiagnostic


def deep_freeze_json(value: Any) -> JsonFrozen:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): deep_freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, list | tuple):
        return tuple(deep_freeze_json(nested) for nested in value)
    return value


@dataclass(frozen=True, slots=True)
class RepositoryRecord:
    kind: str
    record_id: str
    payload: Mapping[str, Any]
    source_path: str | None = None

    @property
    def data(self) -> Mapping[str, Any]:
        return self.payload

    @property
    def path(self) -> str | None:
        return self.source_path

    @property
    def vendor_id(self) -> str:
        value = self.data.get("vendor_id")
        if not isinstance(value, str):
            raise KeyError("vendor_id")
        return value

    @classmethod
    def from_raw(
        cls,
        *,
        spec: RecordKindSpec,
        payload: Mapping[str, Any],
        source_path: str | Path | None = None,
    ) -> RepositoryRecord:
        record_id = payload.get(spec.id_field)
        if not isinstance(record_id, str):
            raise ValueError(f"{spec.kind} record missing string id field {spec.id_field}")
        frozen = deep_freeze_json(payload)
        if not isinstance(frozen, Mapping):
            raise TypeError("repository record payload must freeze to a mapping")
        return cls(
            kind=spec.kind,
            record_id=record_id,
            payload=frozen,
            source_path=str(source_path) if source_path is not None else None,
        )


class RepositoryView(Protocol):
    vendors: Mapping[str, RepositoryRecord]
    sources: Mapping[str, RepositoryRecord]
    source_observations: Mapping[str, RepositoryRecord]
    assurances: Mapping[str, RepositoryRecord]
    assurance_observations: Mapping[str, RepositoryRecord]
    assurance_change_events: Mapping[str, RepositoryRecord]

    def records_for_kind(self, kind: str) -> Mapping[str, RepositoryRecord]: ...
    def get_vendor(self, vendor_id: str) -> RepositoryRecord | None: ...
    def get_source(self, source_id: str) -> RepositoryRecord | None: ...


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    vendors: Mapping[str, RepositoryRecord]
    sources: Mapping[str, RepositoryRecord]
    source_observations: Mapping[str, RepositoryRecord]
    assurances: Mapping[str, RepositoryRecord]
    assurance_observations: Mapping[str, RepositoryRecord]
    assurance_change_events: Mapping[str, RepositoryRecord]

    def records_for_kind(self, kind: str) -> Mapping[str, RepositoryRecord]:
        if kind == VENDOR.kind:
            return self.vendors
        if kind == SOURCE.kind:
            return self.sources
        if kind == SOURCE_OBSERVATION.kind:
            return self.source_observations
        if kind == ASSURANCE.kind:
            return self.assurances
        if kind == ASSURANCE_OBSERVATION.kind:
            return self.assurance_observations
        if kind == ASSURANCE_CHANGE_EVENT.kind:
            return self.assurance_change_events
        raise KeyError(kind)

    def get_vendor(self, vendor_id: str) -> RepositoryRecord | None:
        return self.vendors.get(vendor_id)

    def get_source(self, source_id: str) -> RepositoryRecord | None:
        return self.sources.get(source_id)


@dataclass(frozen=True, slots=True)
class RepositoryBuildResult:
    snapshot: RepositorySnapshot | None
    diagnostics: tuple[ValidationDiagnostic, ...] = ()


def _duplicate_diagnostic(
    *,
    spec: RecordKindSpec,
    record_id: str,
    source_paths: Iterable[str | None],
) -> ValidationDiagnostic:
    related = tuple(sorted(path for path in source_paths if path))
    return ValidationDiagnostic(
        code=REPOSITORY_DUPLICATE_ID,
        record_kind=spec.kind,
        record_id=record_id,
        instance_path=f"/{spec.id_field}",
        related_ids=related,
        message=f"duplicate {spec.kind} id {record_id}",
        record_path=related[0] if related else None,
    )


def _materialize_collection(
    *,
    spec: RecordKindSpec,
    records: Iterable[RepositoryRecord],
) -> tuple[Mapping[str, RepositoryRecord], tuple[ValidationDiagnostic, ...]]:
    by_id: dict[str, RepositoryRecord] = {}
    duplicate_paths: dict[str, list[str | None]] = {}
    for record in records:
        if record.kind != spec.kind:
            raise TypeError(f"{spec.kind} collection contains {record.kind} record {record.record_id}")
        if record.record_id in by_id:
            duplicate_paths.setdefault(record.record_id, [by_id[record.record_id].source_path]).append(
                record.source_path
            )
            continue
        by_id[record.record_id] = record

    diagnostics = tuple(
        _duplicate_diagnostic(spec=spec, record_id=record_id, source_paths=paths)
        for record_id, paths in sorted(duplicate_paths.items())
    )
    return MappingProxyType(dict(sorted(by_id.items()))), diagnostics


def build_repository_snapshot(
    records_by_kind: Mapping[str, Iterable[RepositoryRecord]],
) -> RepositoryBuildResult:
    unknown = sorted(set(records_by_kind) - set(RECORD_KIND_SPEC_BY_KIND))
    if unknown:
        raise KeyError(f"unknown repository record kind(s): {', '.join(unknown)}")

    materialized: dict[str, Mapping[str, RepositoryRecord]] = {}
    diagnostics: list[ValidationDiagnostic] = []
    for spec in RECORD_KIND_SPECS:
        records, duplicate_diagnostics = _materialize_collection(
            spec=spec,
            records=records_by_kind.get(spec.kind, ()),
        )
        materialized[spec.kind] = records
        diagnostics.extend(duplicate_diagnostics)

    diagnostics = sorted_diagnostics(diagnostics)
    if diagnostics:
        return RepositoryBuildResult(snapshot=None, diagnostics=tuple(diagnostics))

    return RepositoryBuildResult(
        snapshot=RepositorySnapshot(
            vendors=materialized[VENDOR.kind],
            sources=materialized[SOURCE.kind],
            source_observations=materialized[SOURCE_OBSERVATION.kind],
            assurances=materialized[ASSURANCE.kind],
            assurance_observations=materialized[ASSURANCE_OBSERVATION.kind],
            assurance_change_events=materialized[ASSURANCE_CHANGE_EVENT.kind],
        )
    )


def validate_assurance_record_semantics(
    record: RepositoryRecord,
    repository: RepositoryView,
) -> list[SemanticDiagnostic]:
    if record.kind != "assurance":
        raise ValueError(
            f"validate_assurance_record_semantics requires an assurance record, "
            f"received {record.kind!r}"
        )

    diagnostics: list[SemanticDiagnostic] = []

    # Rule: ASSURANCE_VENDOR_UNKNOWN
    vendor_id = record.data["vendor_id"]
    vendor_record = repository.get_vendor(vendor_id)

    if vendor_record is None:
        diagnostics.append(
            SemanticDiagnostic(
                code="ASSURANCE_VENDOR_UNKNOWN",
                record_kind="assurance",
                record_id=record.record_id,
                record_path=record.path,
                instance_path="/vendor_id",
                message=f"Referenced vendor {vendor_id!r} does not exist.",
                related_ids=(vendor_id,),
            )
        )

    # Rule: ASSURANCE_PRIMARY_SOURCE_NOT_IN_EVIDENCE_SET
    evidence = record.data["evidence"]
    source_ids = evidence["source_ids"]
    primary_source_id = evidence.get("primary_source_id")
    if isinstance(primary_source_id, str) and primary_source_id not in source_ids:
        diagnostics.append(
            SemanticDiagnostic(
                code=ASSURANCE_PRIMARY_SOURCE_NOT_IN_EVIDENCE_SET,
                record_kind="assurance",
                record_id=record.record_id,
                record_path=record.path,
                instance_path="/evidence/primary_source_id",
                message=(
                    f"Primary source {primary_source_id!r} is not present "
                    "in evidence.source_ids."
                ),
                related_ids=(primary_source_id,),
            )
        )

    # Rule: ASSURANCE_SOURCE_UNKNOWN & ASSURANCE_SOURCE_VENDOR_MISMATCH
    for index, source_id in enumerate(source_ids):
        source_record = repository.get_source(source_id)

        if source_record is None:
            diagnostics.append(
                SemanticDiagnostic(
                    code="ASSURANCE_SOURCE_UNKNOWN",
                    record_kind="assurance",
                    record_id=record.record_id,
                    record_path=record.path,
                    instance_path=f"/evidence/source_ids/{index}",
                    message=f"Referenced source {source_id!r} does not exist.",
                    related_ids=(source_id,),
                )
            )
            continue

        # Rule: ASSURANCE_SOURCE_VENDOR_MISMATCH
        if (
            vendor_record is not None
            and source_record.vendor_id != record.vendor_id
        ):
            diagnostics.append(
                SemanticDiagnostic(
                    code="ASSURANCE_SOURCE_VENDOR_MISMATCH",
                    record_kind="assurance",
                    record_id=record.record_id,
                    record_path=record.path,
                    instance_path=f"/evidence/source_ids/{index}",
                    message=(
                        f"Source {source_id!r} belongs to vendor "
                        f"{source_record.vendor_id!r}, but assurance "
                        f"belongs to vendor {record.vendor_id!r}."
                    ),
                    related_ids=(
                        source_id,
                        source_record.vendor_id,
                        record.vendor_id,
                    ),
                )
            )

    return diagnostics


def sorted_diagnostics(diagnostics: Iterable[ValidationDiagnostic]) -> list[ValidationDiagnostic]:
    return sorted(
        diagnostics,
        key=lambda diagnostic: (
            diagnostic.record_path or "",
            diagnostic.instance_path,
            diagnostic.code,
            diagnostic.record_kind,
            diagnostic.record_id,
            diagnostic.related_ids,
        ),
    )


def validate_assurance_repository(repository: RepositoryView) -> tuple[ValidationDiagnostic, ...]:
    diagnostics: list[ValidationDiagnostic] = []
    for assurance_id in sorted(repository.assurances):
        diagnostics.extend(
            validate_assurance_record_semantics(repository.assurances[assurance_id], repository)
        )
    return tuple(sorted_diagnostics(diagnostics))
