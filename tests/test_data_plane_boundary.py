"""The discovery/canonical plane boundary is machine-enforced and fails closed.

WP-OPENVA-DATA-PLANE-BOUNDARY-01.

Two invariants:
  1. Every committed discovery candidate record reproduces its deterministic, store-ready
     identity (so the discovery plane can leave GitHub for an append-only store).
  2. The canonical source-reference schema never absorbs discovery-plane-only bulk fields
     (so raw discovery signals cannot leak into the canonical catalog plane).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.openva import data_plane_boundary as boundary

ROOT = Path(__file__).resolve().parents[1]


def test_all_committed_candidate_records_are_store_addressable():
    assert boundary.check_store_addressability() == []


def test_canonical_plane_is_disjoint_from_discovery_bulk():
    assert boundary.check_plane_disjointness() == []


def test_full_check_passes_on_the_committed_tree():
    assert boundary.check() == []


def test_at_least_the_known_candidate_corpus_is_covered():
    # Guards against the globs silently matching nothing (which would make the store-
    # addressability assertion vacuously pass).
    assert len(boundary.candidate_record_paths()) >= 1000


def test_store_addressability_fails_closed_on_a_tampered_id(tmp_path, monkeypatch):
    # A record whose candidate_source_id does not reproduce from its identity is not
    # store-addressable and must be flagged.
    real = boundary.candidate_record_paths()[0]
    record = boundary._load_yaml(real)
    record["candidate_source_id"] = "tampered-not-reproducible-000000000000"
    vendor_dir = tmp_path / "data" / "vendors" / record["vendor_id"] / "candidate_sources"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "tampered.yaml").write_text(
        json.dumps(record), encoding="utf-8"
    )  # JSON is valid YAML
    monkeypatch.setattr(boundary, "ROOT", tmp_path)
    problems = boundary.check_store_addressability()
    assert problems
    assert any("not store-addressable" in p or "not reproducible" in p for p in problems)


def test_plane_disjointness_fails_closed_when_canonical_absorbs_discovery_field(
    tmp_path, monkeypatch
):
    # If the canonical schema ever declares a discovery-plane-only bulk field, the planes
    # have re-coupled and the guard must fail closed.
    schema = json.loads(boundary.CANONICAL_SOURCE_SCHEMA.read_text(encoding="utf-8"))
    schema.setdefault("properties", {})["evidence"] = {"type": "object"}
    leaked_schema = tmp_path / "source-reference.schema.json"
    leaked_schema.write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr(boundary, "CANONICAL_SOURCE_SCHEMA", leaked_schema)
    problems = boundary.check_plane_disjointness()
    assert problems
    assert any("leaked into the canonical" in p for p in problems)


def test_plane_disjointness_fails_closed_when_canonical_opens_additional_properties(
    tmp_path, monkeypatch
):
    schema = json.loads(boundary.CANONICAL_SOURCE_SCHEMA.read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    open_schema = tmp_path / "source-reference.schema.json"
    open_schema.write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr(boundary, "CANONICAL_SOURCE_SCHEMA", open_schema)
    problems = boundary.check_plane_disjointness()
    assert problems
    assert any("additionalProperties" in p for p in problems)
