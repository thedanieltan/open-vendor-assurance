from __future__ import annotations

from pathlib import Path

from tools.openva.strict_growth_shortlist import (
    build_strict_growth_shortlist,
    promotion_plan_from_shortlist,
    write_outputs,
)


def action(
    vendor_id: str = "candidate-a",
    source_type: str = "security_page",
    source_id: str | None = None,
    verification_status: str = "ok",
) -> dict:
    candidate_source_id = source_id or f"{vendor_id}-{source_type.replace('_', '-')}-candidate"
    return {
        "action": "strict_catalog_growth_promotion_candidate",
        "vendor": {
            "candidate_vendor_id": vendor_id,
            "display_name_candidate": vendor_id.title(),
            "official_domain_candidate": f"{vendor_id}.example",
            "coverage_lane": "security",
            "cohort_id": "security-001",
            "vendor_category_candidates": ["security_software"],
            "headquarters_country_candidate": "US",
        },
        "source": {
            "candidate_source_id": candidate_source_id,
            "vendor_id": vendor_id,
            "source_type_candidate": source_type,
            "candidate_url": f"https://{vendor_id}.example/{source_type}",
            "confidence": "likely",
            "evidence": {
                "page_title": source_type.replace("_", " ").title(),
                "matched_terms": ["privacy" if source_type == "privacy_notice" else "security"],
                "final_url": f"https://{vendor_id}.example/{source_type}",
                "http_status": 200,
                "verification_status": verification_status,
            },
        },
    }


def item(vendor_id: str, classification: str = "strict_promote_ready", reason_codes=None) -> dict:
    return {
        "candidate_vendor_id": vendor_id,
        "display_name_candidate": vendor_id.title(),
        "official_domain_candidate": f"{vendor_id}.example",
        "coverage_lane": "security",
        "cohort_id": "security-001",
        "classification": classification,
        "reason_codes": reason_codes or ["strict_source_candidate_evidence_present"],
        "source_candidate_count": 1,
        "strict_source_count": 1 if classification == "strict_promote_ready" else 0,
        "promotable_now": classification == "strict_promote_ready",
    }


def eligibility_report(actions: list[dict], items: list[dict] | None = None) -> dict:
    if items is None:
        vendor_ids = sorted({row["vendor"]["candidate_vendor_id"] for row in actions})
        items = [item(vendor_id) for vendor_id in vendor_ids]
    return {
        "schema_version": "0.1.0",
        "report_type": "catalog_growth_eligibility_report",
        "generated_at": "2026-06-06T00:00:00Z",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "items": items,
        "strict_promotions": actions,
    }


def backlog_report() -> dict:
    return {
        "schema_version": "0.1.0",
        "report_type": "catalog_growth_backlog_report",
        "items": [],
    }


def test_shortlist_includes_only_strict_promote_ready_candidates():
    report = build_strict_growth_shortlist(
        eligibility_report(
            [action("candidate-a"), action("candidate-b")],
            items=[item("candidate-a"), item("candidate-b", "review_required", ["source_candidate_requires_review"])],
        ),
        backlog_report(),
    )

    assert [row["candidate_vendor_id"] for row in report["items"]] == ["candidate-a"]
    assert report["excluded"][0]["candidate_vendor_id"] == "candidate-b"
    assert report["excluded"][0]["classification"] == "review_required"


def test_shortlist_excludes_deferred_rejected_and_ambiguous_candidates():
    report = build_strict_growth_shortlist(
        eligibility_report(
            [action("candidate-a"), action("candidate-b"), action("candidate-c"), action("candidate-d")],
            items=[
                item("candidate-a"),
                item("candidate-b", "deferred", ["deferred"]),
                item("candidate-c", "rejected", ["rejected"]),
                item("candidate-d", "ambiguous", ["ambiguous"]),
            ],
        ),
        backlog_report(),
    )

    assert [row["candidate_vendor_id"] for row in report["items"]] == ["candidate-a"]
    assert {row["classification"] for row in report["excluded"]} >= {"deferred", "rejected", "ambiguous"}


def test_shortlist_excludes_source_preflight_risk_candidates():
    report = build_strict_growth_shortlist(
        eligibility_report([action("candidate-a", verification_status="homepage_or_generic_redirect")]),
        backlog_report(),
    )

    assert report["summary"]["shortlisted_action_count"] == 0
    assert report["excluded"][0]["reason_codes"] == [
        "source_preflight_risk:homepage_or_generic_redirect",
        "verification_status_not_strict_safe:homepage_or_generic_redirect",
    ]


def test_shortlist_preserves_eligibility_source_health_rejections():
    rejected = item("candidate-a", "strict_promote_ready")
    rejected["source_health_rejections"] = [
        {
            "candidate_source_id": "candidate-a-security-page-candidate",
            "source_type_candidate": "security_page",
            "candidate_url": "https://candidate-a.example/security",
            "classification": "reject_source_health_failure",
            "reason_codes": ["source_preflight_risk:homepage_or_generic_redirect"],
        }
    ]

    report = build_strict_growth_shortlist(
        eligibility_report([action("candidate-a", source_type="privacy_notice")], items=[rejected]),
        backlog_report(),
    )

    assert report["summary"]["shortlisted_action_count"] == 1
    assert report["excluded"][0]["candidate_source_id"] == "candidate-a-security-page-candidate"
    assert report["excluded"][0]["reason_codes"] == ["source_preflight_risk:homepage_or_generic_redirect"]


def test_shortlist_excludes_advisory_wording_candidates():
    risky = action("candidate-a")
    item_a = item("candidate-a", reason_codes=["strict_growth_advisory_wording_detected:safe"])
    report = build_strict_growth_shortlist(eligibility_report([risky], items=[item_a]), backlog_report())

    assert report["summary"]["shortlisted_action_count"] == 0
    assert report["excluded"][0]["reason_codes"] == ["strict_growth_advisory_wording_detected:safe"]


def test_shortlist_ranking_is_deterministic_and_respects_source_type_priority():
    rows = [
        action("candidate-b", "security_page"),
        action("candidate-a", "privacy_notice"),
        action("candidate-c", "dpa"),
    ]
    report = build_strict_growth_shortlist(eligibility_report(rows), backlog_report())

    assert [
        (row["rank"], row["candidate_vendor_id"], row["source_type_candidate"])
        for row in report["items"]
    ] == [
        (1, "candidate-c", "dpa"),
        (2, "candidate-a", "privacy_notice"),
        (3, "candidate-b", "security_page"),
    ]


def test_shortlist_respects_max_actions_and_preserves_excluded_reason():
    report = build_strict_growth_shortlist(
        eligibility_report([action("candidate-a", "privacy_notice"), action("candidate-b", "security_page")]),
        backlog_report(),
        max_actions=1,
    )

    assert report["summary"]["shortlisted_action_count"] == 1
    assert report["excluded"][0]["reason_codes"] == ["strict_growth_shortlist_max_actions_exceeded"]


def test_shortlist_excludes_candidates_without_sha_bound_evidence():
    eligibility = eligibility_report([action("candidate-a")])
    eligibility.pop("head_sha")

    report = build_strict_growth_shortlist(eligibility, backlog_report())

    assert report["summary"]["shortlisted_action_count"] == 0
    assert report["excluded"][0]["reason_codes"] == ["head_sha_missing"]


def test_promotion_plan_from_shortlist_uses_selected_batch_only():
    shortlist = build_strict_growth_shortlist(
        eligibility_report([action("candidate-a", "privacy_notice"), action("candidate-b", "security_page")]),
        backlog_report(),
    )

    plan = promotion_plan_from_shortlist(shortlist, max_actions=1)

    assert plan["summary"]["action_count"] == 1
    assert plan["summary"]["uncapped_action_count"] == 2
    assert plan["summary"]["batch_deferred_action_count"] == 1
    assert plan["actions"][0]["action"] == "strict_catalog_growth_promotion"


def test_max_actions_two_cannot_apply_five_shortlist_actions():
    rows = [action(f"candidate-{index}", "privacy_notice") for index in range(5)]
    shortlist = build_strict_growth_shortlist(eligibility_report(rows), backlog_report(), max_actions=5)

    plan = promotion_plan_from_shortlist(shortlist, max_actions=2)

    assert len(plan["actions"]) == 2
    assert plan["summary"]["batch_deferred_action_count"] == 3


def test_shortlist_writer_does_not_write_catalog_state(tmp_path: Path):
    report = build_strict_growth_shortlist(eligibility_report([action("candidate-a")]), backlog_report())

    write_outputs(
        report,
        tmp_path / "strict-growth-shortlist.json",
        tmp_path / "reports" / "strict-growth-shortlist.csv",
        tmp_path / "reports" / "strict-growth-shortlist-summary.md",
    )

    assert (tmp_path / "strict-growth-shortlist.json").is_file()
    assert (tmp_path / "reports" / "strict-growth-shortlist.csv").is_file()
    assert not (tmp_path / "data").exists()
