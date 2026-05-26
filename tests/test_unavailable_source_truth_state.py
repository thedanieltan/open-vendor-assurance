from tools.openva.validate import validate_unavailable_truth_state


def canonical_source() -> dict:
    return {
        "source_id": "example-dpa",
        "vendor_id": "example",
        "source_type": "dpa",
        "source_url": "https://example.com/legal/dpa",
    }


def reviewed_no_replacement_record() -> dict:
    return {
        "vendor_id": "example",
        "source_type": "dpa",
        "truth_state": "reviewed_no_replacement_available",
        "truth_state_status": "current",
        "source_review_decision_id": "review-example-dpa",
        "reviewed_artifact_path": "maintenance/reviewed/source-review/example-dpa.json",
        "validation_report_path": "maintenance/reviewed/source-review/validation.json",
        "source_maintenance_run_id": "source-maintenance-report-12345",
        "reviewed_by": "human",
        "reviewer_note": "Reviewed public materials and no replacement was available at review time.",
        "original_source": {
            "source_id": "example-dpa",
            "source_url": "https://example.com/legal/dpa",
            "source_type": "dpa",
        },
    }


def test_validate_unavailable_truth_state_accepts_human_reviewed_no_replacement():
    failures = validate_unavailable_truth_state(
        "data/vendors/example/unavailable_sources/example-dpa.yaml",
        reviewed_no_replacement_record(),
        {"example-dpa": canonical_source()},
    )

    assert failures == []


def test_validate_unavailable_truth_state_rejects_agent_reviewed_no_replacement():
    record = reviewed_no_replacement_record()
    record["reviewed_by"] = "agent"

    failures = validate_unavailable_truth_state(
        "data/vendors/example/unavailable_sources/example-dpa.yaml",
        record,
        {"example-dpa": canonical_source()},
    )

    assert any("must be reviewed by human or hybrid" in failure for failure in failures)


def test_validate_unavailable_truth_state_requires_reviewed_artifact_paths():
    record = reviewed_no_replacement_record()
    record["reviewed_artifact_path"] = "data/vendors/example/unavailable_sources/example-dpa.yaml"
    record["validation_report_path"] = "reports/validation.json"

    failures = validate_unavailable_truth_state(
        "data/vendors/example/unavailable_sources/example-dpa.yaml",
        record,
        {"example-dpa": canonical_source()},
    )

    assert any("reviewed_artifact_path must be under maintenance/reviewed/" in failure for failure in failures)
    assert any("validation_report_path must be under maintenance/reviewed/" in failure for failure in failures)


def test_validate_unavailable_truth_state_rejects_original_source_mismatch():
    record = reviewed_no_replacement_record()
    record["original_source"]["source_url"] = "https://example.com/other"

    failures = validate_unavailable_truth_state(
        "data/vendors/example/unavailable_sources/example-dpa.yaml",
        record,
        {"example-dpa": canonical_source()},
    )

    assert any("original_source.source_url must match referenced source_id" in failure for failure in failures)


def test_validate_unavailable_truth_state_rejects_superseded_missing_source_reference():
    record = reviewed_no_replacement_record()
    record["truth_state_status"] = "superseded"
    record["superseded_by_source_id"] = "example-dpa-v2"
    record["superseded_at"] = "2026-08-01T00:00:00Z"

    failures = validate_unavailable_truth_state(
        "data/vendors/example/unavailable_sources/example-dpa.yaml",
        record,
        {"example-dpa": canonical_source()},
    )

    assert any("superseded_by_source_id example-dpa-v2 must reference an existing source" in failure for failure in failures)


def test_validate_unavailable_truth_state_accepts_superseded_with_same_vendor_replacement():
    record = reviewed_no_replacement_record()
    record["truth_state_status"] = "superseded"
    record["superseded_by_source_id"] = "example-dpa-v2"
    record["superseded_at"] = "2026-08-01T00:00:00Z"

    replacement = {
        "source_id": "example-dpa-v2",
        "vendor_id": "example",
        "source_type": "dpa",
        "source_url": "https://example.com/legal/dpa-v2",
    }
    failures = validate_unavailable_truth_state(
        "data/vendors/example/unavailable_sources/example-dpa.yaml",
        record,
        {"example-dpa": canonical_source(), "example-dpa-v2": replacement},
    )

    assert failures == []
