from tools.openva import promotion_planner


def test_promotion_planner_uses_reviewed_candidate_promotion_action_for_strong_candidates(tmp_path):
    candidate_path = tmp_path / "data" / "vendors" / "example" / "candidate_sources" / "example-dpa.yaml"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(
        "\n".join(
            [
                "schema_version: 0.1.0",
                "candidate_source_id: example-dpa-candidate",
                "vendor_id: example",
                "source_type_candidate: dpa",
                "candidate_url: https://example.com/dpa",
                "confidence: likely",
                "evidence:",
                "  http_status: 200",
                "  matched_terms:",
                "    - data processing",
                "  page_title: Example DPA",
            ]
        ),
        encoding="utf-8",
    )

    plan = promotion_planner.build_promotion_plan(root=tmp_path)
    action = plan["actions"][0]

    assert action["action"] == "promote_candidate_source_for_review"
    assert action["requires_human_review"] is True
    assert action["writes_canonical_sources"] is False
    assert action["non_advisory"] is True
    assert action["candidate_source_id"] == "example-dpa-candidate"
    assert action["candidate_url"] == "https://example.com/dpa"


def test_promotion_planner_does_not_emit_legacy_candidate_promotion_action(tmp_path):
    candidate_path = tmp_path / "data" / "vendors" / "example" / "candidate_sources" / "example-dpa.yaml"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(
        "\n".join(
            [
                "schema_version: 0.1.0",
                "candidate_source_id: example-dpa-candidate",
                "vendor_id: example",
                "source_type_candidate: dpa",
                "candidate_url: https://example.com/dpa",
                "confidence: likely",
                "evidence:",
                "  http_status: 200",
                "  matched_terms:",
                "    - data processing",
            ]
        ),
        encoding="utf-8",
    )

    plan = promotion_planner.build_promotion_plan(root=tmp_path)
    action_names = {action["action"] for action in plan["actions"]}

    assert "promote_candidate_source_for_review" in action_names
    assert "promote_candidate_for_review" not in action_names
