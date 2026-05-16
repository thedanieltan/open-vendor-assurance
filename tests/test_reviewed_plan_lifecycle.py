import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLIED_PLANS = ROOT / "maintenance" / "applied" / "applied-plans.json"
REVIEWED_DIR = ROOT / "maintenance" / "reviewed"


def test_applied_plan_registry_records_consumed_cleanup_plans():
    assert APPLIED_PLANS.exists()

    registry = json.loads(APPLIED_PLANS.read_text(encoding="utf-8"))
    plans = {plan["plan_name"]: plan for plan in registry["plans"]}

    for plan_name, pr_number in {
        "promotion-plan-cleanup-1.json": 129,
        "promotion-plan-cleanup-2.json": 133,
    }.items():
        assert plan_name in plans
        assert plans[plan_name]["applied_by_pr"] == pr_number
        assert plans[plan_name]["catalog_pr_title"]
        assert plans[plan_name]["status"] == "applied"
        assert (REVIEWED_DIR / plan_name).exists()
