"""WP40B autonomous source-repair classifier tests."""

from __future__ import annotations

from tools.openva.source_repair_classifier import Replacement, classify_repair


def test_temporary_failure_does_not_trigger_repair():
    result = classify_repair(latest_status="unreachable", consecutive_failures=1)
    assert result.outcome == "temporary_failure"
    assert result.action == "bounded_retry"


def test_persistent_unavailable_without_replacement_quarantines():
    result = classify_repair(latest_status="not_found", consecutive_failures=4)
    assert result.outcome == "confirmed_unavailable"
    assert result.action == "quarantine"


def test_bot_protection_is_never_bypassed():
    result = classify_repair(latest_status="bot_protected", consecutive_failures=5)
    assert result.outcome == "bot_protected"
    assert result.action == "record_access_state"


def test_gated_records_access_state_and_quarantines_when_persistent():
    result = classify_repair(latest_status="gated_or_login_required", consecutive_failures=5)
    assert result.outcome == "gated"
    assert result.action == "record_access_state_and_quarantine"


def test_cross_authority_replacement_without_evidence_is_deferred():
    replacement = Replacement(final_url="https://other.example/x", reachable=True, on_same_authority=False)
    result = classify_repair(latest_status="not_found", consecutive_failures=4, replacement=replacement)
    assert result.outcome == "cross_authority_unproven"
    assert result.action == "defer"


def test_safe_replacement_requires_repeated_evidence():
    weak = Replacement(
        final_url="https://acme.example/new", reachable=True, on_same_authority=True,
        source_role_match=True, repeated_observations=1, fresh_evidence=True, semantic_strong=True,
    )
    result = classify_repair(latest_status="gone", consecutive_failures=4, replacement=weak,
                             min_replacement_observations=2)
    assert result.outcome == "same_authority_redirect"
    assert result.action == "repair_candidate"

    strong = Replacement(
        final_url="https://acme.example/new", reachable=True, on_same_authority=True,
        source_role_match=True, repeated_observations=3, fresh_evidence=True, semantic_strong=True,
    )
    result = classify_repair(latest_status="gone", consecutive_failures=4, replacement=strong,
                             min_replacement_observations=2)
    assert result.outcome == "safe_replacement"
    assert result.action == "autonomous_repair_pr"


def test_duplicate_replacement_is_ambiguous_defer():
    replacement = Replacement(
        final_url="https://acme.example/dup", reachable=True, on_same_authority=True,
        source_role_match=True, duplicate_conflict=True, repeated_observations=3,
        fresh_evidence=True, semantic_strong=True,
    )
    result = classify_repair(latest_status="gone", consecutive_failures=4, replacement=replacement)
    assert result.outcome == "ambiguous_replacement"
    assert result.action == "defer"


def test_generic_redirect_without_replacement_defers():
    result = classify_repair(latest_status="homepage_or_generic_redirect", consecutive_failures=4)
    assert result.outcome == "generic_redirect"
    assert result.action == "defer"


def test_repair_is_reversible():
    result = classify_repair(latest_status="not_found", consecutive_failures=4)
    assert result.reversible is True
