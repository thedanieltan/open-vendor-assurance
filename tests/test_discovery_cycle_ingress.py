from __future__ import annotations

from tools.openva import candidate_record, vendor_resolution
from tools.openva.discovery_cycle_ingress import project_discovery_candidates


def vendor_report(*, country: str = "GB") -> dict:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-08-26T00:00:00Z",
        "report_type": "vendor_candidate_discovery_report",
        "vendor_candidates": [
            {
                "candidate_vendor_id": "ably",
                "display_name_candidate": "Ably",
                "official_domain_candidate": "ably.com",
                "headquarters_country_candidate": country,
                "coverage_lane": "signal_mesh",
                "cohort_id": "provider-replenishment",
                "requires_review": True,
                "writes_canonical_vendors": False,
                "non_advisory": True,
            }
        ],
    }


def source_report(source_type: str = "dpa", *, verification: str = "ok") -> dict:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-08-26T00:00:01Z",
        "report_type": "source_discovery_report",
        "discovery_context": "vendor_candidate_source_discovery",
        "vendors": [
            {
                "vendor_id": "ably",
                "candidate_vendor_id": "ably",
                "candidates": [
                    {
                        "candidate_source_id": f"ably-{source_type}-candidate",
                        "vendor_id": "ably",
                        "source_type_candidate": source_type,
                        "candidate_url": f"https://ably.com/{source_type}",
                        "confidence": "likely",
                        "requires_review": True,
                        "discovered_at": "2026-08-26T00:00:01Z",
                        "discovery_method": "official_domain_crawl",
                        "not_advice": True,
                        "evidence": {
                            "http_status": 200,
                            "content_type": "text/html",
                            "final_url": f"https://ably.com/{source_type}",
                            "verification_status": verification,
                            "semantic_status": "strong",
                            "matched_terms": ["data processing"],
                        },
                    }
                ],
            }
        ],
    }


def test_public_materialization_source_projects_to_eligible_unified_candidate() -> None:
    ingress = vendor_resolution.RecordingIngress()
    result = project_discovery_candidates(vendor_report(), source_report(), ingress=ingress)
    assert result["summary"]["eligible_count"] == 1
    record = next(iter(ingress.records.values()))
    assert record["candidate_origin"] == "catalog_discovery"
    assert record["eligibility_state"] == candidate_record.ELIGIBLE_STATE
    assert record["vendor_identity_candidate"]["headquarters_country"] == "GB"
    assert record["source_candidates"][0]["source_role"] == "primary_assurance"
    assert record["source_candidates"][0]["access_state"] == "public_reachable"
    assert candidate_record.validate_candidate(record) == []


def test_missing_source_is_persistable_deferred_state() -> None:
    ingress = vendor_resolution.RecordingIngress()
    empty_sources = source_report()
    empty_sources["vendors"][0]["candidates"] = []
    result = project_discovery_candidates(vendor_report(), empty_sources, ingress=ingress)
    assert result["summary"]["state_counts"] == {"deferred_insufficient_evidence": 1}
    record = next(iter(ingress.records.values()))
    assert record["source_candidates"] == []


def test_non_materialization_source_does_not_make_vendor_eligible() -> None:
    ingress = vendor_resolution.RecordingIngress()
    result = project_discovery_candidates(vendor_report(), source_report("status_page"), ingress=ingress)
    assert result["summary"]["eligible_count"] == 0
    record = next(iter(ingress.records.values()))
    assert record["source_candidates"][0]["source_role"] == "rejected"
    assert record["eligibility_state"] == "deferred_insufficient_evidence"


def test_incomplete_country_stays_in_breadth_resolution_instead_of_poisoning_candidate_base() -> None:
    ingress = vendor_resolution.RecordingIngress()
    result = project_discovery_candidates(vendor_report(country=""), source_report(), ingress=ingress)
    assert result["summary"]["candidate_count"] == 0
    assert result["skipped"] == [{"vendor_id": "ably", "reason": "headquarters_country_not_ready"}]
    assert ingress.records == {}


def test_repeated_discovery_uses_stable_candidate_identity_and_merges_new_source() -> None:
    ingress = vendor_resolution.RecordingIngress()
    first = project_discovery_candidates(vendor_report(), source_report("dpa"), ingress=ingress)
    second = project_discovery_candidates(vendor_report(), source_report("privacy_notice"), ingress=ingress)
    assert first["candidates"][0]["candidate_id"] == second["candidates"][0]["candidate_id"]
    assert len(ingress.records) == 1
    record = next(iter(ingress.records.values()))
    assert {row["source_type_candidate"] for row in record["source_candidates"]} == {"dpa", "privacy_notice"}
    assert record["eligibility_state"] == "eligible"
