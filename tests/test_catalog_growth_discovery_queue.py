import json
from pathlib import Path

import pytest

from tools.openva.catalog_growth_discovery_queue import validate_queue


QUEUE = Path("maintenance/queues/catalog-growth-discovery.json")


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
