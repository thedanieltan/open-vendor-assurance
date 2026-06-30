from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tools.openva.assurance_intelligence import (
    INTELLIGENCE_AXES,
    INTELLIGENCE_PROFILE,
    AssuranceIntelligenceError,
    validate_intelligence_output,
)
from tools.openva.assurance_intelligence_materialization import (
    AssuranceIntelligenceMaterializationError,
    latest_intelligence_index_relative_path,
    load_latest_intelligence_index,
)
from tools.openva.assurance_projection import json_material
from tools.openva.assurance_projection_materialization import (
    atomic_write_bytes,
    json_bytes,
    load_json_object,
    resolve_repo_path,
    validate_destination_path,
)
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator

PUBLICATION_POLICY_PATH = ROOT / "config/assurance-intelligence-publication-policy.yaml"
PUBLICATION_POLICY_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-publication-policy.schema.json"
PUBLIC_SNAPSHOT_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-public-snapshot.schema.json"
PUBLIC_SNAPSHOT_RELATIVE_PATH = "public/assurance-intelligence.json"
REPORT_TYPE = "assurance_intelligence_public_snapshot"
SNAPSHOT_SCHEMA_VERSION = "0.1.0"

FORBIDDEN_PUBLIC_TOKENS = (
    "input_digest",
    "policy digest",
    "projection_ref",
    "maintenance/",
    "caused_by",
    "assurance_observation_ids",
    "source_observation_ids",
)


class AssuranceIntelligencePublicationError(ValueError):
    def __init__(self, code: str, message: str, *, instance_path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.instance_path = instance_path


ASSURANCE_INTELLIGENCE_PUBLICATION_POLICY_INVALID = "ASSURANCE_INTELLIGENCE_PUBLICATION_POLICY_INVALID"
ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID = "ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID"
ASSURANCE_INTELLIGENCE_PUBLICATION_PATH_INVALID = "ASSURANCE_INTELLIGENCE_PUBLICATION_PATH_INVALID"
ASSURANCE_INTELLIGENCE_PUBLICATION_OUTPUT_INVALID = "ASSURANCE_INTELLIGENCE_PUBLICATION_OUTPUT_INVALID"


@dataclass(frozen=True, slots=True)
class AssuranceIntelligencePublicSnapshotWriteResult:
    snapshot: Mapping[str, Any]
    output_path: str
    written: bool


def load_yaml_object(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_POLICY_INVALID,
            f"{path} must contain a YAML mapping.",
        )
    return data


def publication_policy_digest(policy: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(json_material(policy)))


def validate_publication_policy(policy: Mapping[str, Any]) -> None:
    validator = build_openva_validator(PUBLICATION_POLICY_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(policy), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_POLICY_INVALID,
            f"Assurance intelligence publication policy is invalid: {error.message}",
            instance_path="/" + "/".join(str(part) for part in error.path) if error.path else "",
        )
    if tuple(policy["allowed_axes"]) != tuple(INTELLIGENCE_AXES):
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_POLICY_INVALID,
            "Publication policy allowed_axes must match the intelligence profile axis order.",
            instance_path="/allowed_axes",
        )


def validate_public_snapshot(snapshot: Mapping[str, Any]) -> None:
    validator = build_openva_validator(PUBLIC_SNAPSHOT_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(snapshot), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_OUTPUT_INVALID,
            f"Assurance intelligence public snapshot is invalid: {error.message}",
            instance_path="/" + "/".join(str(part) for part in error.path) if error.path else "",
        )
    assurance_ids = [entry["assurance_id"] for entry in snapshot["entries"]]
    if len(assurance_ids) != len(set(assurance_ids)):
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_OUTPUT_INVALID,
            "Assurance intelligence public snapshot contains duplicate assurance IDs.",
            instance_path="/entries",
        )


def validate_latest_index_document(latest_index: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    validator = build_openva_validator(ROOT / "schemas/openva/assurance-intelligence-latest-index.schema.json")
    errors = sorted(validator.iter_errors(latest_index), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
            f"Latest intelligence index is invalid: {error.message}",
            instance_path="/" + "/".join(str(part) for part in error.path) if error.path else "",
        )
    entries = latest_index.get("entries")
    if not isinstance(entries, list):
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
            "Latest intelligence index entries must be a list.",
            instance_path="/entries",
        )
    assurance_ids = [entry.get("assurance_id") for entry in entries if isinstance(entry, Mapping)]
    if len(assurance_ids) != len(set(assurance_ids)):
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
            "Latest intelligence index contains duplicate assurance IDs.",
            instance_path="/entries",
        )
    return tuple(entry for entry in entries if isinstance(entry, Mapping))


def public_axis(axis: Mapping[str, Any], *, expose_reason_codes: bool) -> dict[str, Any]:
    reasons = axis.get("reason_codes")
    reason_code = None
    if expose_reason_codes:
        if not isinstance(reasons, list) or len(reasons) != 1:
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
                "A public axis reason requires exactly one source reason code.",
                instance_path="/axes/reason_codes",
            )
        reason_code = str(reasons[0])
    return {
        "value": str(axis["value"]),
        "reason_code": reason_code,
    }


def public_metadata_for_assurance(
    assurance_id: str,
    public_assurance_metadata: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if not public_assurance_metadata:
        return {
            "assurance_label": None,
            "assurance_class": None,
            "framework_id": None,
            "framework_display_name": None,
        }
    metadata = public_assurance_metadata.get(assurance_id, {})
    framework = metadata.get("framework") if isinstance(metadata.get("framework"), Mapping) else {}
    return {
        "assurance_label": metadata.get("assurance_label") or metadata.get("display_name") or metadata.get("assurance_id"),
        "assurance_class": metadata.get("assurance_class"),
        "framework_id": framework.get("framework_id") or metadata.get("framework_id"),
        "framework_display_name": framework.get("display_name") or metadata.get("framework_display_name"),
    }


def public_entry(
    projection: Mapping[str, Any],
    *,
    publication_policy: Mapping[str, Any],
    public_assurance_metadata: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    try:
        validate_intelligence_output(projection)
    except AssuranceIntelligenceError as exc:
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
            str(exc),
            instance_path=exc.instance_path,
        ) from exc
    if projection.get("projection_profile") not in set(publication_policy["allowed_projection_profiles"]):
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
            f"Unsupported assurance intelligence profile: {projection.get('projection_profile')!r}.",
            instance_path="/projection_profile",
        )
    if tuple(projection.get("implemented_axes", ())) != tuple(publication_policy["allowed_axes"]):
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
            "Projection implemented_axes do not match the publication policy.",
            instance_path="/implemented_axes",
        )
    assurance_id = str(projection["assurance_id"])
    metadata = public_metadata_for_assurance(assurance_id, public_assurance_metadata)
    axes = projection["axes"]
    return {
        "assurance_id": assurance_id,
        "vendor_id": str(projection["vendor_id"]),
        **metadata,
        "projection_profile": str(projection["projection_profile"]),
        "effective_at": str(projection["effective_at"]),
        "knowledge_cutoff": str(projection["knowledge_cutoff"]),
        "next_reevaluation_at": projection.get("next_reevaluation_at"),
        "axes": {
            axis_name: public_axis(
                axes[axis_name],
                expose_reason_codes=bool(publication_policy["expose_reason_codes"]),
            )
            for axis_name in INTELLIGENCE_AXES
        },
    }


def projection_for_index_entry(
    entry: Mapping[str, Any],
    projections: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    projection_ref = entry.get("projection_ref")
    if not isinstance(projection_ref, str) or projection_ref not in projections:
        raise AssuranceIntelligencePublicationError(
            ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
            f"Missing projection for latest-index reference {projection_ref!r}.",
            instance_path="/entries/projection_ref",
        )
    projection = projections[projection_ref]
    for field in ("assurance_id", "vendor_id", "projection_profile", "input_digest", "effective_at", "knowledge_cutoff", "next_reevaluation_at"):
        if json_material(projection.get(field)) != json_material(entry.get(field)):
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
                f"Latest-index field {field!r} does not match the referenced projection.",
                instance_path=f"/entries/{field}",
            )
    return projection


def assert_no_public_leakage(snapshot: Mapping[str, Any]) -> None:
    text = json.dumps(json_material(snapshot), sort_keys=True)
    for token in FORBIDDEN_PUBLIC_TOKENS:
        if token in text:
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_OUTPUT_INVALID,
                f"Public assurance intelligence snapshot leaks prohibited token {token!r}.",
            )


def build_assurance_intelligence_public_snapshot(
    latest_index: Mapping[str, Any],
    projections: Mapping[str, Mapping[str, Any]],
    publication_policy: Mapping[str, Any],
    public_assurance_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    validate_publication_policy(publication_policy)
    entries = []
    seen_assurance_ids: set[str] = set()
    for entry in validate_latest_index_document(latest_index):
        projection = projection_for_index_entry(entry, projections)
        public = public_entry(
            projection,
            publication_policy=publication_policy,
            public_assurance_metadata=public_assurance_metadata,
        )
        assurance_id = public["assurance_id"]
        if assurance_id in seen_assurance_ids:
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
                f"Duplicate assurance_id {assurance_id!r}.",
                instance_path="/entries",
            )
        seen_assurance_ids.add(assurance_id)
        entries.append(public)

    ordered = sorted(entries, key=lambda item: (str(item["vendor_id"]), str(item["assurance_id"])))
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "snapshot_type": "artifact_derived" if ordered else "empty",
        "projection_profile": INTELLIGENCE_PROFILE,
        "publication_policy": {
            "id": str(publication_policy["policy_id"]),
            "version": str(publication_policy["policy_version"]),
        },
        "summary": {
            "assurance_count": len(ordered),
            "axis_count": len(INTELLIGENCE_AXES),
        },
        "entries": ordered,
        "advisory_boundary": "non_advisory",
    }
    validate_public_snapshot(snapshot)
    assert_no_public_leakage(snapshot)
    return snapshot


def load_public_assurance_metadata(repository_root: Path) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for base in ("data/vendors/*/assurances/*.yaml", "examples/vendors/*/assurances/*.yaml"):
        for path in sorted(repository_root.glob(base)):
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(record, Mapping) and isinstance(record.get("assurance_id"), str):
                records[str(record["assurance_id"])] = json_material(record)
    return records


def load_referenced_projections(repository_root: Path, latest_index: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    projections: dict[str, Mapping[str, Any]] = {}
    for entry in validate_latest_index_document(latest_index):
        projection_ref = entry.get("projection_ref")
        if not isinstance(projection_ref, str):
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
                "Latest-index projection_ref must be a string.",
                instance_path="/entries/projection_ref",
            )
        if projection_ref.startswith("/") or "\\" in projection_ref or ".." in Path(projection_ref).parts:
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_PATH_INVALID,
                f"Unsafe projection_ref {projection_ref!r}.",
                instance_path="/entries/projection_ref",
            )
        path = resolve_repo_path(repository_root, projection_ref)
        if not path.exists():
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
                f"Referenced intelligence projection does not exist: {projection_ref}.",
                instance_path="/entries/projection_ref",
            )
        projections[projection_ref] = load_json_object(path)
    return projections


def build_assurance_intelligence_public_snapshot_from_repository(
    repository_root: Path = ROOT,
    publication_policy_path: Path = PUBLICATION_POLICY_PATH,
) -> dict[str, Any]:
    latest_index_path = resolve_repo_path(repository_root, latest_intelligence_index_relative_path())
    if latest_index_path.exists():
        try:
            latest_index = load_latest_intelligence_index(repository_root)
        except AssuranceIntelligenceMaterializationError as exc:
            raise AssuranceIntelligencePublicationError(
                ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
                str(exc),
                instance_path=exc.instance_path,
            ) from exc
    else:
        latest_index = {
            "schema_version": "0.1.0",
            "report_type": "assurance_intelligence_latest_index",
            "projection_profile": INTELLIGENCE_PROFILE,
            "count": 0,
            "entries": [],
        }
    policy = load_yaml_object(publication_policy_path)
    projections = load_referenced_projections(repository_root, latest_index)
    metadata = load_public_assurance_metadata(repository_root)
    return build_assurance_intelligence_public_snapshot(latest_index, projections, policy, metadata)


def write_assurance_intelligence_public_snapshot(
    repository_root: Path = ROOT,
    output_relative_path: str = PUBLIC_SNAPSHOT_RELATIVE_PATH,
    publication_policy_path: Path = PUBLICATION_POLICY_PATH,
) -> AssuranceIntelligencePublicSnapshotWriteResult:
    snapshot = build_assurance_intelligence_public_snapshot_from_repository(repository_root, publication_policy_path)
    output_path = validate_destination_path(repository_root, output_relative_path)
    written = atomic_write_bytes(output_path, json_bytes(snapshot))
    return AssuranceIntelligencePublicSnapshotWriteResult(
        snapshot=snapshot,
        output_path=output_relative_path,
        written=written,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-assurance-intelligence-publication")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--output", default=PUBLIC_SNAPSHOT_RELATIVE_PATH)
    parser.add_argument("--policy", type=Path, default=PUBLICATION_POLICY_PATH)
    args = parser.parse_args(argv)

    result = write_assurance_intelligence_public_snapshot(args.repository_root, args.output, args.policy)
    print(json.dumps({"output": result.output_path, "written": result.written}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
