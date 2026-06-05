from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from tools.openva.automerge_lanes import load_policy
from tools.openva.strict_growth_automerge import check_strict_growth_eligibility, main

NOW = datetime(2026, 5, 27, 8, 0, tzinfo=UTC)
HEAD = "head-sha"
BASE = "base-sha"


def strict_action(candidate_vendor_id: str = "candidate-a", source_type: str = "security_page") -> dict:
    return {
        "action": "strict_catalog_growth_promotion",
        "vendor": {
            "candidate_vendor_id": candidate_vendor_id,
            "display_name_candidate": "Candidate A",
            "official_domain_candidate": "candidate-a.example",
        },
        "source": {
            "candidate_source_id": f"{candidate_vendor_id}-{source_type}-candidate",
            "source_type_candidate": source_type,
            "candidate_url": f"https://{candidate_vendor_id}.example/security",
            "evidence": {
                "page_title": source_type.replace("_", " ").title(),
                "matched_terms": [source_type],
                "final_url": f"https://{candidate_vendor_id}.example/security",
                "http_status": 200,
            },
        },
        "requires_human_review": False,
        "strict_machine_candidate": True,
        "non_advisory": True,
    }


def promotion_plan(*actions: dict, generated_at: str = "2026-05-27T07:00:00Z") -> dict:
    return {
        "report_type": "candidate_promotion_plan",
        "generated_at": generated_at,
        "head_sha": HEAD,
        "base_sha": BASE,
        "actions": list(actions or [strict_action()]),
    }


def eligibility_report(generated_at: str = "2026-05-27T07:00:00Z") -> dict:
    return {
        "report_type": "catalog_growth_eligibility_report",
        "generated_at": generated_at,
        "head_sha": HEAD,
        "base_sha": BASE,
    }


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def eligible_result(**overrides):
    kwargs = {
        "promotion_plan": promotion_plan(strict_action()),
        "eligibility_report": eligibility_report(),
        "labels": ["catalog-growth", "automerge:strict-growth"],
        "current_head_sha": HEAD,
        "recorded_head_sha": None,
        "current_base_sha": BASE,
        "recorded_base_sha": None,
        "now": NOW,
        "policy": load_policy(),
    }
    kwargs.update(overrides)
    return check_strict_growth_eligibility(**kwargs)


def test_strict_growth_eligible_when_all_required_evidence_is_current():
    result = eligible_result()

    assert result.eligible is True
    assert result.lane == "automerge:strict-growth"
    assert result.report_only is False
    assert result.reasons == ()


def test_head_sha_mismatch_hard_fails():
    result = eligible_result(recorded_head_sha="stale-head-sha")

    assert result.eligible is False
    assert "head_sha_mismatch" in result.reasons


def test_missing_recorded_head_sha_hard_fails_without_key_error():
    plan = promotion_plan(strict_action())
    plan.pop("head_sha")
    report = eligibility_report()
    report.pop("head_sha")

    result = eligible_result(promotion_plan=plan, eligibility_report=report)

    assert result.eligible is False
    assert "recorded_head_sha_missing" in result.reasons


def test_missing_recorded_base_sha_hard_fails_without_key_error():
    plan = promotion_plan(strict_action())
    plan.pop("base_sha")
    report = eligibility_report()
    report.pop("base_sha")

    result = eligible_result(promotion_plan=plan, eligibility_report=report)

    assert result.eligible is False
    assert "recorded_base_sha_missing" in result.reasons


def test_expired_evidence_hard_fails_after_four_hours():
    old_report = eligibility_report(generated_at="2026-05-27T03:59:59Z")

    result = eligible_result(eligibility_report=old_report)

    assert result.eligible is False
    assert "evidence_timestamp_expired" in result.reasons


def test_strict_machine_candidate_missing_fails_entire_pr():
    action = strict_action()
    del action["strict_machine_candidate"]

    result = eligible_result(promotion_plan=promotion_plan(action))

    assert result.eligible is False
    assert (
        "strict_machine_candidate_missing:candidate-a:security_page:candidate-a-security_page-candidate"
        in result.reasons
    )


def test_strict_machine_candidate_false_fails_entire_pr():
    action = strict_action()
    action["strict_machine_candidate"] = False

    result = eligible_result(promotion_plan=promotion_plan(action))

    assert result.eligible is False
    assert (
        "strict_machine_candidate_false:candidate-a:security_page:candidate-a-security_page-candidate"
        in result.reasons
    )


def test_strict_machine_candidate_not_boolean_fails_entire_pr():
    action = strict_action()
    action["strict_machine_candidate"] = "true"

    result = eligible_result(promotion_plan=promotion_plan(action))

    assert result.eligible is False
    assert (
        "strict_machine_candidate_not_boolean:candidate-a:security_page:candidate-a-security_page-candidate"
        in result.reasons
    )


def test_missing_inference_mode_fails_closed_for_relationship_record():
    action = strict_action()
    action["relationships"] = [
        {
            "relationship_type": "vendor_stated_terms_publisher",
            "attestation_mode": "source_attested",
            "evidence_url": "https://candidate-a.example/terms",
            "source_id": "candidate-a-terms",
        }
    ]

    result = eligible_result(promotion_plan=promotion_plan(action))

    assert result.eligible is False
    assert (
        "inference_mode_missing:candidate-a:security_page:candidate-a-security_page-candidate"
        in result.reasons
    )


def test_blocked_inference_mode_wins_over_allowed_attestation():
    action = strict_action()
    action["relationships"] = [
        {
            "relationship_type": "vendor_stated_terms_publisher",
            "attestation_mode": "source_attested",
            "inference_mode": "domain_similarity",
            "evidence_url": "https://candidate-a.example/terms",
            "source_id": "candidate-a-terms",
        }
    ]

    result = eligible_result(promotion_plan=promotion_plan(action))

    assert result.eligible is False
    assert (
        "blocked_inference_mode:domain_similarity:candidate-a:security_page:candidate-a-security_page-candidate"
        in result.reasons
    )


def test_base_sha_mismatch_warns_but_does_not_hard_fail():
    result = eligible_result(recorded_base_sha="older-base-sha")

    assert result.eligible is True
    assert "base_sha_mismatch_warning" in result.reasons


def test_report_only_policy_cannot_enable_merge_authority():
    policy = deepcopy(load_policy())
    policy["mode"] = "report_only"

    result = eligible_result(policy=policy)

    assert result.eligible is False
    assert result.report_only is True
    assert "report_only_not_merge_authority" in result.reasons


def test_missing_required_label_fails_even_with_strict_machine_candidate():
    result = eligible_result(labels=["automerge:strict-growth"])

    assert result.eligible is False
    assert "required_label_missing:catalog-growth" in result.reasons


def test_non_core_source_type_fails():
    action = strict_action(source_type="ai_terms")

    result = eligible_result(promotion_plan=promotion_plan(action))

    assert result.eligible is False
    assert "non_core_source_type:ai_terms:candidate-a:ai_terms:candidate-a-ai_terms-candidate" in result.reasons


def test_advisory_wording_in_strict_growth_plan_fails_preflight():
    action = strict_action()
    action["source"]["evidence"]["page_title"] = "Cloud Security | How Candidate A Keeps Your Data Safe"

    result = eligible_result(promotion_plan=promotion_plan(action))

    assert result.eligible is False
    assert (
        "strict_growth_advisory_wording_detected:safe:candidate-a:security_page:candidate-a-security_page-candidate"
        in result.reasons
    )


def test_more_than_five_new_vendors_fails():
    actions = [strict_action(candidate_vendor_id=f"candidate-{index}") for index in range(6)]

    result = eligible_result(promotion_plan=promotion_plan(*actions))

    assert result.eligible is False
    assert "new_vendor_limit_exceeded:6>5" in result.reasons


def test_more_than_two_sources_for_one_vendor_fails():
    action_a = strict_action(source_type="security_page")
    action_b = strict_action(source_type="privacy_notice")
    action_c = strict_action(source_type="dpa")

    result = eligible_result(promotion_plan=promotion_plan(action_a, action_b, action_c))

    assert result.eligible is False
    assert "vendor_source_limit_exceeded:candidate-a:3>2" in result.reasons


def test_check_plan_cli_rejects_over_cap_plan(tmp_path):
    plan_path = write_json(
        tmp_path / "strict-growth-promotion-plan.json",
        promotion_plan(
            strict_action(source_type="security_page"),
            strict_action(source_type="privacy_notice"),
            strict_action(source_type="dpa"),
        ),
    )
    eligibility_path = write_json(tmp_path / "eligibility-report.json", eligibility_report())

    assert main(
        [
            "check-plan",
            "--promotion-plan",
            str(plan_path),
            "--eligibility-report",
            str(eligibility_path),
            "--labels",
            "catalog-growth,automerge:strict-growth",
            "--current-head-sha",
            HEAD,
            "--current-base-sha",
            BASE,
            "--now",
            "2026-05-27T08:00:00Z",
        ]
    ) == 1


def test_check_plan_cli_rejects_advisory_wording_plan(tmp_path):
    action = strict_action()
    action["source"]["evidence"]["page_title"] = "Cloud Security | How Candidate A Keeps Your Data Safe"
    plan_path = write_json(tmp_path / "strict-growth-promotion-plan.json", promotion_plan(action))
    eligibility_path = write_json(tmp_path / "eligibility-report.json", eligibility_report())

    assert main(
        [
            "check-plan",
            "--promotion-plan",
            str(plan_path),
            "--eligibility-report",
            str(eligibility_path),
            "--labels",
            "catalog-growth,automerge:strict-growth",
            "--current-head-sha",
            HEAD,
            "--current-base-sha",
            BASE,
            "--now",
            "2026-05-27T08:00:00Z",
        ]
    ) == 1


def test_promotion_plan_timestamp_after_eligibility_report_matches_regeneration_order():
    result = eligible_result(
        promotion_plan=promotion_plan(strict_action(), generated_at="2026-05-27T07:10:00Z"),
        eligibility_report=eligibility_report(generated_at="2026-05-27T07:00:00Z"),
    )

    assert result.eligible is True
    assert result.reasons == ()


def test_fallback_to_promotion_plan_timestamp_is_reported_when_eligibility_report_absent():
    result = eligible_result(eligibility_report=None)

    assert result.eligible is True
    assert "eligibility_report_missing_used_promotion_plan_timestamp" in result.reasons
