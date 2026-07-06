from __future__ import annotations

from tools.openva import candidate_record as cr


INTERNAL_TERMS = {
    "eligibility",
    "candidate_processing",
    "pending_ingress",
    "workflow_visible",
    "machine_provisional",
    "quorum",
    "pull request",
    "pr",
    "ingress",
    "lifecycle",
}


def _record(eligibility_state: str) -> dict[str, object]:
    return cr.build_candidate(
        candidate_origin="coverage_gap",
        origin_reference="vendor:dpa:https://vendor.example/dpa",
        vendor_identity_candidate={"vendor_id_candidate": "vendor", "official_domain": "vendor.example"},
        source_candidates=[
            {
                "candidate_url": "https://vendor.example/dpa",
                "final_url": "https://vendor.example/dpa",
                "http_status": 200,
                "content_type": "text/html",
                "source_type_candidate": "dpa",
                "access_state": "public_reachable",
                "source_role": "primary_assurance",
                "on_vendor_domain": True,
                "verification_result": "likely_vendor_published",
                "reasons": [],
            }
        ],
        evidence_references=[
            {
                "candidate_url": "https://vendor.example/dpa",
                "final_url": "https://vendor.example/dpa",
                "http_status": 200,
                "content_type": "text/html",
                "verification_result": "likely_vendor_published",
                "observed_at": "2026-07-06T00:00:00Z",
            }
        ],
        discovery_component="vendor_resolution:api_resolution",
        created_at="2026-07-06T00:00:00Z",
        eligibility_state=eligibility_state,
        decision_reasons=[],
    )


def test_phase_6_user_memory_states_are_stable() -> None:
    assert set(cr.USER_MEMORY_STATES) == {
        "queued_for_reuse",
        "already_known",
        "candidate_found",
        "not_queued_ambiguous",
        "not_queued_unsafe",
        "not_queued_insufficient_evidence",
    }


def test_eligible_candidate_is_candidate_found_until_durable() -> None:
    assert cr.user_facing_candidate_memory_state("eligible", ingress_state="recorded") == "candidate_found"


def test_eligible_candidate_is_queued_for_reuse_after_durable_ingress() -> None:
    for ingress_state in ("persisted_local", "committed_local", "submitted_remote", "workflow_visible"):
        assert cr.user_facing_candidate_memory_state("eligible", ingress_state=ingress_state) == "queued_for_reuse"


def test_duplicate_candidate_is_already_known() -> None:
    assert cr.user_facing_candidate_memory_state("rejected_duplicate") == "already_known"


def test_ambiguous_candidates_are_not_queued_as_ambiguous() -> None:
    assert cr.user_facing_candidate_memory_state("rejected_identity_collision") == "not_queued_ambiguous"
    assert cr.user_facing_candidate_memory_state("deferred_cross_authority") == "not_queued_ambiguous"
    assert cr.user_facing_candidate_memory_state("deferred_language_uncertainty") == "not_queued_ambiguous"


def test_unsafe_candidate_is_not_queued_as_unsafe() -> None:
    assert cr.user_facing_candidate_memory_state("rejected_unsafe_url") == "not_queued_unsafe"


def test_insufficient_public_evidence_is_not_queued_as_insufficient_evidence() -> None:
    assert cr.user_facing_candidate_memory_state("deferred_insufficient_evidence") == "not_queued_insufficient_evidence"
    assert cr.user_facing_candidate_memory_state("rejected_source_type_conflict") == "not_queued_insufficient_evidence"
    assert cr.user_facing_candidate_memory_state("rejected_gated") == "not_queued_insufficient_evidence"


def test_user_facing_candidate_memory_view_hides_internal_lifecycle_terms() -> None:
    view = cr.user_facing_candidate_memory_view(_record("eligible"), ingress_state="workflow_visible")

    assert view == {"state": "queued_for_reuse", "label": "queued for reuse", "not_advice": True}
    assert set(view) == {"state", "label", "not_advice"}
    text = " ".join(str(value).lower() for value in view.values())
    for term in INTERNAL_TERMS:
        assert term not in text


def test_user_facing_candidate_memory_view_is_non_advisory_for_rejections() -> None:
    view = cr.user_facing_candidate_memory_view(_record("rejected_unsafe_url"), ingress_state="recorded")

    assert view == {"state": "not_queued_unsafe", "label": "not queued: unsafe", "not_advice": True}
