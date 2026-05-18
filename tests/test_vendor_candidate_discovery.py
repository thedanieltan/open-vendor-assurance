from tools.openva.vendor_candidate_discovery import (
    all_seed_paths,
    build_vendor_candidate_report,
    load_seed_file,
    validate_seed_identities,
)


def test_vendor_candidate_discovery_reports_non_canonical_candidates(tmp_path):
    queue = tmp_path / "maintenance/queues/catalog-growth-discovery.json"
    taxonomy = tmp_path / "config/category-taxonomy.yaml"
    seed = tmp_path / "maintenance/seeds/vendors/cloud_platforms.yaml"
    queue.parent.mkdir(parents=True, exist_ok=True)
    taxonomy.parent.mkdir(parents=True, exist_ok=True)
    seed.parent.mkdir(parents=True, exist_ok=True)
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
  "discovery_modes": ["seed_file_vendor_discovery"],
  "cohorts": [
    {"cohort_id": "cloud", "coverage_lane": "cloud_platforms", "target_vendor_candidates": 5, "priority": "high", "status": "queued"}
  ]
}
""",
        encoding="utf-8",
    )
    seed.write_text(
        """
- candidate_vendor_id: newvendor
  display_name_candidate: New Vendor
  official_domain_candidate: newvendor.test
  coverage_lane: cloud_platforms
  vendor_category_candidates:
    - cloud_infrastructure
  headquarters_country_candidate: US
  source_index_url: https://newvendor.test
  discovery_method: manual_seed
  requires_review: true
  writes_canonical_vendors: false
  non_advisory: true
""".lstrip(),
        encoding="utf-8",
    )

    report = build_vendor_candidate_report(queue_path=queue, root=tmp_path)
    candidate = report["vendor_candidates"][0]

    assert report["posture"]["network_fetch_performed"] is False
    assert report["posture"]["writes_canonical_vendors"] is False
    assert report["posture"]["writes_canonical_sources"] is False
    assert candidate["requires_review"] is True
    assert candidate["writes_canonical_vendors"] is False
    assert candidate["non_advisory"] is True
    assert candidate["official_domain_candidate"] == "newvendor.test"
    assert candidate["discovery_method"] == "manual_seed"
    assert candidate["vendor_category_candidates"] == ["cloud_infrastructure"]
    assert candidate["headquarters_country_candidate"] == "US"


def test_vendor_candidate_discovery_does_not_construct_google_queries(tmp_path):
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
  "discovery_modes": ["seed_file_vendor_discovery"],
  "cohorts": [
    {"cohort_id": "cloud", "coverage_lane": "cloud_platforms", "target_vendor_candidates": 5, "priority": "high", "status": "queued"}
  ]
}
""",
        encoding="utf-8",
    )

    report = build_vendor_candidate_report(queue_path=queue, root=tmp_path)

    assert report["summary"]["candidate_vendor_count"] == 0
    assert all("google.com/search" not in item.get("source_index_url", "") for item in report["vendor_candidates"])


def test_seed_identity_validation_checks_ids_domains_categories_and_countries(tmp_path):
    taxonomy = tmp_path / "config/category-taxonomy.yaml"
    seed = tmp_path / "maintenance/seeds/vendors/cloud_platforms.yaml"
    taxonomy.parent.mkdir(parents=True, exist_ok=True)
    seed.parent.mkdir(parents=True, exist_ok=True)
    taxonomy.write_text(
        """
vendor_categories:
  cloud_infrastructure: {}
coverage_lanes:
  cloud_platforms: {}
""",
        encoding="utf-8",
    )
    seed.write_text(
        """
- candidate_vendor_id: invalid id
  display_name_candidate: Bad Vendor
  official_domain_candidate: not a domain
  coverage_lane: unknown_lane
  vendor_category_candidates:
    - unknown_category
  headquarters_country_candidate: usa
  source_index_url: https://example.test
  discovery_method: manual_seed
  requires_review: false
  writes_canonical_vendors: true
  non_advisory: false
""".lstrip(),
        encoding="utf-8",
    )

    summary = validate_seed_identities(root=tmp_path)

    assert summary["seed_count"] == 1
    assert summary["failure_count"] >= 7
    assert any("candidate_vendor_id" in failure for failure in summary["failures"])
    assert any("official_domain_candidate" in failure for failure in summary["failures"])
    assert any("coverage_lane" in failure for failure in summary["failures"])
    assert any("vendor_category_candidates" in failure for failure in summary["failures"])
    assert any("headquarters_country_candidate" in failure for failure in summary["failures"])


def test_repository_seed_identity_corpus_has_balanced_valid_identities():
    summary = validate_seed_identities()

    assert summary["seed_count"] >= 200
    assert summary["failure_count"] == 0
    assert len(summary["coverage_lane_counts"]) >= 16
    assert min(summary["coverage_lane_counts"].values()) >= 10
    assert max(summary["coverage_lane_counts"].values()) / summary["seed_count"] <= 0.2
    assert len(summary["headquarters_country_counts"]) >= 25
    assert summary["headquarters_country_counts"]["US"] / summary["seed_count"] <= 0.55


def test_regional_apac_seed_identities_use_functional_category_tags():
    summary = validate_seed_identities()
    regional_seeds = [
        seed
        for path in all_seed_paths()
        if path.name == "regional_apac.yaml"
        for seed in load_seed_file(path)
    ]

    assert summary["coverage_lane_counts"]["regional_apac"] >= 10
    assert regional_seeds
    assert all(
        "regional_apac" not in seed["vendor_category_candidates"]
        for seed in regional_seeds
    )
