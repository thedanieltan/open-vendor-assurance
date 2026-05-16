import hashlib
import json
from pathlib import Path

import pytest

from tools.openva import maintenance_lifecycle


def write_plan(path: Path, action_type: str = "cleanup_source_for_review") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "report_type": "promotion_plan",
                "posture": {
                    "network_fetch_performed": False,
                    "writes_repository_state": False,
                    "writes_canonical_sources": False,
                    "non_advisory": True,
                },
                "actions": [
                    {
                        "action": action_type,
                        "vendor_id": "example",
                        "source_id": "example-dpa",
                        "source_type": "dpa",
                        "non_advisory": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def write_registry(root: Path, entries: list[dict]) -> None:
    path = root / "maintenance" / "applied" / "applied-plans.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "0.1.0", "plans": entries}), encoding="utf-8")


def test_select_unapplied_reviewed_plan_skips_applied_plan_by_name(tmp_path):
    cleanup_1 = tmp_path / "maintenance" / "reviewed" / "promotion-plan-cleanup-1.json"
    cleanup_2 = tmp_path / "maintenance" / "reviewed" / "promotion-plan-cleanup-2.json"
    write_plan(cleanup_1)
    write_plan(cleanup_2)
    write_registry(
        tmp_path,
        [
            {
                "plan_path": "maintenance/reviewed/promotion-plan-cleanup-1.json",
                "plan_name": "promotion-plan-cleanup-1.json",
                "status": "applied",
            }
        ],
    )

    assert maintenance_lifecycle.select_unapplied_reviewed_plan(tmp_path) == cleanup_2


def test_is_applied_plan_matches_plan_sha256(tmp_path):
    plan = tmp_path / "maintenance" / "reviewed" / "promotion-plan-cleanup-3.json"
    write_plan(plan)
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    write_registry(
        tmp_path,
        [
            {
                "plan_path": "maintenance/reviewed/renamed-plan.json",
                "plan_name": "renamed-plan.json",
                "plan_sha256": digest,
                "status": "applied",
            }
        ],
    )

    assert maintenance_lifecycle.is_applied_plan(plan, tmp_path)


def test_validate_reviewed_cleanup_plan_rejects_candidate_promotion_action(tmp_path):
    plan = tmp_path / "maintenance" / "reviewed" / "promotion-plan-growth-1.json"
    write_plan(plan, action_type="promote_candidate_source_for_review")
    write_registry(tmp_path, [])

    with pytest.raises(ValueError, match="unsupported reviewed cleanup action"):
        maintenance_lifecycle.validate_reviewed_cleanup_plan(plan, tmp_path)
