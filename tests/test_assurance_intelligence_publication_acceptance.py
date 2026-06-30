from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from tests.test_assurance_intelligence_publication import valid_projection
from tests.test_site import build_site, source_rows
from tools.openva import release_artifacts
from tools.openva.assurance_intelligence import INTELLIGENCE_AXES
from tools.openva.assurance_intelligence_materialization import (
    latest_index_document,
    latest_intelligence_projection_relative_path,
)
from tools.openva.assurance_intelligence_publication import (
    ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
    PUBLIC_SNAPSHOT_RELATIVE_PATH,
    AssuranceIntelligencePublicationError,
    build_assurance_intelligence_public_snapshot_from_repository,
    write_assurance_intelligence_public_snapshot,
)
from tools.openva.assurance_projection_materialization import json_bytes
from tools.openva.schema_registry import ROOT


FORBIDDEN_PUBLIC_TOKENS = (
    "input_digest",
    "policy digest",
    "projection_ref",
    "maintenance/",
    "caused_by",
    "assurance_observation_ids",
    "source_observation_ids",
)


def write_materialized_intelligence(root: Path, projection: dict) -> None:
    projection_ref = latest_intelligence_projection_relative_path(projection["assurance_id"])
    projection_path = root / projection_ref
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.write_bytes(json_bytes(projection))
    latest_index = latest_index_document(
        [
            {
                "assurance_id": projection["assurance_id"],
                "vendor_id": projection["vendor_id"],
                "projection_profile": projection["projection_profile"],
                "projection_ref": projection_ref,
                "policies": projection["policies"],
                "input_digest": projection["input_digest"],
                "effective_at": projection["effective_at"],
                "knowledge_cutoff": projection["knowledge_cutoff"],
                "next_reevaluation_at": projection["next_reevaluation_at"],
            }
        ]
    )
    index_path = root / "maintenance" / "assurance-intelligence" / "latest-index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(json_bytes(latest_index))


def public_artifact_texts(site_out: Path, snapshot_path: Path) -> str:
    parts = [
        snapshot_path.read_text(encoding="utf-8"),
        (site_out / "data" / "assurance-intelligence.json").read_text(encoding="utf-8"),
    ]
    parts.extend(path.read_text(encoding="utf-8") for path in sorted((site_out / "data" / "vendors").glob("*.json")))
    return "\n".join(parts)


def test_materialized_intelligence_publishes_to_snapshot_site_and_release_manifest(monkeypatch, tmp_path):
    repository_root = tmp_path / "repo"
    projection = valid_projection()
    projection["vendor_id"] = source_rows(1)[0]["vendor_id"]
    write_materialized_intelligence(repository_root, projection)

    result = write_assurance_intelligence_public_snapshot(repository_root, PUBLIC_SNAPSHOT_RELATIVE_PATH)
    snapshot_path = repository_root / PUBLIC_SNAPSHOT_RELATIVE_PATH
    site_out = build_site(tmp_path, assurance_intelligence=snapshot_path)

    snapshot = result.snapshot
    assert snapshot["projection_profile"] == "openva.assurance-intelligence.v1"
    assert list(snapshot["entries"][0]["axes"]) == list(INTELLIGENCE_AXES)
    assert snapshot["entries"][0]["axes"]["verification_state"]["value"] == "confirmed"

    site_snapshot = json.loads((site_out / "data" / "assurance-intelligence.json").read_text(encoding="utf-8"))
    assert site_snapshot == snapshot
    assert (site_out / "data" / "vendors" / f"{projection['vendor_id']}.json").is_file()

    public_text = public_artifact_texts(site_out, snapshot_path)
    for token in FORBIDDEN_PUBLIC_TOKENS:
        assert token not in public_text

    monkeypatch.setattr(release_artifacts, "ROOT", repository_root)
    monkeypatch.setattr(release_artifacts, "MANIFEST_PATH", repository_root / "release-artifacts.json")
    monkeypatch.setattr(release_artifacts, "ARTIFACT_PATTERNS", ["public/assurance-intelligence.json"])
    monkeypatch.setattr(release_artifacts, "REQUIRED_ARTIFACTS", ["public/assurance-intelligence.json"])
    manifest = release_artifacts.build_manifest()
    assert [artifact["path"] for artifact in manifest["artifacts"]] == ["public/assurance-intelligence.json"]


def test_publication_is_repeatable_and_ignores_source_health_changes(tmp_path):
    repository_root = tmp_path / "repo"
    write_materialized_intelligence(repository_root, valid_projection())
    (repository_root / "public").mkdir(parents=True)
    (repository_root / "public" / "source-health-snapshot.json").write_text('{"status":"warning"}\n', encoding="utf-8")

    first = build_assurance_intelligence_public_snapshot_from_repository(repository_root)
    (repository_root / "public" / "source-health-snapshot.json").write_text('{"status":"unavailable"}\n', encoding="utf-8")
    second = build_assurance_intelligence_public_snapshot_from_repository(repository_root)

    assert json_bytes(first) == json_bytes(second)


def test_malformed_maintenance_projection_fails_closed(tmp_path):
    repository_root = tmp_path / "repo"
    projection = valid_projection()
    projection["implemented_axes"] = ["instrument_state"]
    write_materialized_intelligence(repository_root, projection)

    with pytest.raises(AssuranceIntelligencePublicationError) as exc_info:
        build_assurance_intelligence_public_snapshot_from_repository(repository_root)

    assert exc_info.value.code == ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID


def test_publication_output_is_stable_under_projected_at_only_changes(tmp_path):
    repository_root = tmp_path / "repo"
    projection = valid_projection()
    write_materialized_intelligence(repository_root, projection)
    first = build_assurance_intelligence_public_snapshot_from_repository(repository_root)

    changed = deepcopy(projection)
    changed["projected_at"] = "2026-07-01T00:00:00Z"
    write_materialized_intelligence(repository_root, changed)
    second = build_assurance_intelligence_public_snapshot_from_repository(repository_root)

    assert json_bytes(first) == json_bytes(second)


def test_lifecycle_profile_remains_two_axis():
    schema = json.loads((ROOT / "schemas/openva/assurance-projection.schema.json").read_text(encoding="utf-8"))
    implemented_axes = [
        item["const"]
        for item in schema["properties"]["implemented_axes"]["prefixItems"]
    ]

    assert implemented_axes == ["instrument_state", "supersession_state"]
