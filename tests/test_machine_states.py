"""WP40A Issue 5: routine review reasons map to machine states, not human review."""

from __future__ import annotations

from tools.openva import contribution_intake
from tools.openva import machine_states as ms
from tools.openva.candidate_record import ELIGIBILITY_STATES


def test_every_mapped_state_is_a_known_eligibility_state():
    for state in ms.REASON_TO_STATE.values():
        assert state in ELIGIBILITY_STATES


def test_no_mapping_target_is_a_human_review_verdict():
    for state in ms.REASON_TO_STATE.values():
        assert not ms.is_human_review_verdict(state)
        assert not state.endswith("human_review")


def test_unknown_reason_fails_closed_to_deferred():
    assert ms.map_reason("totally_unknown_reason") == "deferred_insufficient_evidence"


def test_resolve_prefers_rejection_over_deferral():
    reasons = ["new_vendor_identity_requires_human_review", "gated_or_access_control_language_needs_human_review"]
    assert ms.resolve_state(reasons) == "rejected_gated"


def test_empty_reasons_is_eligible():
    assert ms.resolve_state([]) == "eligible"


def test_all_legacy_intake_reasons_have_machine_mappings():
    # Every *_requires/needs_human_review reason emitted by contribution_intake
    # must have an explicit machine-state mapping so nothing silently falls back
    # to a human-review queue in the autonomous lane.
    import inspect

    source = inspect.getsource(contribution_intake)
    emitted = set()
    for token in source.replace('"', " ").replace("'", " ").split():
        # the bare "needs_human_review" is the decision value, not a granular reason
        if token == "needs_human_review":
            continue
        if token.endswith("requires_human_review") or token.endswith("needs_human_review"):
            emitted.add(token)
    assert emitted, "expected to find legacy human-review reasons in contribution_intake"
    for reason in emitted:
        assert reason in ms.REASON_TO_STATE, f"unmapped legacy reason: {reason}"


def test_human_governed_change_classes_are_named():
    for change in ("code", "schema", "workflow", "policy", "authority", "permissions", "governance"):
        assert change in ms.HUMAN_GOVERNED_CHANGE_CLASSES
