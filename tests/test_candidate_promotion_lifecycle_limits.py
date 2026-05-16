import json

import pytest

from tools.openva import candidate_promotion_lifecycle


def test_candidate_promotion_lifecycle_rejects_oversized_plan(tmp_path):
    plan = tmp_path / "maintenance/reviewed/candidate-promotion-plan-large.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        json.dumps(
            {
                "posture": {
                    "network_fetch_performed": False,
                    "writes_repository_state": False,
                    "writes_canonical_sources": False,
                    "non_advisory": True,
                },
                "actions": [
                    {
                        "action": "promote_candidate_source_for_review",
                        "vendor_id": f"vendor-{index}",
                        "source_type": "dpa",
                        "candidate_source_id": f"vendor-{index}-dpa-candidate",
                        "candidate_url": f"https://vendor-{index}.test/dpa",
                        "requires_human_review": True,
                        "writes_canonical_sources": False,
                        "non_advisory": True,
                    }
                    for index in range(3)
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_actions_per_plan=2"):
        candidate_promotion_lifecycle.validate_candidate_promotion_plan(plan, tmp_path, max_actions=2)
