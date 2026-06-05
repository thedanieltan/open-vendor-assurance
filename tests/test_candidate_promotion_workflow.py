from pathlib import Path


WORKFLOW = Path(".github/workflows/candidate-promotion-pr.yml")


def strict_growth_regeneration_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Regenerate strict growth promotion plan")
    end = text.index("- name: Select candidate promotion plan")
    return text[start:end]


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
