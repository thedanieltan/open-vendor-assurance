from pathlib import Path


NO_REPLACEMENT_DESIGN = Path("docs/operations/NO_REPLACEMENT_TRUTH_STATE_DESIGN.md")
SOURCE_SCHEDULER_SPEC = Path("docs/operations/SOURCE_OPERATIONS_SCHEDULER_SPEC.md")
CATALOG_GATING_SPEC = Path("docs/operations/CATALOG_GROWTH_GATING_DASHBOARD_SPEC.md")
CONSOLIDATION_AUDIT = Path("docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md")


def test_no_replacement_truth_state_design_is_design_only_and_non_mutating():
    text = NO_REPLACEMENT_DESIGN.read_text(encoding="utf-8")

    assert "No catalog source YAML is mutated by this design" in text
    assert "Reviewed artifacts under `maintenance/reviewed/` are evidence" in text
    assert "not durable catalog state until a later controlled application path" in text
    assert "source records remain reserved for canonical available sources" in text
    assert "source repairs, deletion instructions" in text
    assert "First-class unavailable-source structure" in text
    assert "Durable reviewed no-replacement state belongs under" in text


def test_no_replacement_truth_state_design_requires_freshness_and_validators():
    text = NO_REPLACEMENT_DESIGN.read_text(encoding="utf-8")

    assert "`next_review_after` is required" in text
    assert "Re-check cadence should be no longer than 90 days" in text
    assert "Any new candidate source found by discovery invalidates" in text
    assert "Reviewed evidence is committed under `maintenance/reviewed/`" in text
    assert "Validation has zero invalid rows" in text
    assert "No source record is deleted" in text
    assert "`truth_state_status` distinguishes `current`, `stale`, `expired`, and `superseded` state" in text


def test_source_operations_scheduler_spec_is_non_implementation_spec():
    text = SOURCE_SCHEDULER_SPEC.read_text(encoding="utf-8")

    assert "It is a spec only" in text
    assert "does not create a workflow" in text
    assert "does not mutate catalog records" in text
    assert "`source-maintenance-report.yml` remains the source cleanup and reporting entry point" in text
    assert "must not replace the full source maintenance artifact package" in text
    assert "It must not bypass confirmation history or generate repairs directly" in text


def test_source_operations_scheduler_spec_covers_sharding_incremental_and_release_readiness():
    text = SOURCE_SCHEDULER_SPEC.read_text(encoding="utf-8")

    assert "deterministic source-check sharding" in text
    assert "incremental source verification" in text
    assert "No source should be skipped indefinitely" in text
    assert "emergency full runs" in text
    assert "Relationship to `source-refinement-scan.yml`" in text
    assert "Relationship to release readiness" in text
    assert "fail closed for release readiness" in text


def test_catalog_growth_gating_dashboard_spec_is_operator_aid_only():
    text = CATALOG_GATING_SPEC.read_text(encoding="utf-8")

    assert "It is a spec only" in text
    assert "does not build UI" in text
    assert "The dashboard is an operator decision aid" in text
    assert "must not automatically promote candidates" in text
    assert "must not automatically mutate `data/vendors/**`" in text
    assert "not become a source of catalog truth" in text


def test_catalog_growth_gating_dashboard_spec_covers_required_loops_and_states():
    text = CATALOG_GATING_SPEC.read_text(encoding="utf-8")

    for state in [
        "promotion_allowed",
        "promotion_allowed_with_warnings",
        "promotion_blocked_source_debt",
        "promotion_blocked_catalog_quality",
        "promotion_blocked_missing_artifacts",
    ]:
        assert state in text

    assert "Relationship to `catalog-growth-discovery.yml`" in text
    assert "Relationship to `candidate-promotion-pr.yml`" in text
    assert "Relationship to `source-maintenance-report.yml`" in text
    assert "Relationship to `coverage-audit.yml`" in text
    assert "Relationship to release/site loop" in text


def test_consolidation_audit_references_remaining_future_specs_without_implementation():
    text = CONSOLIDATION_AUDIT.read_text(encoding="utf-8")

    assert "NO_REPLACEMENT_TRUTH_STATE_DESIGN.md" in text
    assert "SOURCE_OPERATIONS_SCHEDULER_SPEC.md" in text
    assert "CATALOG_GROWTH_GATING_DASHBOARD_SPEC.md" in text
    assert "Do not implement until the truth-state schema is decided." in text
    assert "Do not implement now." in text
