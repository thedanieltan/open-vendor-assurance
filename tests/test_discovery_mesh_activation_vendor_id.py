from pathlib import Path

import pytest

from tools.openva.discovery_mesh_activation import build_vendor_promotion_plans
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def test_rejects_reviewed_action_without_vendor_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing vendor_id"):
        build_vendor_promotion_plans(
            {
                "actions": [
                    {
                        "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
                        "candidate_source_id": "orphan-dpa",
                        "source_type": "dpa",
                    }
                ]
            },
            source_plan_path="raw.json",
            run_token="run-1",
            output_root=tmp_path,
        )
