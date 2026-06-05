from pathlib import Path


WORKFLOW = Path(".github/workflows/candidate-promotion-pr.yml")


def strict_growth_regeneration_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Regenerate strict growth promotion plan")
    end = text.index("- name: Select candidate promotion plan")
    return text[start:end]


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_strict_growth_latest_regenerates_sha_bound_evidence():
    block = strict_growth_regeneration_block()

    assert "if: env.PROMOTION_PLAN_MODE == 'strict-growth-latest'" in block
    assert "python -m tools.openva.catalog_growth_eligibility classify \\" in block
    assert "python -m tools.openva.promotion_planner plan-strict-growth \\" in block

    eligibility = block[
        block.index("python -m tools.openva.catalog_growth_eligibility classify \\") :
        block.index("python -m tools.openva.promotion_planner plan-strict-growth \\")
    ]
    planner = block[block.index("python -m tools.openva.promotion_planner plan-strict-growth \\") :]

    for command in (eligibility, planner):
        assert '--head-sha "${{ github.sha }}"' in command
        assert '--base-sha "${{ github.sha }}"' in command


def test_strict_growth_plan_preflight_runs_before_candidate_apply():
    text = workflow_text()

    preflight = text.index("- name: Preflight strict growth promotion plan")
    apply = text.index("- name: Apply candidate promotions")
    assert preflight < apply

    block = text[preflight:apply]
    assert "if: steps.reviewed_plan.outputs.HAS_REVIEWED_PLAN == 'true' && env.PROMOTION_PLAN_MODE == 'strict-growth-latest'" in block
    assert "python -m tools.openva.strict_growth_automerge check-plan \\" in block
    assert "--promotion-plan strict-growth-promotion-plan.json \\" in block
    assert "--eligibility-report catalog-growth-eligibility-report.json \\" in block
    assert "--current-head-sha" in block
    assert "--current-base-sha" in block
