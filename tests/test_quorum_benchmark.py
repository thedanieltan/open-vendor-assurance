"""WP39 quorum benchmark: the enumerated cases must classify correctly in CI.

Each case is fed through the WP37 independent quorum and asserted to clear or
challenge for the expected reason (by reviewer module). This is the regression
benchmark that proves the quorum keeps distinguishing genuine vendors from
duplicates, aliases, typosquats, unsafe redirects, gated/bot-protected and
stale sources, advisory/private leakage, and self-approval.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tools.openva import bot_quorum as q

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
THRESHOLDS = {"min_useful_source_roles": 2, "min_independent_supporting_modules": 2}


def event(source_id, *, health="ok", required=False, reason="first_observation", change="none"):
    return {"source_id": source_id, "vendor_id": "newco", "event_type": "first_observed",
            "change_class": change, "observed_at": "2026-06-12T00:00:00Z",
            "source_health_status": health, "review_signal": {"required": required, "reason": reason}}


def subject(**overrides) -> q.PromotionSubject:
    base = dict(
        vendor={"vendor_id": "newco", "display_name": "NewCo", "catalog_status": "machine_provisional",
                "official_domains": ["newco.com"], "public_entrypoints": ["https://newco.com"],
                "reversal": {"method": "remove", "reference": "revert"}, "notes": "machine provisional"},
        sources=[{"source_id": "newco-privacy", "source_type": "privacy_notice", "source_url": "https://newco.com/privacy"},
                 {"source_id": "newco-security", "source_type": "security_page", "source_url": "https://newco.com/security"}],
        events=[event("newco-privacy"), event("newco-security")],
        materialization_decision={"decision_id": "newco-vendor-materialization", "decision": "materialize_provisional",
                                  "deciding_bot": "strict-growth-materializer", "discovery_bot": "catalog-growth-discovery"},
        other_vendor_domains={"other.com"}, other_vendor_names={"other co"},
        match_index_items=[{"vendor_id": "other", "official_domains": ["other.com"], "display_name": "Other Co"}],
        now=NOW, thresholds=THRESHOLDS,
    )
    base.update(overrides)
    return q.PromotionSubject(**base)


def challenge_modules(result: q.QuorumResult) -> set[str]:
    return {r.split(":", 1)[0] for r in result.challenges}


# --- genuine ---------------------------------------------------------------- #
def test_genuine_vendor_promotes():
    result = q.run_quorum(subject(), release_gate_decision="pass")
    assert result.promote, result.reasons


# --- duplicate (shared official domain with another vendor) ----------------- #
def test_duplicate_domain_challenged():
    s = subject(match_index_items=[{"vendor_id": "newco-eu", "official_domains": ["newco.com"], "display_name": "Globex"}])
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "duplicate_match" in challenge_modules(result)


# --- alias / name collision with an existing vendor ------------------------- #
def test_alias_name_collision_challenged():
    result = q.run_quorum(subject(other_vendor_names={"newco"}), release_gate_decision="pass")
    assert not result.promote
    assert "identity_resolver" in challenge_modules(result)


# --- typosquat (fuzzy name match against another catalog vendor) ------------ #
def test_typosquat_challenged():
    s = subject(match_index_items=[{"vendor_id": "newco-inc", "official_domains": ["newc0.com"], "display_name": "NewCo"}])
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "duplicate_match" in challenge_modules(result)


# --- product-vs-company name collision -------------------------------------- #
def test_product_vs_company_name_collision_challenged():
    # A product sharing an existing company's name collides on identity.
    result = q.run_quorum(subject(other_vendor_names={"newco"}), release_gate_decision="pass")
    assert not result.promote
    assert "identity_resolver" in challenge_modules(result)


# --- parent / subsidiary on a shared domain --------------------------------- #
def test_parent_subsidiary_shared_domain_challenged():
    s = subject(match_index_items=[{"vendor_id": "newco-parent", "official_domains": ["newco.com"], "display_name": "NewCo Holdings"}])
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "duplicate_match" in challenge_modules(result)


# --- generic homepage as the only source ------------------------------------ #
def test_generic_homepage_only_challenged():
    s = subject(sources=[{"source_id": "newco-home", "source_type": "homepage", "source_url": "https://newco.com/"}],
                events=[event("newco-home")])
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "source_verifier" in challenge_modules(result)


# --- same-domain-safe redirect (clears) vs cross-domain-unsafe (challenged) -- #
def test_same_domain_safe_redirect_clears_domain_authority():
    s = subject(sources=[{"source_id": "newco-privacy", "source_type": "privacy_notice", "source_url": "https://www.newco.com/legal/privacy"},
                         {"source_id": "newco-security", "source_type": "security_page", "source_url": "https://trust.newco.com/security"}])
    assert q.review_domain_authority(s).cleared


def test_cross_domain_unsafe_redirect_challenged():
    s = subject()
    s.sources[0]["source_url"] = "https://newco.evilcdn.example/privacy"
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "domain_authority" in challenge_modules(result)


# --- gated / bot-protected sources (open review signal) --------------------- #
def test_gated_source_challenged():
    s = subject()
    s.events[0] = event("newco-privacy", health="gated", required=True, reason="source_health_gated")
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "adversarial" in challenge_modules(result)


def test_bot_protected_source_challenged():
    s = subject()
    s.events[0] = event("newco-privacy", health="bot_protected", required=True, reason="source_health_bot_protected")
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "adversarial" in challenge_modules(result)


# --- stale (latest observation still flags review) -------------------------- #
def test_stale_source_with_open_review_challenged():
    s = subject()
    s.events[1] = event("newco-security", required=True, reason="stale_observation")
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "adversarial" in challenge_modules(result)


# --- conflicting official domain (one of two collides) ---------------------- #
def test_conflicting_official_domain_challenged():
    s = subject()
    s.vendor["official_domains"] = ["newco.com", "other.com"]  # other.com belongs to another vendor
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "identity_resolver" in challenge_modules(result)


# --- advisory leakage in a source title ------------------------------------- #
def test_advisory_leakage_challenged():
    from tools.openva.advisory_wording import load_prohibited_terms
    term = load_prohibited_terms()[0]
    s = subject()
    s.sources[0]["title_native"] = f"NewCo {term} report"
    result = q.run_quorum(s, release_gate_decision="pass")
    assert not result.promote
    assert "adversarial" in challenge_modules(result)


# --- private leakage (release gate blocks) ---------------------------------- #
def test_private_leakage_blocks_via_release_gate():
    result = q.run_quorum(subject(), release_gate_decision="blocked")
    assert not result.promote
    assert "release_gate" in challenge_modules(result)


# --- self-approval (deciding == discovery) ---------------------------------- #
def test_self_approval_rejected():
    result = q.run_quorum(subject(), release_gate_decision="pass", deciding_bot="catalog-growth-discovery")
    assert not result.promote
    assert any("deciding_bot == discovery_bot" in r for r in result.reasons)
