from pathlib import Path


WORKFLOW = Path(".github/workflows/candidate-promotion-pr.yml")


def strict_growth_regeneration_block() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Regenerate strict-growth promotion plan")
    end = text.index("- name: Select candidate promotion plan")
    return text[start:end]


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_strict_growth_latest_regenerates_sha_bound_evidence():
    block = strict_growth_regeneration_block()

    assert "env.PROMOTION_PLAN_MODE == 'strict-growth-latest'" in block
    assert "env.PROMOTION_PLAN_MODE == 'strict-growth-shortlist'" in block
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

    assert '--max-promotion-actions-per-pr "$MAX_PROMOTION_ACTIONS_PER_PR"' in planner


def test_strict_growth_shortlist_mode_builds_shortlist_before_plan():
    text = workflow_text()

    assert "- strict-growth-shortlist" in text
    assert "reviewed-path|strict-growth-latest|strict-growth-shortlist" in text
    shortlist = text.index("python -m tools.openva.strict_growth_shortlist build \\")
    plan = text.index("python -m tools.openva.strict_growth_shortlist plan \\")
    apply = text.index("- name: Apply candidate promotions")

    assert shortlist < plan < apply
    block = text[shortlist:plan]
    assert "--eligibility-report catalog-growth-eligibility-report.json" in block
    assert "--backlog-report catalog-growth-backlog-report.json" in block
    assert '--max-actions "$MAX_PROMOTION_ACTIONS_PER_PR"' in block
    assert "--output-json strict-growth-shortlist.json" in block


def test_strict_growth_latest_uses_workflow_batch_cap_before_apply():
    text = workflow_text()

    plan = text.index("python -m tools.openva.promotion_planner plan-strict-growth \\")
    select = text.index("- name: Select candidate promotion plan")
    apply = text.index("- name: Apply candidate promotions")

    assert plan < select < apply
    assert '--max-promotion-actions-per-pr "$MAX_PROMOTION_ACTIONS_PER_PR"' in text[plan:select]
    assert "PROMOTION_PLAN_ACTION_COUNT=$SELECTED_PLAN_ACTION_COUNT" in text[select:apply]


def test_strict_growth_plan_preflight_runs_before_candidate_apply():
    text = workflow_text()

    preflight = text.index("- name: Preflight strict-growth promotion plan")
    apply = text.index("- name: Apply candidate promotions")
    assert preflight < apply

    block = text[preflight:apply]
    assert "env.PROMOTION_PLAN_MODE == 'strict-growth-latest'" in block
    assert "env.PROMOTION_PLAN_MODE == 'strict-growth-shortlist'" in block
    assert "python -m tools.openva.strict_growth_automerge check-plan \\" in block
    assert "--promotion-plan strict-growth-promotion-plan.json \\" in block
    assert "--eligibility-report catalog-growth-eligibility-report.json \\" in block
    assert "--current-head-sha" in block
    assert "--current-base-sha" in block


def test_candidate_promotion_commits_rebuilt_dist_outputs():
    text = workflow_text()

    assert "python -m tools.openva.validate build-indexes" in text
    assert "git diff --quiet -- data indexes dist maintenance/generated maintenance/machine-decisions openva-pack.json" in text
    assert "git add data indexes dist openva-pack.json" in text
    assert "if [ -d maintenance/generated ]; then" in text
    assert "git add maintenance/generated" in text
    # WP36b: the linked machine decision record is committed too.
    assert "git add maintenance/machine-decisions" in text


def test_strict_growth_latest_commits_sha_bound_evidence_files():
    text = workflow_text()

    assert "- name: Prepare strict-growth evidence files" in text
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
    assert "Upload strict-growth evidence artifacts" in text
    assert "Strict-growth uncapped promotion actions:" in text
    assert "Strict-growth source-health screened promotion actions:" in text
    assert "Strict-growth policy-capped promotion actions:" in text
    assert "Strict-growth batch-deferred promotion actions:" in text
    assert "Redirects detected:" in text
    assert "Redirects canonicalized:" in text
    assert "Redirects deferred:" in text
    assert "Cross-authority redirects:" in text
    assert "Generic redirects rejected:" in text
    assert "Unresolved redirects:" in text
    assert "cp strict-growth-shortlist.json maintenance/generated/strict-growth-shortlist.json" in text


def test_source_preflight_report_uploads_before_fail_closed():
    text = workflow_text()

    preflight = text.index("- name: Run source preflight for changed sources")
    upload = text.index("- name: Upload source preflight report")
    fail = text.index("- name: Fail if source preflight failed")
    body = text.index("- name: Prepare compact PR body")

    assert preflight < upload < fail < body
    block = text[preflight:upload]
    assert "id: source_preflight" in block
    assert "continue-on-error: true" in block
    upload_block = text[upload:fail]
    assert "if: always()" in upload_block
    assert "name: openva-candidate-promotion-source-preflight-report" in upload_block
    assert "path: source-preflight-report.json" in upload_block
    fail_block = text[fail:body]
    assert "if: steps.source_preflight.outcome == 'failure'" in fail_block
    assert "run: exit 1" in fail_block


def test_candidate_promotion_applies_only_machine_provisional_labels():
    # WP36b: candidate-promotion may apply the machine-provisional lane labels
    # (the marker at materialization, and automerge:machine-provisional via the
    # not_before controller). It must never apply any OTHER lane's automerge
    # label.
    text = workflow_text()

    assert "gh pr edit" in text
    assert "--add-label machine-provisional" in text
    assert "--add-label automerge:machine-provisional" in text
    assert "--add-label automerge:machine-canonical" not in text
    assert "--add-label automerge:p0-source-repair" not in text
    assert "--add-label automerge:strict-growth" not in text
    assert "--add-label automerge:observation" not in text
