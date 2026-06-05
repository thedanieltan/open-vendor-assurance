import json
from copy import deepcopy
from pathlib import Path

import yaml

from tools.openva.promotion_planner import build_promotion_plan, build_strict_growth_plan


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def vendor(vendor_id: str = "example") -> dict:
    return {
        "schema_version": "0.1.0",
        "vendor_id": vendor_id,
        "display_name": "Example",
        "legal_name": "Example Inc.",
        "headquarters_country": "US",
        "official_domains": ["example.com"],
        "source_policy": {
            "public_sources_only": True,
            "gated_materials_excluded": True,
            "raw_documents_mirrored_by_default": False,
        },
        "status": "active",
    }


def source(vendor_id: str = "example", source_type: str = "dpa") -> dict:
    return {
        "schema_version": "0.1.0",
        "source_id": f"{vendor_id}-{source_type.replace('_', '-')}",
        "vendor_id": vendor_id,
        "source_type": source_type,
        "title_native": "Example DPA",
        "source_url": "https://example.com/legal/dpa",
        "source_language": "en",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "vendor",
            "collected_at": "2026-05-16T00:00:00Z",
            "observer": "human",
            "confidence": "medium",
        },
        "not_advice": True,
    }


def candidate(vendor_id: str = "example", source_type: str = "dpa", confidence: str = "likely") -> dict:
    return {
        "schema_version": "0.1.0",
        "candidate_source_id": f"{vendor_id}-{source_type.replace('_', '-')}-candidate",
        "vendor_id": vendor_id,
        "source_type_candidate": source_type,
        "candidate_url": "https://example.com/legal/data-processing-addendum",
        "discovery_method": "official_domain_crawl",
        "confidence": confidence,
        "requires_review": True,
        "discovered_at": "2026-05-16T00:00:00Z",
        "discovered_by": "agent",
        "evidence": {
            "page_title": "Data Processing Addendum",
            "matched_terms": ["data processing", "processor"],
            "final_url": "https://example.com/legal/data-processing-addendum",
            "http_status": 200,
            "content_type": "text/html",
        },
        "not_advice": True,
    }


def unavailable(vendor_id: str = "example", source_type: str = "subprocessors_list") -> dict:
    return {
        "schema_version": "0.1.0",
        "unavailable_source_id": f"{vendor_id}-{source_type.replace('_', '-')}",
        "vendor_id": vendor_id,
        "source_type": source_type,
        "status": "not_identified",
        "reason": "distinct_public_url_not_identified",
        "reviewed_at": "2026-05-16T00:00:00Z",
        "reviewed_by": "agent",
        "next_review_after": "2026-08-16",
        "candidate_urls_checked": ["https://example.com/legal/subprocessors"],
        "not_advice": True,
    }


def strict_eligibility_report() -> dict:
    return {
        "schema_version": "0.1.0",
        "report_type": "catalog_growth_eligibility_report",
        "items": [
            {
                "candidate_vendor_id": "candidate-a",
                "classification": "strict_promote_ready",
                "reason_codes": ["strict_source_candidate_evidence_present"],
            }
        ],
        "strict_promotions": [
            {
                "action": "strict_catalog_growth_promotion_candidate",
                "vendor": {
                    "candidate_vendor_id": "candidate-a",
                    "display_name_candidate": "Candidate A",
                    "official_domain_candidate": "candidate-a.example",
                    "coverage_lane": "security",
                    "cohort_id": "security-001",
                    "vendor_category_candidates": ["security_software"],
                    "headquarters_country_candidate": "US",
                },
                "source": {
                    "candidate_source_id": "candidate-a-security-page-candidate",
                    "vendor_id": "candidate-a",
                    "source_type_candidate": "security_page",
                    "candidate_url": "https://candidate-a.example/security",
                    "confidence": "likely",
                    "evidence": {
                        "page_title": "Security",
                        "matched_terms": ["security", "encryption"],
                        "final_url": "https://candidate-a.example/security",
                        "http_status": 200,
                        "content_type": "text/html",
                    },
                },
                "posture": {
                    "network_fetch_performed": False,
                    "writes_repository_state": False,
                    "writes_canonical_sources": False,
                    "strict_machine_candidate": True,
                    "non_advisory": True,
                },
            }
        ],
    }


def test_planner_promotes_likely_candidate_for_review(tmp_path):
    write_yaml(tmp_path / "data/vendors/example/vendor.yaml", vendor())
    write_yaml(tmp_path / "data/vendors/example/candidate_sources/example-dpa-candidate.yaml", candidate())

    plan = build_promotion_plan(root=tmp_path)

    assert plan["posture"]["writes_repository_state"] is False
    assert plan["posture"]["writes_canonical_sources"] is False
    assert plan["summary"]["action_types"] == {"promote_candidate_source_for_review": 1}
    action = plan["actions"][0]
    assert action["candidate_source_id"] == "example-dpa-candidate"
    assert action["requires_human_review"] is True
    assert action["writes_canonical_sources"] is False
    assert action["non_advisory"] is True


def test_planner_keeps_unavailable_source_until_next_review(tmp_path):
    write_yaml(tmp_path / "data/vendors/example/vendor.yaml", vendor())
    write_yaml(
        tmp_path / "data/vendors/example/unavailable_sources/example-subprocessors-list.yaml",
        unavailable(),
    )

    plan = build_promotion_plan(root=tmp_path)

    assert plan["summary"]["action_types"] == {"keep_unavailable_until_next_review": 1}
    action = plan["actions"][0]
    assert action["next_review_after"] == "2026-08-16"
    assert action["requires_human_review"] is False


def test_planner_detects_unavailable_conflict_with_existing_source(tmp_path):
    write_yaml(tmp_path / "data/vendors/example/vendor.yaml", vendor())
    write_yaml(tmp_path / "data/vendors/example/sources/example-subprocessors-list.yaml", source(source_type="subprocessors_list"))
    write_yaml(
        tmp_path / "data/vendors/example/unavailable_sources/example-subprocessors-list.yaml",
        unavailable(),
    )

    plan = build_promotion_plan(root=tmp_path)

    assert plan["summary"]["action_types"] == {"review_unavailable_conflict": 1}
    assert plan["actions"][0]["requires_human_review"] is True


def test_planner_recommends_cleanup_from_verification_report(tmp_path):
    write_yaml(tmp_path / "data/vendors/example/vendor.yaml", vendor())
    write_yaml(tmp_path / "data/vendors/example/sources/example-dpa.yaml", source())
    verification_report = {
        "sources": [
            {
                "vendor_id": "example",
                "source_id": "example-dpa",
                "verification_status": "suspect_inferred_url",
                "http_status": 200,
                "final_url": "https://example.com/legal/data-processing-addendum",
                "title_detected": "Example",
                "semantic_match": {"status": "weak", "matched_terms": ["data processing"]},
            }
        ]
    }
    report_path = tmp_path / "source-verification-report.json"
    report_path.write_text(json.dumps(verification_report), encoding="utf-8")

    plan = build_promotion_plan(root=tmp_path, verification_report_path=report_path)

    assert plan["summary"]["action_types"] == {"cleanup_source_for_review": 1}
    action = plan["actions"][0]
    assert action["source_id"] == "example-dpa"
    assert action["verification"]["verification_status"] == "suspect_inferred_url"


def test_planner_recommends_retire_or_replace_for_gone_source(tmp_path):
    write_yaml(tmp_path / "data/vendors/example/vendor.yaml", vendor())
    write_yaml(tmp_path / "data/vendors/example/sources/example-dpa.yaml", source())
    verification_report = {
        "sources": [
            {
                "vendor_id": "example",
                "source_id": "example-dpa",
                "verification_status": "gone",
                "http_status": 410,
                "final_url": "https://example.com/legal/dpa",
                "title_detected": None,
                "semantic_match": {"status": "mismatch", "matched_terms": []},
            }
        ]
    }
    report_path = tmp_path / "source-verification-report.json"
    report_path.write_text(json.dumps(verification_report), encoding="utf-8")

    plan = build_promotion_plan(root=tmp_path, verification_report_path=report_path)

    assert plan["summary"]["action_types"] == {"retire_or_replace_source_for_review": 1}
    assert plan["actions"][0]["requires_human_review"] is True


def test_planner_does_not_emit_action_for_ok_existing_source(tmp_path):
    write_yaml(tmp_path / "data/vendors/example/vendor.yaml", vendor())
    write_yaml(tmp_path / "data/vendors/example/sources/example-dpa.yaml", source())
    verification_report = {
        "sources": [
            {
                "vendor_id": "example",
                "source_id": "example-dpa",
                "verification_status": "ok",
                "http_status": 200,
                "semantic_match": {"status": "strong", "matched_terms": ["data processing", "processor"]},
            }
        ]
    }
    report_path = tmp_path / "source-verification-report.json"
    report_path.write_text(json.dumps(verification_report), encoding="utf-8")

    plan = build_promotion_plan(root=tmp_path, verification_report_path=report_path)

    assert plan["summary"]["action_count"] == 0
    assert plan["actions"] == []


def test_strict_growth_planner_uses_only_strict_promote_ready_records():
    report = strict_eligibility_report()
    report["items"].append({"candidate_vendor_id": "candidate-b", "classification": "reject_no_public_source"})
    report["strict_promotions"].append(
        {
            "vendor": {"candidate_vendor_id": "candidate-b"},
            "source": {"candidate_url": "https://candidate-b.example/security"},
        }
    )

    plan = build_strict_growth_plan(report)

    assert plan["report_type"] == "strict_growth_promotion_plan"
    assert plan["summary"]["action_types"] == {"strict_catalog_growth_promotion": 1}
    action = plan["actions"][0]
    assert action["vendor"]["candidate_vendor_id"] == "candidate-a"
    assert action["requires_human_review"] is False
    assert action["writes_canonical_vendors"] is False
    assert action["writes_canonical_sources"] is False
    assert action["strict_machine_candidate"] is True


def test_strict_growth_planner_caps_sources_by_deterministic_priority():
    report = strict_eligibility_report()
    base_action = report["strict_promotions"][0]
    dpa = deepcopy(base_action)
    dpa["source"]["candidate_source_id"] = "candidate-a-dpa-candidate"
    dpa["source"]["source_type_candidate"] = "dpa"
    dpa["source"]["candidate_url"] = "https://candidate-a.example/dpa"
    dpa["source"]["evidence"]["page_title"] = "Data Processing Addendum"
    privacy = deepcopy(base_action)
    privacy["source"]["candidate_source_id"] = "candidate-a-privacy-notice-candidate"
    privacy["source"]["source_type_candidate"] = "privacy_notice"
    privacy["source"]["candidate_url"] = "https://candidate-a.example/privacy"
    privacy["source"]["evidence"]["page_title"] = "Privacy Notice"
    security = deepcopy(base_action)
    security["source"]["candidate_source_id"] = "candidate-a-security-page-candidate"
    security["source"]["source_type_candidate"] = "security_page"
    security["source"]["candidate_url"] = "https://candidate-a.example/security"
    security["source"]["evidence"]["page_title"] = "Security"
    report["strict_promotions"] = [security, privacy, dpa]

    plan = build_strict_growth_plan(report)

    assert [action["source"]["source_type_candidate"] for action in plan["actions"]] == [
        "dpa",
        "privacy_notice",
    ]
    assert plan["summary"]["action_count"] == 2
    assert plan["summary"]["deferred_action_count"] == 1
    assert plan["deferred_actions"][0]["reason_codes"] == ["strict_growth_vendor_source_cap_exceeded"]
    assert plan["deferred_actions"][0]["action"]["source"]["source_type_candidate"] == "security_page"
