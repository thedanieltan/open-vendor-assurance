"""WP40A submission lifecycle status tests: idempotent comment, terminal close."""

from __future__ import annotations

from tools.openva import submission_lifecycle as sl


def test_derive_progresses_with_signals():
    assert sl.derive_state(verification_done=False, eligibility_state=None) == "submitted"
    assert sl.derive_state(verification_done=True, eligibility_state=None) == "verified"
    assert sl.derive_state(verification_done=True, eligibility_state="eligible") == "eligible"
    assert sl.derive_state(verification_done=True, eligibility_state="eligible", materialising=True) == "materialising"
    assert sl.derive_state(verification_done=True, eligibility_state="eligible", catalog_status="machine_provisional") == "machine_provisional"
    assert sl.derive_state(verification_done=True, eligibility_state="eligible", catalog_status="active") == "active"


def test_deferred_and_rejected_outcomes():
    assert sl.derive_state(verification_done=True, eligibility_state="deferred_insufficient_evidence") == "deferred"
    assert sl.derive_state(verification_done=True, eligibility_state="rejected_duplicate") == "rejected"
    assert sl.derive_state(verification_done=True, eligibility_state="eligible", rolled_back=True) == "rolled_back"


def test_terminal_states_close_issue():
    for state in ("active", "deferred", "rejected", "rolled_back"):
        assert sl.is_terminal(state)
        assert sl.should_close(state)
    for state in ("submitted", "verified", "eligible", "machine_provisional", "observing", "quorum_pending"):
        assert not sl.is_terminal(state)
        assert not sl.should_close(state)


def test_comment_is_idempotent_with_stable_marker():
    kwargs = dict(state="machine_provisional", candidate_id="cand-human-submission-issue-1",
                  verification_result="canonical_candidate", decision_id="acme-mat", pr_url="http://pr/1")
    first = sl.render_status_comment(**kwargs)
    second = sl.render_status_comment(**kwargs)
    assert first == second
    assert first.count(sl.COMMENT_MARKER) == 1
    assert first.startswith(sl.COMMENT_MARKER)


def test_comment_shows_required_fields():
    body = sl.render_status_comment(
        state="quorum_pending",
        candidate_id="cand-x",
        verification_result="likely_vendor_published",
        decision_id="dec-1",
        pr_url="http://pr/2",
    )
    for needle in ("Current state", "Last completed action", "Verification result",
                   "Candidate ID", "Linked decision", "Linked PR",
                   "Next scheduled action", "Final outcome", "`quorum_pending`", "`cand-x`", "`dec-1`"):
        assert needle in body


def test_payload_flags_close_at_terminal():
    payload = sl.status_payload(state="rejected", candidate_id="c", verification_result="duplicate_existing_source")
    assert payload["close_issue"] is True
    assert payload["terminal"] is True
    payload = sl.status_payload(state="observing", candidate_id="c", verification_result="canonical_candidate")
    assert payload["close_issue"] is False


def test_comment_is_non_advisory():
    body = sl.render_status_comment(state="active", candidate_id="c", verification_result="canonical_candidate")
    lowered = body.lower()
    assert "not legal" in lowered
    assert "neither approves nor" in lowered
