from tools.openva.automerge_lanes import load_policy
from tools.openva.catalog_growth_backlog import build_catalog_growth_backlog, evidence_hash_for


def eligibility_report():
    return {
        "report_type": "catalog_growth_eligibility_report",
        "generated_at": "2026-05-27T08:00:00Z",
        "items": [
            {
                "candidate_vendor_id": "candidate-a",
                "display_name_candidate": "Candidate A",
                "official_domain_candidate": "candidate-a.example",
                "coverage_lane": "security",
                "cohort_id": "security-001",
                "classification": "strict_promote_ready",
                "reason_codes": ["strict_source_candidate_evidence_present"],
                "source_candidate_count": 2,
                "strict_source_count": 1,
            },
            {
                "candidate_vendor_id": "candidate-b",
                "display_name_candidate": "Candidate B",
                "official_domain_candidate": "candidate-b.example",
                "coverage_lane": "privacy",
                "cohort_id": "privacy-001",
                "classification": "review_required",
                "reason_codes": ["source_candidate_requires_review"],
                "source_candidate_count": 1,
                "strict_source_count": 0,
            },
            {
                "candidate_vendor_id": "candidate-c",
                "display_name_candidate": "Candidate C",
                "official_domain_candidate": "candidate-c.example",
                "coverage_lane": "security",
                "cohort_id": "security-001",
                "classification": "reject_duplicate",
                "reason_codes": ["duplicate_candidate_domain"],
                "source_candidate_count": 1,
                "strict_source_count": 0,
            },
        ],
    }


def test_catalog_growth_backlog_maps_eligibility_to_operational_states():
    report = build_catalog_growth_backlog(eligibility_report(), generated_at="2026-05-27T08:00:00Z")

    assert report["report_type"] == "catalog_growth_backlog_report"
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "writes_canonical_vendors": False,
        "writes_canonical_sources": False,
        "opens_pull_requests": False,
        "non_advisory": True,
    }
    assert report["summary"] == {
        "candidate_count": 3,
        "backlog_state_counts": {
            "human_review_required": 1,
            "rejected": 1,
            "strict_pr_candidate": 1,
        },
        "strict_pr_candidate_count": 1,
        "human_review_required_count": 1,
        "rejected_count": 1,
    }


def test_catalog_growth_backlog_uses_configured_refresh_policies():
    report = build_catalog_growth_backlog(eligibility_report(), policy=load_policy(), generated_at="2026-05-27T08:00:00Z")
    by_candidate = {item["candidate_vendor_id"]: item for item in report["items"]}

    assert by_candidate["candidate-a"]["refresh_policy"] == "expires_after:21d/3cycles"
    assert by_candidate["candidate-b"]["refresh_policy"] == "refresh_after:42d/6cycles"
    assert by_candidate["candidate-c"]["refresh_policy"] == "suppress_rediscovery:90d"


def test_catalog_growth_backlog_evidence_hash_changes_when_evidence_changes():
    item = eligibility_report()["items"][0]
    changed = dict(item)
    changed["reason_codes"] = ["different_reason"]

    assert evidence_hash_for(item) != evidence_hash_for(changed)


def test_catalog_growth_backlog_rejects_wrong_report_type():
    import pytest

    with pytest.raises(ValueError, match="expected catalog_growth_eligibility_report"):
        build_catalog_growth_backlog({"report_type": "wrong"})
