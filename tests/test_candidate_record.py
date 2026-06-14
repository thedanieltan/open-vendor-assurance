"""WP40 unified candidate record tests.

Determinism (stable candidate_id + evidence_digest), schema validity, and the
fail-closed eligibility evaluator: every origin feeds one evaluator and
candidate origin never reduces verification requirements.
"""

from __future__ import annotations

from tools.openva import candidate_record as cr


def _identity(**overrides):
    base = {"vendor_id_candidate": "acme", "official_domain": "acme.example"}
    base.update(overrides)
    return base


def _source(**overrides):
    base = {
        "candidate_url": "https://acme.example/trust",
        "source_type_candidate": "trust_center",
        "access_state": "public_reachable",
        "source_role": "primary_assurance",
        "on_vendor_domain": True,
    }
    base.update(overrides)
    return base


def _evidence(url="https://acme.example/trust"):
    return [{"candidate_url": url, "verification_result": "canonical_candidate", "observed_at": "2026-06-14T00:00:00Z"}]


def test_candidate_id_is_deterministic():
    a = cr.compute_candidate_id("human_submission", "issue-42")
    b = cr.compute_candidate_id("human_submission", "issue-42")
    assert a == b == "cand-human-submission-issue-42"


def test_candidate_id_differs_by_origin_and_reference():
    assert cr.compute_candidate_id("human_submission", "issue-42") != cr.compute_candidate_id(
        "catalog_discovery", "issue-42"
    )
    assert cr.compute_candidate_id("human_submission", "issue-42") != cr.compute_candidate_id(
        "human_submission", "issue-43"
    )


def test_evidence_digest_is_sha256_and_order_independent():
    digest_a = cr.compute_evidence_digest(
        [{"b": 2, "a": 1, "candidate_url": "x"}, {"candidate_url": "y"}]
    )
    digest_b = cr.compute_evidence_digest(
        [{"a": 1, "candidate_url": "x", "b": 2}, {"candidate_url": "y"}]
    )
    assert digest_a == digest_b
    assert digest_a.startswith("sha256:")
    assert len(digest_a) == len("sha256:") + 64


def test_build_candidate_is_schema_valid_and_deterministic():
    kwargs = dict(
        candidate_origin="human_submission",
        origin_reference="issue-42",
        vendor_identity_candidate=_identity(),
        source_candidates=[_source()],
        evidence_references=_evidence(),
        discovery_component="submission-bridge",
        created_at="2026-06-14T00:00:00Z",
        eligibility_state="eligible",
        decision_reasons=["usable_assurance_sources=1"],
    )
    first = cr.build_candidate(**kwargs)
    second = cr.build_candidate(**kwargs)
    assert first == second
    assert cr.validate_candidate(first) == []
    assert first["candidate_id"] == "cand-human-submission-issue-42"


def test_every_origin_uses_the_same_evaluator_states():
    for origin in cr.CANDIDATE_ORIGINS:
        state, _ = cr.evaluate_eligibility(_identity(), [_source()])
        assert state == "eligible"
        record = cr.build_candidate(
            candidate_origin=origin,
            origin_reference="ref-1",
            vendor_identity_candidate=_identity(),
            source_candidates=[_source()],
            evidence_references=_evidence(),
            discovery_component="x",
            created_at="2026-06-14T00:00:00Z",
            eligibility_state=state,
        )
        assert cr.validate_candidate(record) == []


def test_eligible_requires_usable_source():
    state, reasons = cr.evaluate_eligibility(_identity(), [_source()])
    assert state == "eligible"
    assert any("usable_assurance_sources=1" in r for r in reasons)


def test_insufficient_evidence_defers():
    state, _ = cr.evaluate_eligibility(_identity(), [])
    assert state == "deferred_insufficient_evidence"


def test_duplicate_vendor_rejected():
    state, reasons = cr.evaluate_eligibility(
        _identity(matches_existing_vendor_id="acme"), [_source()]
    )
    assert state == "rejected_duplicate"
    assert any("acme" in r for r in reasons)


def test_identity_collision_fails_closed():
    state, _ = cr.evaluate_eligibility(_identity(), [_source()], identity_collision=True)
    assert state == "rejected_identity_collision"


def test_unsafe_official_domain_rejected():
    state, _ = cr.evaluate_eligibility(
        {**_identity(), "official_domain_unsafe": True}, [_source()]
    )
    assert state == "rejected_unsafe_url"


def test_all_gated_sources_rejected_gated():
    state, _ = cr.evaluate_eligibility(
        _identity(), [_source(access_state="declared_gated"), _source(access_state="bot_protected")]
    )
    assert state == "rejected_gated"


def test_one_bad_source_does_not_invalidate_vendor():
    # one unsafe + one good public source -> still eligible
    state, _ = cr.evaluate_eligibility(
        _identity(),
        [_source(access_state="unsafe_url", candidate_url="https://10.0.0.1/x"), _source()],
    )
    assert state == "eligible"


def test_cross_authority_only_defers_without_human_escalation():
    state, _ = cr.evaluate_eligibility(
        _identity(),
        [_source(on_vendor_domain=False, authority_proven=False)],
    )
    assert state in {"deferred_cross_authority", "deferred_insufficient_evidence"}
    assert state.startswith("deferred_")


def test_source_type_conflict_when_all_public_conflict():
    state, _ = cr.evaluate_eligibility(
        _identity(),
        [_source(source_type_conflict=True)],
    )
    assert state == "rejected_source_type_conflict"


def test_language_uncertainty_defers():
    state, _ = cr.evaluate_eligibility(_identity(), [_source()], language_uncertain=True)
    # a usable source plus language uncertainty defers rather than rejecting
    assert state == "deferred_language_uncertainty"


def test_evaluator_only_keys_never_reach_committed_record():
    # build_candidate stores source_candidates verbatim; evaluator-only keys
    # must be stripped by the caller. validate flags leakage.
    record = cr.build_candidate(
        candidate_origin="catalog_discovery",
        origin_reference="ref-leak",
        vendor_identity_candidate=_identity(),
        source_candidates=[_source(authority_proven=True)],
        evidence_references=_evidence(),
        discovery_component="x",
        created_at="2026-06-14T00:00:00Z",
    )
    errors = cr.validate_candidate(record)
    assert any("authority_proven" in e for e in errors)
