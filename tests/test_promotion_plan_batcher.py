from tools.openva.promotion_plan_batcher import build_batches


def action(index: int) -> dict:
    return {
        "action": "promote_candidate_source_for_review",
        "vendor_id": f"vendor-{index}",
        "source_type": "dpa",
        "candidate_source_id": f"vendor-{index}-dpa-candidate",
        "candidate_url": f"https://vendor-{index}.test/dpa",
        "requires_human_review": True,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }


def test_promotion_plan_batcher_splits_candidate_promotion_actions():
    plan = {"actions": [action(index) for index in range(5)]}

    batches = build_batches(plan, "promotion-plan.json", max_actions=2)

    assert [batch["summary"]["action_count"] for batch in batches] == [2, 2, 1]
    assert all(batch["posture"]["writes_canonical_sources"] is False for batch in batches)
    assert all(batch["posture"]["non_advisory"] is True for batch in batches)


def test_promotion_plan_batcher_ignores_non_candidate_promotion_actions():
    plan = {
        "actions": [
            action(1),
            {"action": "cleanup_source_for_review", "vendor_id": "example"},
        ]
    }

    batches = build_batches(plan, "promotion-plan.json", max_actions=50)

    assert len(batches) == 1
    assert batches[0]["summary"]["action_count"] == 1
    assert batches[0]["actions"][0]["action"] == "promote_candidate_source_for_review"
