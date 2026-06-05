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


def test_candidate_promotion_commits_rebuilt_dist_outputs():
    text = workflow_text()

    assert "python -m tools.openva.validate build-indexes" in text
    assert "git diff --quiet -- data indexes dist maintenance/generated openva-pack.json" in text
    assert "git add data indexes dist openva-pack.json" in text
    assert "if [ -d maintenance/generated ]; then" in text
    assert "git add maintenance/generated" in text


def test_strict_growth_latest_commits_sha_bound_evidence_files():
    text = workflow_text()

    assert "- name: Prepare strict growth evidence files" in text
    assert "cp strict-growth-promotion-plan.json maintenance/generated/strict-growth-promotion-plan.json" in text
    assert (
        "cp catalog-growth-eligibility-report.json maintenance/generated/strict-growth-eligibility-report.json"
        in text
    )
    assert "PROMOTION_PLAN_PATH=maintenance/generated/strict-growth-promotion-plan.json" in text
    assert "ELIGIBILITY_REPORT_PATH=maintenance/generated/strict-growth-eligibility-report.json" in text
    assert "Strict-growth eligibility report: `{os.environ['ELIGIBILITY_REPORT_PATH']}`" in text
    assert "Head SHA: \\`$HEAD_SHA\\`" in text
    assert "candidate-promotion-pr-body-final.md" in text
    assert "Upload strict growth evidence artifacts" in text
