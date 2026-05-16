import json

from tools.openva import candidate_promotion_lifecycle


def write_plan(path, action_name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
                        "action": action_name,
                        "vendor_id": "example",
                        "source_type": "dpa",
                        "candidate_source_id": "example-dpa-candidate",
                        "candidate_url": "https://example.test/dpa",
                        "requires_human_review": True,
                        "writes_canonical_sources": False,
                        "non_advisory": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_candidate_promotion_lifecycle_skips_cleanup_and_selects_candidate_plan(tmp_path):
    cleanup = tmp_path / "maintenance/reviewed/promotion-plan-cleanup-1.json"
    candidate = tmp_path / "maintenance/reviewed/candidate-promotion-plan-1.json"
    write_plan(cleanup, "cleanup_source_for_review")
    write_plan(candidate, "promote_candidate_source_for_review")

    assert candidate_promotion_lifecycle.select_unapplied(tmp_path) == candidate
