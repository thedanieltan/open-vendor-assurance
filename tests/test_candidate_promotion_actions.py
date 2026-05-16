import yaml

from tools.openva.candidate_promotion_actions import apply_candidate_promotions


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_apply_reviewed_candidate_promotion_writes_canonical_source(tmp_path):
    write_yaml(
        tmp_path / "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        {
            "schema_version": "0.1.0",
            "candidate_source_id": "example-dpa-candidate",
            "vendor_id": "example",
            "source_type_candidate": "dpa",
            "candidate_url": "https://example.test/dpa",
            "confidence": "likely",
            "requires_review": True,
            "evidence": {"http_status": 200, "matched_terms": ["data processing"]},
            "not_advice": True,
        },
    )
    action = {
        "action": "promote_candidate_source_for_review",
        "vendor_id": "example",
        "source_type": "dpa",
        "candidate_source_id": "example-dpa-candidate",
        "candidate_url": "https://example.test/dpa",
        "path": "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        "requires_human_review": True,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }

    report = apply_candidate_promotions({"actions": [action]}, root=tmp_path)
    source_path = tmp_path / "data/vendors/example/sources/example-dpa.yaml"
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))

    assert report["summary"]["canonical_sources_written"] == 1
    assert source["source_id"] == "example-dpa"
    assert source["source_url"] == "https://example.test/dpa"
    assert source["rights_class"] == "metadata_only"
    assert source["not_advice"] is True


def test_apply_reviewed_candidate_promotion_skips_duplicate_source(tmp_path):
    write_yaml(
        tmp_path / "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        {
            "schema_version": "0.1.0",
            "candidate_source_id": "example-dpa-candidate",
            "vendor_id": "example",
            "source_type_candidate": "dpa",
            "candidate_url": "https://example.test/dpa",
            "requires_review": True,
            "evidence": {"http_status": 200, "matched_terms": ["data processing"]},
            "not_advice": True,
        },
    )
    write_yaml(
        tmp_path / "data/vendors/example/sources/example-dpa.yaml",
        {"schema_version": "0.1.0", "source_id": "example-dpa", "vendor_id": "example"},
    )
    action = {
        "action": "promote_candidate_source_for_review",
        "vendor_id": "example",
        "source_type": "dpa",
        "candidate_source_id": "example-dpa-candidate",
        "candidate_url": "https://example.test/dpa",
        "path": "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        "requires_human_review": True,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }

    report = apply_candidate_promotions({"actions": [action]}, root=tmp_path)

    assert report["summary"]["canonical_sources_written"] == 0
    assert report["summary"]["skipped_actions"] == 1
