"""WP37 independent bot quorum tests.

Covers each reviewer's clear/challenge behaviour, the adversarial default of
CHALLENGE, and EVERY prohibited self-approval combination (discovery == deciding,
deciding as sole supporter, and identical modules not counting as independent
reviewers).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tools.openva import bot_quorum as q

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
OBSERVED_AT = "2026-06-12T00:00:00Z"

THRESHOLDS = {
    "min_useful_source_roles": 2,
    "min_independent_supporting_modules": 2,
    "promotion_not_before_delay_hours": 48,
    "required_score": 1.0,
}


def healthy_event(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "vendor_id": "newco",
        "event_type": "first_observed",
        "change_class": "none",
        "observed_at": OBSERVED_AT,
        "source_health_status": "ok",
        "review_signal": {"required": False, "reason": "first_observation"},
    }


def clean_subject(**overrides) -> q.PromotionSubject:
    sources = [
        {"source_id": "newco-privacy", "source_type": "privacy_notice", "source_url": "https://newco.com/privacy", "title_native": "NewCo Privacy"},
        {"source_id": "newco-security", "source_type": "security_page", "source_url": "https://newco.com/security", "title_native": "NewCo Security"},
    ]
    kwargs = dict(
        vendor={
            "vendor_id": "newco",
            "display_name": "NewCo",
            "catalog_status": "machine_provisional",
            "official_domains": ["newco.com"],
            "public_entrypoints": ["https://newco.com"],
            "reversal": {"method": "remove", "reference": "revert the materialization PR", "reversal_decision_id": None},
            "notes": "Machine-provisional catalog growth vendor.",
        },
        sources=sources,
        events=[healthy_event("newco-privacy"), healthy_event("newco-security")],
        materialization_decision={
            "decision_id": "newco-vendor-materialization",
            "decision": "materialize_provisional",
            "deciding_bot": "strict-growth-materializer",
            "discovery_bot": "catalog-growth-discovery",
        },
        other_vendor_domains={"other.com"},
        other_vendor_names={"other co"},
        match_index_items=[{"vendor_id": "other", "official_domains": ["other.com"], "display_name": "Other Co"}],
        now=NOW,
        thresholds=THRESHOLDS,
    )
    kwargs.update(overrides)
    return q.PromotionSubject(**kwargs)


# --------------------------------------------------------------------------- #
# Reviewers
# --------------------------------------------------------------------------- #
def test_identity_resolver_clears_unique_vendor_and_challenges_collision():
    assert q.review_identity(clean_subject()).cleared
    colliding = clean_subject(other_vendor_domains={"newco.com"})
    verdict = q.review_identity(colliding)
    assert not verdict.cleared
    assert any("identity_collision:domain:newco.com" in r for r in verdict.reasons)


def test_identity_resolver_challenges_name_collision():
    verdict = q.review_identity(clean_subject(other_vendor_names={"newco"}))
    assert not verdict.cleared
    assert any("identity_collision:name:newco" in r for r in verdict.reasons)


def test_domain_authority_challenges_offsite_source():
    subject = clean_subject()
    subject.sources[0]["source_url"] = "https://evilcdn.example/newco/privacy"
    verdict = q.review_domain_authority(subject)
    assert not verdict.cleared
    assert any("source_host_outside_authority" in r for r in verdict.reasons)


def test_source_verifier_requires_two_useful_roles():
    one_role = clean_subject(sources=[{"source_id": "newco-privacy", "source_type": "privacy_notice", "source_url": "https://newco.com/privacy"}],
                             events=[healthy_event("newco-privacy")])
    verdict = q.review_sources(one_role)
    assert not verdict.cleared
    assert any("insufficient_useful_source_roles" in r for r in verdict.reasons)


def test_source_verifier_challenges_unavailable_source():
    subject = clean_subject()
    subject.events[0]["source_health_status"] = "unreachable"
    verdict = q.review_sources(subject)
    assert not verdict.cleared
    assert any("source_unavailable:newco-privacy" in r for r in verdict.reasons)


def test_duplicate_reviewer_flags_shared_domain_and_fuzzy_name():
    dup = clean_subject(match_index_items=[{"vendor_id": "newco-eu", "official_domains": ["newco.com"], "display_name": "NewCo"}])
    verdict = q.review_duplicates(dup)
    assert not verdict.cleared
    assert any("duplicate_domain:newco.com" in r for r in verdict.reasons)
    assert any("fuzzy_name_match:newco-eu" in r for r in verdict.reasons)


def test_adversarial_defaults_to_challenge_without_evidence():
    bare = q.PromotionSubject(
        vendor={"vendor_id": "x", "display_name": "X", "catalog_status": "machine_provisional", "reversal": {}},
        sources=[],
        events=[],
        materialization_decision=None,
        now=NOW,
        thresholds=THRESHOLDS,
    )
    verdict = q.review_adversarial(bare)
    assert not verdict.cleared
    assert any("missing_materialization_decision" in r for r in verdict.reasons)


def test_adversarial_clears_on_clean_evidence():
    assert q.review_adversarial(clean_subject()).cleared


def test_adversarial_challenges_open_material_change():
    subject = clean_subject()
    subject.events[0]["change_class"] = "material_confirmed"
    verdict = q.review_adversarial(subject)
    assert not verdict.cleared
    assert any("open_material_change" in r for r in verdict.reasons)


def test_release_gate_reviewer_consumes_decision():
    assert q.review_release_gate(clean_subject(), "pass").cleared
    assert not q.review_release_gate(clean_subject(), "blocked").cleared


# --------------------------------------------------------------------------- #
# Quorum + separation of duty
# --------------------------------------------------------------------------- #
def test_quorum_promotes_on_clean_subject():
    result = q.run_quorum(clean_subject(), release_gate_decision="pass")
    assert result.promote, result.reasons
    assert len(result.independent_modules) >= 2


def test_quorum_rejects_when_a_reviewer_challenges():
    result = q.run_quorum(clean_subject(), release_gate_decision="blocked")
    assert not result.promote
    assert any("release_gate" in r for r in result.reasons)


# --- prohibited self-approval combination 1: discovery == deciding ---------- #
def test_quorum_rejects_discovery_equals_deciding():
    result = q.run_quorum(
        clean_subject(),
        release_gate_decision="pass",
        deciding_bot="catalog-growth-discovery",  # == discovery_bot from materialization
    )
    assert not result.promote
    assert any("deciding_bot == discovery_bot" in r for r in result.reasons)


# --- prohibited self-approval combination 2: deciding is sole supporter ----- #
def test_separation_of_duty_rejects_sole_self_support():
    reasons = q.separation_of_duty_reasons(
        deciding_bot="dec",
        discovery_bot="disc",
        supporting_bot_ids=["dec"],
        independent_module_count=1,
        min_independent_modules=2,
    )
    assert any("sole supporter" in r for r in reasons)


# --- prohibited self-approval combination 3: identical modules not independent #
def test_identical_modules_do_not_count_as_independent_reviewers():
    v1 = q.ReviewVerdict("bot-a", "identity_resolver", q.REVIEWER_LEVEL, q.VERDICT_CLEAR)
    v2 = q.ReviewVerdict("bot-b", "identity_resolver", q.REVIEWER_LEVEL, q.VERDICT_CLEAR)
    assert q.independent_supporting_modules([v1, v2]) == {"identity_resolver"}


def test_quorum_rejects_when_same_module_reviewers_lack_independence():
    subject = clean_subject(thresholds={**THRESHOLDS, "min_independent_supporting_modules": 3})
    # Two reviewers from the SAME module + the release gate => only 2 distinct
    # modules, below the configured minimum of 3.
    result = q.run_quorum(
        subject,
        release_gate_decision="pass",
        reviewers=(q.review_identity, q.review_identity),
    )
    assert not result.promote
    assert any("insufficient_independent_supporting_modules" in r for r in result.reasons)


def test_separation_of_duty_clean_case_has_no_reasons():
    assert q.separation_of_duty_reasons(
        deciding_bot="dec",
        discovery_bot="disc",
        supporting_bot_ids=["a", "b"],
        independent_module_count=2,
        min_independent_modules=2,
    ) == []
