from tools.openva.cleanup_proposals import build_cleanup_proposal, render_markdown


def promotion_plan() -> dict:
    return {
        "actions": [
            {
                "action": "cleanup_source_for_review",
                "reason": "Existing canonical source appears mismatched.",
                "vendor_id": "example",
                "source_id": "example-dpa",
                "source_type": "dpa",
                "source_url": "https://example.com/legal/data-processing-addendum",
                "path": "data/vendors/example/sources/example-dpa.yaml",
                "verification": {
                    "verification_status": "suspect_inferred_url",
                    "http_status": 200,
                    "final_url": "https://example.com/legal/data-processing-addendum",
                },
                "requires_human_review": True,
                "non_advisory": True,
            },
            {
                "action": "promote_candidate_for_review",
                "reason": "Candidate has public HTTP 200 evidence and matched terms.",
                "vendor_id": "example",
                "candidate_source_id": "example-subprocessors-list-candidate",
                "source_type": "subprocessors_list",
                "candidate_url": "https://example.com/legal/subprocessors",
                "path": "data/vendors/example/candidate_sources/example-subprocessors-list-candidate.yaml",
                "evidence": {
                    "confidence": "likely",
                    "http_status": 200,
                    "matched_terms": ["subprocessor", "service providers"],
                    "page_title": "Subprocessors",
                },
                "requires_human_review": True,
                "non_advisory": True,
            },
            {
                "action": "keep_unavailable_until_next_review",
                "reason": "No canonical source exists and this absence has been recorded.",
                "vendor_id": "another",
                "source_type": "dpa",
                "unavailable_source_id": "another-dpa",
                "path": "data/vendors/another/unavailable_sources/another-dpa.yaml",
                "next_review_after": "2026-08-16",
                "requires_human_review": False,
                "non_advisory": True,
            },
        ]
    }


def test_cleanup_proposal_groups_actions_and_counts_blockers():
    proposal = build_cleanup_proposal(promotion_plan())

    assert proposal["report_type"] == "cleanup_proposal"
    assert proposal["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }
    assert proposal["summary"]["action_count"] == 3
    assert proposal["summary"]["blocking_cleanup_actions"] == 1
    assert proposal["summary"]["promotable_candidate_actions"] == 1
    assert proposal["summary"]["action_types"] == {
        "cleanup_source_for_review": 1,
        "keep_unavailable_until_next_review": 1,
        "promote_candidate_for_review": 1,
    }
    assert set(proposal["groups"]) == {
        "cleanup_source_for_review",
        "keep_unavailable_until_next_review",
        "promote_candidate_for_review",
    }


def test_cleanup_proposal_markdown_is_non_advisory_and_actionable():
    proposal = build_cleanup_proposal(promotion_plan())
    markdown = render_markdown(proposal)

    assert "# OpenVA Cleanup Proposal" in markdown
    assert "non-advisory" in markdown
    assert "Clean up suspect or mismatched canonical sources" in markdown
    assert "Review candidate sources for possible promotion" in markdown
    assert "Keep unavailable-source ledger entries" in markdown
    assert "vendor: `example`" in markdown
    assert "source_id: `example-dpa`" in markdown
    assert "candidate_source_id: `example-subprocessors-list-candidate`" in markdown
    assert "next_review_after: `2026-08-16`" in markdown
