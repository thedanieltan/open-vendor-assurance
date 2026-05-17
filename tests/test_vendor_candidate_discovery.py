from tools.openva.source_verification import FetchResult
from tools.openva.vendor_candidate_discovery import build_vendor_candidate_report


def fetcher(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        http_status=200,
        content_type="text/html",
        body_sample='<html><head><title>Example Index</title></head><body><a href="https://newvendor.test">New Vendor</a></body></html>',
        error=None,
    )


def test_vendor_candidate_discovery_reports_non_canonical_candidates(tmp_path):
    queue = tmp_path / "maintenance/queues/catalog-growth-discovery.json"
    taxonomy = tmp_path / "config/category-taxonomy.yaml"
    queue.parent.mkdir(parents=True, exist_ok=True)
    taxonomy.parent.mkdir(parents=True, exist_ok=True)
    taxonomy.write_text(
        """
coverage_lanes:
  cloud_platforms: {}
artifact_categories:
  data_processing_terms:
    maps_to_artifact_types: [dpa]
""",
        encoding="utf-8",
    )
    queue.write_text(
        """
{
  "schema_version": "0.1.0",
  "queue_type": "catalog_growth_discovery_queue",
  "non_advisory": true,
  "posture": {
    "network_fetch_performed": false,
    "writes_repository_state": false,
    "writes_canonical_sources": false,
    "creates_candidate_sources": false
  },
  "limits": {
    "target_vendor_candidates": 10,
    "max_vendors_per_discovery_run": 5,
    "max_candidate_sources_per_report": 10,
    "max_reviewed_actions_per_plan": 5
  },
  "source_types": ["dpa"],
  "discovery_modes": ["public_index_vendor_discovery"],
  "cohorts": [
    {"cohort_id": "cloud", "coverage_lane": "cloud_platforms", "target_vendor_candidates": 5, "priority": "high", "status": "queued"}
  ]
}
""",
        encoding="utf-8",
    )

    report = build_vendor_candidate_report(queue_path=queue, root=tmp_path, fetcher=fetcher)
    candidate = report["vendor_candidates"][0]

    assert report["posture"]["writes_canonical_vendors"] is False
    assert report["posture"]["writes_canonical_sources"] is False
    assert candidate["requires_review"] is True
    assert candidate["writes_canonical_vendors"] is False
    assert candidate["non_advisory"] is True
    assert candidate["official_domain_candidate"] == "newvendor.test"
