from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError

from tests.test_assurance_intelligence_materialization import complete_support_repository
from tests.test_assurance_intelligence_materialization import projection_from
from tests.test_assurance_intelligence_materialization import request_for
from tools.openva.assurance_intelligence import INTELLIGENCE_AXES
from tools.openva.assurance_intelligence_materialization import latest_index_document
from tools.openva.assurance_intelligence_publication import (
    ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
    ASSURANCE_INTELLIGENCE_PUBLICATION_OUTPUT_INVALID,
    ASSURANCE_INTELLIGENCE_PUBLICATION_PATH_INVALID,
    PUBLICATION_POLICY_PATH,
    PUBLIC_SNAPSHOT_RELATIVE_PATH,
    AssuranceIntelligencePublicationError,
    build_assurance_intelligence_public_snapshot,
    build_assurance_intelligence_public_snapshot_from_repository,
    publication_policy_digest,
    validate_public_snapshot,
    write_assurance_intelligence_public_snapshot,
)
from tools.openva.assurance_projection_materialization import json_bytes
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_schema_registry, build_openva_validator

POLICY_SCHEMA = ROOT / "schemas/openva/assurance-intelligence-publication-policy.schema.json"
SNAPSHOT_SCHEMA = ROOT / "schemas/openva/assurance-intelligence-public-snapshot.schema.json"
INDEX_SCHEMA = ROOT / "schemas/openva/assurance-intelligence-latest-index.schema.json"


def load_policy() -> dict:
    policy = yaml.safe_load(PUBLICATION_POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(policy, dict)
    return policy


def valid_projection(
    assurance_id: str = "acme-iso-2026",
    *,
    vendor_id: str | None = None,
) -> dict:
    projection = projection_from(complete_support_repository(), request_for(assurance_id))
    if vendor_id is not None:
        projection["vendor_id"] = vendor_id
    return projection


def index_for(*projections: dict) -> dict:
    return latest_index_document(
        [
            {
                "assurance_id": projection["assurance_id"],
                "vendor_id": projection["vendor_id"],
                "projection_profile": projection["projection_profile"],
                "projection_ref": f"maintenance/assurance-intelligence/latest/{projection['assurance_id'][:2]}/{projection['assurance_id']}.json",
                "policies": projection["policies"],
                "input_digest": projection["input_digest"],
                "effective_at": projection["effective_at"],
                "knowledge_cutoff": projection["knowledge_cutoff"],
                "next_reevaluation_at": projection["next_reevaluation_at"],
            }
            for projection in projections
        ]
    )


def projection_mapping(*projections: dict) -> dict[str, dict]:
    return {
        f"maintenance/assurance-intelligence/latest/{projection['assurance_id'][:2]}/{projection['assurance_id']}.json": projection
        for projection in projections
    }


def test_publication_schemas_register_offline_and_policy_digest_is_real() -> None:
    registry = build_openva_schema_registry()
    assert registry is not None
    policy = load_policy()

    build_openva_validator(POLICY_SCHEMA).validate(policy)

    digest = publication_policy_digest(policy)
    assert digest == sha256_bytes(canonical_json(policy))
    assert digest.startswith("sha256:")
    assert set(digest.removeprefix("sha256:")) != {"0"}


def test_empty_snapshot_is_valid_and_public_safe() -> None:
    policy = load_policy()
    snapshot = build_assurance_intelligence_public_snapshot(
        latest_index_document([]),
        {},
        policy,
        {},
    )

    assert snapshot["snapshot_type"] == "empty"
    assert snapshot["summary"] == {"assurance_count": 0, "axis_count": 5}
    assert snapshot["entries"] == []
    validate_public_snapshot(snapshot)


def test_one_valid_five_axis_entry_exposes_only_public_allowlist() -> None:
    policy = load_policy()
    projection = valid_projection()
    metadata = {
        "acme-iso-2026": {
            "assurance_label": "Acme ISO 27001 2026",
            "assurance_class": "accredited_certification",
            "framework": {"framework_id": "iso-27001", "display_name": "ISO 27001"},
        }
    }

    snapshot = build_assurance_intelligence_public_snapshot(
        index_for(projection),
        projection_mapping(projection),
        policy,
        metadata,
    )

    entry = snapshot["entries"][0]
    assert entry["assurance_label"] == "Acme ISO 27001 2026"
    assert entry["framework_id"] == "iso-27001"
    assert list(entry["axes"]) == list(INTELLIGENCE_AXES)
    assert entry["axes"]["verification_state"]["value"] == "confirmed"
    assert entry["axes"]["verification_state"]["reason_code"] == "decisive_observations_support"
    assert "input_digest" not in json.dumps(snapshot, sort_keys=True)
    assert "caused_by" not in json.dumps(snapshot, sort_keys=True)
    assert "assurance_observation_ids" not in json.dumps(snapshot, sort_keys=True)
    validate_public_snapshot(snapshot)


def test_multiple_entries_sort_by_vendor_then_assurance() -> None:
    policy = load_policy()
    a = valid_projection("acme-iso-2026")
    b = deepcopy(a)
    b["assurance_id"] = "beta-iso-2026"
    b["vendor_id"] = "beta"
    b["input_digest"] = "sha256:" + "b" * 64
    c = deepcopy(a)
    c["assurance_id"] = "acme-attestation-2026"
    c["input_digest"] = "sha256:" + "c" * 64

    snapshot = build_assurance_intelligence_public_snapshot(
        index_for(b, c, a),
        projection_mapping(b, c, a),
        policy,
        {},
    )

    assert [(entry["vendor_id"], entry["assurance_id"]) for entry in snapshot["entries"]] == [
        ("acme", "acme-attestation-2026"),
        ("acme", "acme-iso-2026"),
        ("beta", "beta-iso-2026"),
    ]


def test_snapshot_is_byte_stable_and_input_order_independent() -> None:
    policy = load_policy()
    a = valid_projection("acme-iso-2026")
    b = deepcopy(a)
    b["assurance_id"] = "beta-iso-2026"
    b["vendor_id"] = "beta"
    b["input_digest"] = "sha256:" + "b" * 64

    first = build_assurance_intelligence_public_snapshot(index_for(a, b), projection_mapping(a, b), policy, {})
    second = build_assurance_intelligence_public_snapshot(index_for(b, a), projection_mapping(b, a), policy, {})

    assert json_bytes(first) == json_bytes(second)


def test_schema_rejects_forbidden_public_fields() -> None:
    snapshot = build_assurance_intelligence_public_snapshot(
        index_for(valid_projection()),
        projection_mapping(valid_projection()),
        load_policy(),
        {},
    )
    snapshot["entries"][0]["input_digest"] = "sha256:" + "a" * 64

    with pytest.raises(ValidationError):
        build_openva_validator(SNAPSHOT_SCHEMA).validate(snapshot)


def test_unsupported_profile_fails_closed() -> None:
    projection = valid_projection()
    projection["projection_profile"] = "openva.assurance-lifecycle.v1"

    with pytest.raises(AssuranceIntelligencePublicationError) as exc_info:
        build_assurance_intelligence_public_snapshot(
            index_for(projection),
            projection_mapping(projection),
            load_policy(),
            {},
        )

    assert exc_info.value.code == ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID


def test_latest_index_identity_mismatch_fails_closed() -> None:
    projection = valid_projection()
    latest_index = index_for(projection)
    latest_index["entries"][0]["vendor_id"] = "wrong-vendor"

    with pytest.raises(AssuranceIntelligencePublicationError) as exc_info:
        build_assurance_intelligence_public_snapshot(
            latest_index,
            projection_mapping(projection),
            load_policy(),
            {},
        )

    assert exc_info.value.code == ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID


def test_missing_projection_reference_fails_closed() -> None:
    projection = valid_projection()

    with pytest.raises(AssuranceIntelligencePublicationError) as exc_info:
        build_assurance_intelligence_public_snapshot(index_for(projection), {}, load_policy(), {})

    assert exc_info.value.code == ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID


def test_internal_leakage_fails_closed() -> None:
    snapshot = build_assurance_intelligence_public_snapshot(
        index_for(valid_projection()),
        projection_mapping(valid_projection()),
        load_policy(),
        {},
    )
    snapshot["entries"][0]["axes"]["verification_state"]["reason_code"] = "caused_by"

    with pytest.raises(AssuranceIntelligencePublicationError) as exc_info:
        validate_public_snapshot(snapshot)
        from tools.openva.assurance_intelligence_publication import assert_no_public_leakage

        assert_no_public_leakage(snapshot)

    assert exc_info.value.code == ASSURANCE_INTELLIGENCE_PUBLICATION_OUTPUT_INVALID


def test_repository_builder_rejects_unsafe_projection_ref(tmp_path: Path) -> None:
    latest_index = index_for(valid_projection())
    latest_index["entries"][0]["projection_ref"] = "../outside.json"
    index_path = tmp_path / "maintenance/assurance-intelligence/latest-index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(json.dumps(latest_index), encoding="utf-8")

    with pytest.raises(AssuranceIntelligencePublicationError) as exc_info:
        build_assurance_intelligence_public_snapshot_from_repository(tmp_path)

    assert exc_info.value.code in {
        ASSURANCE_INTELLIGENCE_PUBLICATION_INPUT_INVALID,
        ASSURANCE_INTELLIGENCE_PUBLICATION_PATH_INVALID,
    }


def test_write_public_snapshot_uses_public_artifact_path(tmp_path: Path) -> None:
    result = write_assurance_intelligence_public_snapshot(tmp_path)

    assert result.output_path == PUBLIC_SNAPSHOT_RELATIVE_PATH
    assert result.snapshot["entries"] == []
    assert (tmp_path / PUBLIC_SNAPSHOT_RELATIVE_PATH).is_file()


def test_source_health_changes_do_not_affect_public_snapshot() -> None:
    policy = load_policy()
    projection = valid_projection()
    latest_index = index_for(projection)
    projections = projection_mapping(projection)

    source_health_a = {"status": "ok"}
    source_health_b = {"status": "gone"}
    assert source_health_a != source_health_b

    assert build_assurance_intelligence_public_snapshot(latest_index, projections, policy, {}) == (
        build_assurance_intelligence_public_snapshot(latest_index, projections, policy, {})
    )
