"""Tier A: content-blocked coverage report — boundaries and zero-weight."""

import re

import pytest

from tools.openva.candidate_promotion_actions import validate_materialization_thresholds
from tools.openva.coverage_blocked import CATEGORIES, build_blocked_coverage_report

OFFICIAL = {"acme": ["acme.example"]}
STRONG = {"class": "strong", "method": "official_domain_link", "target_url": "https://acme.example/trust", "observed_at": "t"}


def _candidate(source_candidates, *, eligibility="eligible", vendor_id="acme", domain="acme.example"):
    return {
        "vendor_identity_candidate": {"vendor_id_candidate": vendor_id, "official_domain": domain},
        "eligibility_state": eligibility,
        "source_candidates": source_candidates,
    }


def report(candidates=None, sources=None):
    return build_blocked_coverage_report(
        candidates=candidates or [], sources=sources or [], official_domains_by_vendor=OFFICIAL
    )


def cats(rep):
    return {c: rep["categories"][c]["items"] for c in CATEGORIES}


def test_identity_anchor_passes_but_collision_excluded():
    ok = report([_candidate([])])
    assert "acme" in cats(ok)["identity_anchored_vendor_candidates"]
    collision = report([_candidate([], eligibility="rejected_identity_collision")])
    assert cats(collision)["identity_anchored_vendor_candidates"] == []


def test_bot_protected_and_gated_are_distinct_and_gated_excludes_bot():
    rep = report([_candidate([
        {"candidate_url": "https://acme.example/a", "access_state": "bot_protected"},
        {"candidate_url": "https://acme.example/b", "access_state": "gated_or_auth_required"},
    ])])
    c = cats(rep)
    assert c["bot_protected_candidate_sources"] == ["https://acme.example/a"]
    assert c["gated_candidate_sources"] == ["https://acme.example/b"]


def test_locator_verified_requires_strong_authority_and_blocked_access():
    blocked_strong = report([_candidate([
        {"candidate_url": "https://acme.example/t", "access_state": "bot_protected", "authority": STRONG},
    ])])
    assert cats(blocked_strong)["locator_verified_content_blocked"] == ["https://acme.example/t"]

    # Blocked but NOT strong authority -> not locator-verified.
    weak = report([_candidate([
        {"candidate_url": "https://acme.example/t", "access_state": "bot_protected",
         "authority": {"class": "corroborating", "method": "cname_corroboration", "target_url": "x", "observed_at": "t"}},
    ])])
    assert cats(weak)["locator_verified_content_blocked"] == []


def test_sitemap_only_locator_cannot_be_locator_verified_or_blocked():
    # A sitemap-derived candidate: on-domain, not fetched, no authority.
    sitemap = report([_candidate([
        {"candidate_url": "https://acme.example/trust", "access_state": "not_fetched"},
    ])])
    c = cats(sitemap)
    assert c["locator_verified_content_blocked"] == []
    assert c["bot_protected_candidate_sources"] == []
    assert c["gated_candidate_sources"] == []
    assert c["delegation_unproven"] == []  # on-domain


def test_public_landing_gated_docs_only_from_committed_classification():
    rep = report(sources=[
        {"source_id": "acme-trust", "access_class": "public_landing_gated_docs"},
        {"source_id": "acme-priv", "access_class": "public_web"},
    ])
    assert cats(rep)["public_landing_gated_docs"] == ["acme-trust"]


def test_delegation_unproven_is_off_domain_without_strong_authority():
    rep = report([_candidate([
        {"candidate_url": "https://other.test/trust", "access_state": "public_reachable"},
    ])])
    assert cats(rep)["delegation_unproven"] == ["https://other.test/trust"]
    # Off-domain WITH strong delegation authority -> not unproven.
    proven = report([_candidate([
        {"candidate_url": "https://other.test/trust", "access_state": "public_reachable",
         "authority": {"class": "strong", "method": "official_domain_redirect", "target_url": "https://other.test/trust", "observed_at": "t"}},
    ])])
    assert cats(proven)["delegation_unproven"] == []


def test_client_render_suspected_is_deterministic_indicator_only():
    rep = report([_candidate([
        {"candidate_url": "https://acme.example/spa", "access_state": "public_reachable", "client_render_suspected": True},
    ])])
    assert cats(rep)["client_render_suspected"] == ["https://acme.example/spa"]


def test_dedup_by_identity_not_event_count():
    rep = report([_candidate([
        {"candidate_url": "https://acme.example/a", "access_state": "bot_protected"},
        {"candidate_url": "https://acme.example/a", "access_state": "bot_protected"},
    ])])
    assert rep["categories"]["bot_protected_candidate_sources"]["count"] == 1


def test_report_carries_identifiers_only_and_is_non_advisory():
    rep = report([_candidate([{"candidate_url": "https://acme.example/a", "access_state": "bot_protected"}])])
    assert set(rep) == {"report_type", "schema_version", "not_advice", "categories"}
    assert rep["not_advice"] is True
    for category in CATEGORIES:
        for item in rep["categories"][category]["items"]:
            assert isinstance(item, str)
            assert not re.search(r"\s", item)  # url/id identifiers, never page prose


def test_report_is_reproducible():
    candidates = [_candidate([{"candidate_url": "https://acme.example/a", "access_state": "bot_protected"}])]
    a = build_blocked_coverage_report(candidates=candidates, sources=[], official_domains_by_vendor=OFFICIAL)
    b = build_blocked_coverage_report(candidates=candidates, sources=[], official_domains_by_vendor=OFFICIAL)
    assert a == b


@pytest.mark.parametrize("access_state", ["bot_protected", "gated_or_auth_required", "declared_gated", "not_fetched", "public_reachable"])
def test_no_category_item_can_satisfy_materialization(access_state):
    # A coverage item is a locator with no agreeing independent retrieval
    # evidence; building a materialization action from it fails closed.
    action = {
        "vendor": {"candidate_vendor_id": "acme", "official_domain_candidate": "acme.example"},
        "source": {
            "candidate_url": "https://acme.example/x",
            "evidence": {
                "final_url": "https://acme.example/x",
                "name_supported_by_official_domain_metadata": True,
                "source_host_authority": "vendor_controlled",
                "adversarial_review": "clean",
                "evidence_fresh": True,
            },
        },
    }
    with pytest.raises(ValueError) as exc:
        validate_materialization_thresholds(action)
    assert "retrieval_attempts" in str(exc.value)
