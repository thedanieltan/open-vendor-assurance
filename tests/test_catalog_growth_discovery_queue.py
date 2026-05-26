import json
from pathlib import Path

import pytest

from tools.openva.catalog_growth_discovery_queue import validate_queue


QUEUE = Path("maintenance/queues/catalog-growth-discovery.json")
SCALE_READINESS = Path("maintenance/queues/catalog-growth-scale-readiness.json")
CATALOG_GROWTH_DOC = Path("docs/maintenance/catalog-growth-discovery.md")


def test_catalog_growth_discovery_queue_is_taxonomy_driven_and_bounded():
    summary = validate_queue(QUEUE)

    assert summary["queue_type"] == "catalog_growth_discovery_queue"
    assert summary["cohort_count"] >= 10
    assert summary["queued_cohort_count"] >= 10
    assert summary["target_vendor_candidates"] >= 200
    assert "cloud_platforms" in summary["coverage_lane_counts"]
    assert "security_identity" in summary["coverage_lane_counts"]
    assert "regional_apac" in summary["coverage_lane_counts"]


def test_catalog_growth_discovery_queue_preserves_non_mutating_posture():
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    assert queue["non_advisory"] is True
    assert queue["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "writes_canonical_sources": False,
        "creates_candidate_sources": False,
    }
    assert queue["limits"]["max_vendors_per_discovery_run"] <= 25
    assert queue["limits"]["max_reviewed_actions_per_plan"] <= 50


def test_catalog_growth_discovery_queue_rejects_unknown_taxonomy_lane(tmp_path):
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue["cohorts"][0]["coverage_lane"] = "unknown_lane"
    bad_queue = tmp_path / "catalog-growth-discovery.json"
    bad_queue.write_text(json.dumps(queue), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown coverage lane"):
        validate_queue(bad_queue)


def test_catalog_growth_discovery_queue_rejects_unknown_source_type(tmp_path):
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue["source_types"].append("unknown_source_type")
    bad_queue = tmp_path / "catalog-growth-discovery.json"
    bad_queue.write_text(json.dumps(queue), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown source type"):
        validate_queue(bad_queue)


def test_catalog_growth_scale_readiness_is_non_canonical_and_non_executing():
    plan = json.loads(SCALE_READINESS.read_text(encoding="utf-8"))

    assert plan["queue_type"] == "catalog_growth_scale_readiness"
    assert plan["non_advisory"] is True
    assert plan["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "writes_canonical_vendors": False,
        "writes_canonical_sources": False,
        "creates_candidate_sources": False,
        "creates_pull_requests": False,
        "runs_promotion": False,
    }


def test_catalog_growth_scale_readiness_defines_ordered_stage_model():
    plan = json.loads(SCALE_READINESS.read_text(encoding="utf-8"))
    stages = plan["stage_model"]

    assert [stage["stage_id"] for stage in stages] == [
        "bootstrap_seed_identity",
        "queue_driven_discovery",
        "evidence_scored_promotion",
        "continuous_refresh",
    ]
    assert stages[0]["canonical_write_allowed"] is False
    assert stages[1]["canonical_write_allowed"] is False
    assert stages[2]["canonical_write_allowed"] is True
    assert stages[2]["write_path"] == "candidate-promotion-pr.yml"
    assert stages[3]["canonical_write_allowed"] is False
    assert "phase_model" not in plan
    assert all("phase_id" not in stage for stage in stages)


def test_catalog_growth_scale_readiness_lifecycle_and_source_scope_are_bounded():
    plan = json.loads(SCALE_READINESS.read_text(encoding="utf-8"))

    assert plan["candidate_lifecycle"] == [
        "seeded",
        "discovered",
        "deduplicated",
        "source_discovered",
        "review_ready",
        "approved_for_promotion",
        "promoted",
        "observed",
        "maintenance_required",
    ]
    assert plan["core_source_types"] == [
        "dpa",
        "subprocessors_list",
        "privacy_notice",
        "security_page",
    ]
    assert "trust_center" in plan["extended_source_types_deferred"]
    assert "ai_terms" in plan["extended_source_types_deferred"]


def test_catalog_growth_scale_readiness_requires_promotion_blocks_and_handoff_contract():
    plan = json.loads(SCALE_READINESS.read_text(encoding="utf-8"))

    required_blocks = {
        "official_domain_unknown",
        "duplicate_vendor_or_entity_family",
        "no_public_source_candidates",
        "source_type_mismatch",
        "gated_only_materials",
        "raw_document_mirroring_required",
        "source_health_budget_exceeded",
        "review_plan_not_committed_under_maintenance_reviewed",
    }
    assert required_blocks <= set(plan["promotion_blocks"])
    assert plan["handoff_contract"] == {
        "bootstrap_input": "maintenance/seeds/vendors/*.yaml",
        "discovery_queue": "maintenance/queues/catalog-growth-discovery.json",
        "scale_readiness_queue": "maintenance/queues/catalog-growth-scale-readiness.json",
        "reviewed_plan_path": "maintenance/reviewed/",
        "controlled_write_path": "candidate-promotion-pr.yml",
        "post_promotion_maintenance": "source maintenance loop",
    }


def test_catalog_growth_scale_readiness_documents_source_health_dependency():
    plan = json.loads(SCALE_READINESS.read_text(encoding="utf-8"))
    dimensions = {item["dimension"]: item for item in plan["promotion_readiness_dimensions"]}

    assert "source_health_budget" in dimensions
    assert dimensions["source_health_budget"]["required_for_auto_queue"] is False
    assert any("catalog growth bypass source-health constraints" in guardrail for guardrail in plan["guardrails"])


def test_catalog_growth_docs_describe_staging_reviewed_and_curated_layers():
    text = CATALOG_GROWTH_DOC.read_text(encoding="utf-8")
    plan_text = SCALE_READINESS.read_text(encoding="utf-8")

    assert "seed files and discovery reports = staging input" in text
    assert "maintenance/reviewed/ = reviewed promotion evidence" in text
    assert "data/vendors/** = curated catalog" in text
    assert "coverage area" in text
    assert "source maintenance" in text
    assert "stage_model" in plan_text
