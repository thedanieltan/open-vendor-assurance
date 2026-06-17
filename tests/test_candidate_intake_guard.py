from __future__ import annotations

import json
from pathlib import Path

from tools.openva import candidate_record as cr
from tools.openva.automerge_lanes import is_candidate_intake_path
from tools.openva.candidate_intake_guard import check_candidate_intake

LABELS = ["candidate-intake", "automerge:candidate-intake"]
OBSERVED_AT = "2026-06-15T00:00:00Z"


def _valid_record() -> dict:
    # A schema-valid candidate record as the canonical ingress would produce it.
    return cr.build_candidate(
        candidate_origin="catalog_discovery",
        origin_reference="example",
        vendor_identity_candidate={"vendor_id_candidate": "example", "official_domain": "example.com"},
        source_candidates=[
            {
                "candidate_url": "https://example.com/dpa",
                "source_type_candidate": "dpa",
                "access_state": "public_reachable",
                "source_role": "primary_assurance",
            }
        ],
        evidence_references=[
            {"candidate_url": "https://example.com/dpa", "verification_result": "ok", "observed_at": OBSERVED_AT}
        ],
        discovery_component="vendor-resolution",
        created_at=OBSERVED_AT,
        eligibility_state="eligible",
        decision_reasons=[],
    )


def _write(root: Path, record: dict) -> Path:
    store = root / "maintenance" / "candidates"
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{record['candidate_id']}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def test_path_predicate_is_single_level_json_with_non_empty_stem():
    assert is_candidate_intake_path("maintenance/candidates/cand-x.json") is True
    assert is_candidate_intake_path("maintenance/candidates/.json") is False
    assert is_candidate_intake_path("maintenance/candidates/sub/cand-x.json") is False
    assert is_candidate_intake_path("maintenance/candidates/README.md") is False


def test_valid_candidate_record_passes(tmp_path: Path):
    record = _valid_record()
    assert cr.validate_candidate(record) == []
    path = _write(tmp_path, record)
    result = check_candidate_intake([_rel(tmp_path, path)], LABELS, root=tmp_path)
    assert result.eligible is True
    assert result.reasons == ()


def test_non_candidate_path_is_rejected(tmp_path: Path):
    result = check_candidate_intake(["data/vendors/stripe/sources/a.yaml"], LABELS, root=tmp_path)
    assert result.eligible is False
    assert "disallowed_path:data/vendors/stripe/sources/a.yaml" in result.reasons


def test_generated_or_canonical_drift_is_rejected(tmp_path: Path):
    result = check_candidate_intake(["indexes/sources.json"], LABELS, root=tmp_path)
    assert result.eligible is False
    assert "disallowed_path:indexes/sources.json" in result.reasons


def test_invalid_json_is_rejected(tmp_path: Path):
    store = tmp_path / "maintenance" / "candidates"
    store.mkdir(parents=True)
    bad = store / "cand-broken.json"
    bad.write_text("{not json", encoding="utf-8")
    result = check_candidate_intake([_rel(tmp_path, bad)], LABELS, root=tmp_path)
    assert result.eligible is False
    assert any("invalid_json" in reason for reason in result.reasons)


def test_schema_invalid_record_is_rejected(tmp_path: Path):
    store = tmp_path / "maintenance" / "candidates"
    store.mkdir(parents=True)
    bad = store / "cand-incomplete.json"
    bad.write_text(json.dumps({"candidate_origin": "catalog_discovery"}), encoding="utf-8")  # missing required fields
    result = check_candidate_intake([_rel(tmp_path, bad)], LABELS, root=tmp_path)
    assert result.eligible is False
    assert any(reason.startswith(f"{_rel(tmp_path, bad)}:") for reason in result.reasons)


def test_deletion_within_store_is_permitted(tmp_path: Path):
    # A cross-origin dedup removal deletes a maintenance/candidates/*.json file;
    # path-confinement only (not append-only), so an absent (deleted) path passes.
    result = check_candidate_intake(
        ["maintenance/candidates/cand-removed.json"], LABELS, root=tmp_path
    )
    assert result.eligible is True


def test_missing_labels_fail_closed(tmp_path: Path):
    path = _write(tmp_path, _valid_record())
    result = check_candidate_intake([_rel(tmp_path, path)], ["automerge:candidate-intake"], root=tmp_path)
    assert result.eligible is False
    assert "missing_label:candidate-intake" in result.reasons
