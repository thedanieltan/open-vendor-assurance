from pathlib import Path

from tools.openva.generated_catalog_pr_risk import GeneratedCatalogPrRiskClass, classify_generated_catalog_pr_risk


AUTONOMOUS_GROWTH = Path(".github/workflows/autonomous-catalog-growth.yml")
DISCOVERY_LEDGER = Path(".github/workflows/discovery-ledger-append-pr.yml")
MACHINE_MATERIALIZATION = Path(".github/workflows/machine-provisional-materialization.yml")
CANDIDATE_PROMOTION = Path(".github/workflows/candidate-promotion-pr.yml")
AGENT_AUTOMERGE = Path(".github/workflows/agent-automerge.yml")
CATALOG_PR_GUARD = Path(".github/workflows/catalog-pr-guard.yml")


def test_discovery_ledger_append_authenticates_source_run_and_artifact():
    text = DISCOVERY_LEDGER.read_text(encoding="utf-8")

    assert 'workflows: ["catalog-growth-discovery"]' in text
    assert "conclusion == 'success'" in text
    assert 'gh run view "$RUN_ID" --json attempt,conclusion,headBranch,headSha,workflowName' in text
    assert 'if [ "$WORKFLOW_NAME" != "catalog-growth-discovery" ]; then' in text
    assert 'if [ "$CONCLUSION" != "success" ]; then' in text
    assert 'if [ "$HEAD_BRANCH" != "main" ]; then' in text
    assert 'git merge-base --is-ancestor "$HEAD_SHA" origin/main' in text
    assert "--name openva-catalog-growth-discovery-artifacts \\" in text
    assert 'echo "digest=sha256:$DIGEST" >> "$GITHUB_OUTPUT"' in text
    assert "Discovery workflow attempt:" in text
    assert "Discovery head SHA:" in text
    assert "Discovery artifact digest:" in text


def test_discovery_ledger_append_has_race_safe_append_contract():
    text = DISCOVERY_LEDGER.read_text(encoding="utf-8")

    assert "group: discovery-ledger-append-pr" in text
    assert "cancel-in-progress: false" in text
    assert "git merge-base --is-ancestor origin/main HEAD" in text
    assert "--max-append-count 500 \\" in text
    assert "maintenance/discovery-events/*.ndjson" in text
    assert "git push --force" not in text
    assert "git push -f" not in text
    assert "--force-with-lease" not in text

    first_label = 'gh label create "discovery-ledger"'
    label_apply = 'gh pr edit "$PR_NUMBER"'
    assert first_label in text
    assert 'gh label create "automerge:observation"' in text
    label_block_start = text.index(first_label)
    label_block_end = text.index(label_apply, label_block_start)
    label_block = text[label_block_start:label_block_end]
    append_and_push_text = text[:label_block_start] + text[label_block_end:]
    assert label_block.count("--force") == 2
    assert "--force" not in append_and_push_text


def test_machine_provisional_scheduler_uses_live_queue_and_race_checks():
    text = MACHINE_MATERIALIZATION.read_text(encoding="utf-8")

    assert "group: machine-provisional-materialization" in text
    assert "cancel-in-progress: false" in text
    assert "OPENVA_AUTOMERGE_TOKEN" in text
    assert "gh pr list --state open --label machine-provisional" in text
    assert "gh pr list --state open --label catalog-growth" in text
    assert "openva-bot-paused" in text
    assert "machine-provisional-paused" in text
    assert "recent bot PR limit blocks scheduled materialization" in text
    assert "existing candidate-promotion branch blocks scheduled materialization" in text
    assert "queue state changed before machine-provisional dispatch" in text
    assert "-f promotion_plan_mode=machine-provisional-from-queue" in text
    assert "-f max_promotion_actions_per_pr=1" in text


def test_autonomous_growth_is_the_single_scheduled_materialization_controller():
    autonomous_text = AUTONOMOUS_GROWTH.read_text(encoding="utf-8")
    materialization_text = MACHINE_MATERIALIZATION.read_text(encoding="utf-8")

    assert 'cron: "17 23 * * *"' in autonomous_text
    assert "07:17 Asia/Singapore" in autonomous_text
    assert "schedule:" not in materialization_text
    assert "workflow_dispatch:" in materialization_text


def test_sitemap_source_promotion_stays_in_candidate_promotion_control_plane():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    assert not Path(".github/workflows/sitemap-source-promotion-pr.yml").exists()
    assert "- sitemap-source-latest" in text
    assert '"sitemap-source-latest"' in text
    assert (
        "reviewed-path|strict-growth-latest|strict-growth-shortlist|sitemap-source-latest|"
        "machine-provisional-from-queue"
    ) in text


def test_candidate_promotion_wires_web_bot_auth_for_sitemap_fetches():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")
    job_env = text[text.index("env:") : text.index("steps:")]

    assert "OPENVA_WEB_BOT_AUTH_DIRECTORY_URL: ${{ secrets.OPENVA_WEB_BOT_AUTH_DIRECTORY_URL }}" in job_env
    assert "OPENVA_WEB_BOT_AUTH_PUBLIC_JWK_JSON: ${{ secrets.OPENVA_WEB_BOT_AUTH_PUBLIC_JWK_JSON }}" in job_env
    assert (
        "OPENVA_WEB_BOT_AUTH_PRIVATE_KEY_PEM_B64: ${{ secrets.OPENVA_WEB_BOT_AUTH_PRIVATE_KEY_PEM_B64 }}"
        in job_env
    )


def test_sitemap_source_mode_uses_existing_promotion_pipeline():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    sitemap = text.index("- name: Regenerate sitemap source promotion plan")
    viability = text.index("- name: Filter sitemap source promotion viability")
    stash = text.index("- name: Stash temporary sitemap candidate-source records")
    select = text.index("- name: Select candidate promotion plan")
    current_validate = text.index("- name: Validate current records")
    restore = text.index("- name: Restore temporary sitemap candidate-source records for apply")
    apply = text.index("- name: Apply candidate promotions")
    cleanup = text.index("- name: Remove temporary sitemap candidate-source records")
    rebuild = text.index("- name: Rebuild generated outputs")
    final_validate = text.index("- name: Validate generated catalog promotion")
    preflight = text.index("- name: Run source preflight for changed sources")
    observation_baseline = text.index("- name: Install source preflight observation baseline")
    pr_create = text.index("- name: Create or update pull request")

    assert sitemap < viability < stash < select < current_validate < restore < apply
    assert apply < cleanup < rebuild < final_validate < preflight < observation_baseline < pr_create
    block = text[sitemap:select]
    assert "python -m tools.openva.catalog_growth_discovery_queue run-sitemap-discovery \\" in block
    assert "from tools.openva.source_discovery import write_discovery_outputs" in block
    assert "write_discovery_outputs(" in block
    assert "python -m tools.openva.promotion_planner plan \\" in block
    assert "--discovery-report sitemap-source-discovery-report.json" in block
    assert 'action.get("action") == "promote_candidate_source_for_review"' in block
    assert "candidate_promotion_actions filter-reviewed-plan" in block
    assert '--max-actions "$MAX_PROMOTION_ACTIONS_PER_PR"' in block
    assert "sitemap-source-promotion-viability-report.json" in block
    assert "sitemap-source-promotion-plan.json" in block
    assert "candidate_promotion_actions apply" in text[select:cleanup]
    assert "sitemap-source-candidate-manifest.json" in text[cleanup:preflight]
    assert "openva-candidate-promotion-pr-sitemap-source-evidence" in text


def test_sitemap_source_temp_candidates_are_not_visible_to_current_record_validation():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    stash = text.index("- name: Stash temporary sitemap candidate-source records")
    current_validate = text.index("- name: Validate current records")
    restore = text.index("- name: Restore temporary sitemap candidate-source records for apply")
    apply = text.index("- name: Apply candidate promotions")

    stash_block = text[stash:current_validate]
    validate_block = text[current_validate:restore]
    restore_block = text[restore:apply]

    assert 'Path("reports") / "sitemap-source-temporary-candidates"' in stash_block
    assert "shutil.move(path.as_posix(), stash_path.as_posix())" in stash_block
    assert '"stashed_candidate_paths"' in stash_block
    assert '"temporary_candidate_stash_root"' in stash_block
    assert "python -m tools.openva.validate validate" in validate_block
    assert 'json.load(open("sitemap-source-promotion-plan.json", encoding="utf-8"))' in restore_block
    assert "viable_candidate_ids" in restore_block
    assert "if path.stem not in viable_candidate_ids" in restore_block
    assert "shutil.copy2(stash_path, path)" in restore_block


def test_sitemap_source_temp_candidates_are_cleaned_before_staging_and_pr_creation():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    cleanup = text.index("- name: Remove temporary sitemap candidate-source records")
    rebuild = text.index("- name: Rebuild generated outputs")
    final_validate = text.index("- name: Validate generated catalog promotion")
    catalog_changes = text.index("- name: Check whether catalog changes were produced")
    preflight = text.index("- name: Run source preflight for changed sources")
    observation_baseline = text.index("- name: Install source preflight observation baseline")
    commit = text.index("- name: Commit and push promotion branch")
    pr_create = text.index("- name: Create or update pull request")

    assert cleanup < rebuild < final_validate < catalog_changes < preflight < observation_baseline < commit < pr_create
    cleanup_block = text[cleanup:rebuild]
    assert "if: always() && env.PROMOTION_PLAN_MODE == 'sitemap-source-latest'" in cleanup_block
    assert "path.unlink()" in cleanup_block
    assert 'parent.name == "candidate_sources"' in cleanup_block
    assert "python -m tools.openva.validate build-indexes" in text[rebuild:final_validate]
    commit_block = text[commit:pr_create]
    assert "git add data indexes dist openva-pack.json" in commit_block
    assert "reports/sitemap-source-temporary-candidates" not in commit_block


def test_sitemap_source_final_validation_rebuild_and_preflight_run_before_pr_creation():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    apply = text.index("- name: Apply candidate promotions")
    cleanup = text.index("- name: Remove temporary sitemap candidate-source records")
    final_validate = text.index("- name: Validate generated catalog promotion")
    rebuild = text.index("- name: Rebuild generated outputs")
    catalog_changes = text.index("- name: Check whether catalog changes were produced")
    preflight = text.index("- name: Run source preflight for changed sources")
    observation_baseline = text.index("- name: Install source preflight observation baseline")
    pr_create = text.index("- name: Create or update pull request")

    assert apply < cleanup < rebuild < final_validate < catalog_changes < preflight < observation_baseline < pr_create
    assert "python -m tools.openva.validate build-indexes" in text[rebuild:final_validate]
    assert "python -m tools.openva.validate validate" in text[final_validate:catalog_changes]
    assert "python -m tools.openva.source_preflight check-changed-sources" in text[preflight:observation_baseline]
    assert "python -m tools.openva.observation_ledger install-latest" in text[observation_baseline:pr_create]


def test_sitemap_source_zero_actions_exits_without_pr_creation():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")
    select_start = text.index("- name: Select candidate promotion plan")
    stop = text.index("- name: Stop when no unapplied reviewed candidate promotion plan exists")
    validate = text.index("- name: Validate workflow inputs")
    select = text[select_start:validate]

    assert '[ "$PROMOTION_PLAN_MODE" = "sitemap-source-latest" ]' in select
    assert "GENERATED_PROMOTION_NO_ACTIONS=true" in select
    assert select_start < stop < validate
    assert "if: steps.reviewed_plan.outputs.HAS_REVIEWED_PLAN != 'true'" in text[stop:validate]
    assert "Generated promotion plan completed with zero selected promotion actions." in text
    assert "candidate_promotion_actions apply" not in text[stop:validate]


def test_sitemap_source_one_selected_action_path_restores_candidates_before_apply():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    filter_start = text.index('action.get("action") == "promote_candidate_source_for_review"')
    filter_end = text.index('Path("sitemap-source-promotion-plan.json").write_text')
    viability = text.index("- name: Filter sitemap source promotion viability")
    restore = text.index("- name: Restore temporary sitemap candidate-source records for apply")
    apply = text.index("- name: Apply candidate promotions")
    cleanup = text.index("- name: Remove temporary sitemap candidate-source records")
    rebuild = text.index("- name: Rebuild generated outputs")
    final_validate = text.index("- name: Validate generated catalog promotion")
    preflight = text.index("- name: Run source preflight for changed sources")
    observation_baseline = text.index("- name: Install source preflight observation baseline")
    pr_create = text.index("- name: Create or update pull request")
    filter_block = text[filter_start:filter_end]
    viability_block = text[viability:restore]

    assert "selected_promotion_action_count" in filter_block
    assert '"action_count": len(promote_actions)' in filter_block
    assert '"action_types": dict(sorted(counts.items()))' in filter_block
    assert "promote_actions[:max_actions]" not in filter_block
    assert '"viability_filter_pending": True' in filter_block
    assert '--max-actions "$MAX_PROMOTION_ACTIONS_PER_PR"' in viability_block
    assert restore < apply < cleanup < rebuild < final_validate < preflight < observation_baseline < pr_create


def test_sitemap_source_cap_is_applied_after_viability_filtering():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    sitemap = text.index("- name: Regenerate sitemap source promotion plan")
    viability = text.index("- name: Filter sitemap source promotion viability")
    select = text.index("- name: Select candidate promotion plan")
    raw_block = text[sitemap:viability]
    viability_block = text[viability:select]

    assert "selected_actions = promote_actions[:max_actions]" not in raw_block
    assert '"actions": promote_actions' in raw_block
    assert '"uncapped_action_count": len(promote_actions)' in raw_block
    assert "candidate_promotion_actions filter-reviewed-plan" in viability_block
    assert '--max-actions "$MAX_PROMOTION_ACTIONS_PER_PR"' in viability_block


def test_sitemap_source_evidence_artifacts_include_viability_report_even_without_catalog_changes():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    upload = text.index("- name: Upload sitemap source promotion evidence artifacts")
    strict_upload = text.index("- name: Upload strict-growth evidence artifacts")
    block = text[upload:strict_upload]

    assert "if: always() && env.PROMOTION_PLAN_MODE == 'sitemap-source-latest'" in block
    assert "sitemap-source-promotion-viability-report.json" in block


def test_non_sitemap_modes_keep_current_validation_before_apply_and_rebuild_before_final_validation():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")

    current_validate = text.index("- name: Validate current records")
    restore = text.index("- name: Restore temporary sitemap candidate-source records for apply")
    apply = text.index("- name: Apply candidate promotions")
    cleanup = text.index("- name: Remove temporary sitemap candidate-source records")
    rebuild = text.index("- name: Rebuild generated outputs")
    final_validate = text.index("- name: Validate generated catalog promotion")

    assert current_validate < restore < apply
    assert "env.PROMOTION_PLAN_MODE == 'sitemap-source-latest'" in text[restore:apply]
    assert "env.PROMOTION_PLAN_MODE == 'sitemap-source-latest'" in text[cleanup:rebuild]
    assert apply < cleanup < rebuild < final_validate


def test_agent_automerge_has_generated_catalog_lane_scoped_to_generated_prs():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")

    job = text[text.index("  generated-catalog:") : text.index("  machine-canonical:")]

    assert "schedule:" in text
    assert "workflow_run:" not in text
    assert 'cron: "*/10 * * * *"' in text
    assert "startsWith(github.event.pull_request.head.ref, 'agent-candidate-promotion-')" in job
    assert (
        "github.event.pull_request.title == 'Catalog: apply reviewed candidate source promotion'"
        in job
    )
    assert "github.event_name == 'pull_request'" in job
    assert "automerge:machine-canonical" not in job
    assert "automerge:strict-growth" not in job


def test_agent_automerge_generated_catalog_lane_uses_fail_closed_evaluator():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    job = text[text.index("  generated-catalog:") : text.index("  machine-canonical:")]

    pause = job.index("- name: Check generated catalog circuit breaker pause")
    collect = job.index("- name: Collect generated catalog PR metadata")
    classify = job.index("- name: Classify generated catalog PR paths before applying patch")
    apply = job.index("- name: Apply generated catalog PR patch as data")
    checks = job.index("- name: Wait for generated catalog required checks")
    preflight = job.index("- name: Run source preflight for changed sources")
    release_gates = job.index("- name: Run source-intelligence release gate")
    freshness = job.index("- name: Rebuild generated outputs and detect drift")
    eligibility = job.index("- name: Check generated catalog automerge eligibility")
    upload = job.index("- name: Upload generated catalog automerge eligibility report")
    merge = job.index("- name: Enable GitHub native auto-merge")

    assert pause < collect < classify < apply < checks < preflight < release_gates < freshness < eligibility < upload < merge
    assert "ref: main" in job
    assert "python -m tools.openva.generated_catalog_pr_risk --circuit-breaker-check-pause" in job
    assert "maintenance/generated/generated-catalog-circuit-breaker.json" in job
    assert "gh pr diff \"$PR_NUMBER\" --name-only > changed-files.txt" in job
    assert "gh pr diff \"$PR_NUMBER\" --patch > generated-catalog.patch" in job
    assert "python -m tools.openva.generated_catalog_pr_risk --paths-file changed-files.txt" in job
    assert "git apply --check --index --whitespace=nowarn generated-catalog.patch" in job
    assert "git apply --index --whitespace=nowarn generated-catalog.patch" in job
    assert "--verify-applied-paths" in job
    assert "applied-changed-files.txt" not in job
    assert "gh pr view \"$PR_NUMBER\" --json body --jq .body > pr-body.md" in job
    assert '"gh",\n                      "pr",\n                      "checks"' in job
    assert "python -m tools.openva.source_preflight check-changed-sources" in job
    assert "python -m tools.openva.release_gates check --profile pr" in job
    assert "python -m tools.openva.validate build-indexes" in job
    assert "generated-outputs-before-build.patch" in job
    assert "generated-outputs-after-build.patch" in job
    assert "cmp -s generated-outputs-before-build.patch generated-outputs-after-build.patch" in job
    assert "python -m tools.openva.generated_catalog_pr_risk \\" in job
    assert "--automerge-eligibility-from-files" in job
    assert "continue-on-error: true" in job
    assert "--metadata-file pr-metadata.json" in job
    assert "--checks-file pr-checks.json" in job
    assert "--github-output-file \"$GITHUB_OUTPUT\"" in job
    assert "$GITHUB_ENV" not in job
    assert "generated-catalog-automerge-eligibility.json" in job
    assert "gh pr merge \"$PR_NUMBER\" --auto --squash --delete-branch" in job
    assert "steps.generated_catalog_eligibility.outputs.eligible == 'true'" in job


def test_agent_automerge_rereviews_generated_catalog_on_schedule_after_checks_settle():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    job = text[text.index("  generated-catalog-rereview:") : text.index("  generated-catalog-circuit-breaker:")]

    resolve = job.index("- name: Resolve generated catalog PR awaiting re-evaluation")
    checkout = job.index("- uses: actions/checkout@v5")
    pause = job.index("- name: Check generated catalog circuit breaker pause")
    collect = job.index("- name: Collect generated catalog PR diff")
    classify = job.index("- name: Classify generated catalog PR paths before applying patch")
    apply = job.index("- name: Apply generated catalog PR patch as data")
    checks = job.index("- name: Collect generated catalog required checks")
    eligibility = job.index("- name: Check generated catalog automerge eligibility")
    upload = job.index("- name: Upload generated catalog automerge eligibility report")
    merge = job.index("- name: Enable GitHub native auto-merge")

    assert "if: github.event_name == 'schedule'" in job
    assert "REPO: ${{ github.repository }}" in job
    assert 'gh pr list --repo "$REPO" \\' in job
    assert 'gh pr view "$PR_NUMBER" --repo "$REPO" --json body --jq .body > pr-body.md' in job
    assert "--limit 50" in job
    assert "startswith(\"agent-candidate-promotion-\")" in job
    assert '[[ "$HEAD_REF" != agent-candidate-promotion-* ]]' in job
    assert 'Catalog: apply reviewed candidate source promotion' in job
    assert "ref: main" in job
    assert "python -m tools.openva.generated_catalog_pr_risk --circuit-breaker-check-pause" in job
    assert "head_sha" not in job
    assert "headRefOid" not in job
    assert "github.event.workflow_run.head_sha" not in job
    assert "github.event.pull_request.head.sha" not in job
    assert "gh pr diff \"$PR_NUMBER\" --name-only > changed-files.txt" in job
    assert "gh pr diff \"$PR_NUMBER\" --patch > generated-catalog.patch" in job
    assert "python -m tools.openva.generated_catalog_pr_risk --paths-file changed-files.txt" in job
    assert "git apply --check --index --whitespace=nowarn generated-catalog.patch" in job
    assert "git apply --index --whitespace=nowarn generated-catalog.patch" in job
    assert "--verify-applied-paths" in job
    assert "applied-changed-files.txt" not in job
    assert '"gh",\n                  "pr",\n                  "checks"' in job
    assert "python -m tools.openva.generated_catalog_pr_risk \\" in job
    assert "--automerge-eligibility-from-files" in job
    assert "continue-on-error: true" in job
    assert "$GITHUB_ENV" not in job
    assert "--github-output-file \"$GITHUB_OUTPUT\"" in job
    assert "steps.generated_catalog_rereview_eligibility.outputs.eligible == 'true'" in job
    assert resolve < checkout < pause < collect < classify < apply < checks < eligibility < upload < merge


def test_agent_automerge_has_trusted_main_generated_catalog_circuit_breaker():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    job = text[text.index("  generated-catalog-circuit-breaker:") : text.index("  machine-canonical:")]

    checkout = job.index("- uses: actions/checkout@v5")
    resolve = job.index("- name: Resolve latest merged generated catalog PR")
    validate = job.index("- name: Run post-merge validation")
    drift = job.index("- name: Rebuild generated outputs and detect post-merge drift")
    release_gate = job.index("- name: Run post-merge release gate")
    publication = job.index("- name: Collect publication status for generated catalog merge")
    automerge_evidence = job.index("- name: Resolve generated catalog automerge run evidence")
    evaluate = job.index("- name: Evaluate generated catalog circuit breaker")
    upload = job.index("- name: Upload generated catalog circuit breaker artifacts")
    write_pause = job.index("- name: Write generated catalog circuit breaker pause file")
    open_pr = job.index("- name: Open generated catalog circuit breaker remediation PR")
    fail_closed = job.index("- name: Fail closed when generated catalog circuit breaker pauses the lane")

    assert "if: github.event_name == 'schedule'" in job
    assert "ref: main" in job
    assert "github.event.pull_request.head.sha" not in job
    assert "$GITHUB_ENV" not in job
    assert "python -m tools.openva.validate validate" in job
    assert "python -m tools.openva.validate build-indexes" in job
    assert "python -m tools.openva.release_gates check --profile pr" in job
    assert "gh run list --branch main" in job
    assert "--workflow agent-automerge.yml" in job
    assert "--commit \"$SOURCE_HEAD_SHA\"" in job
    assert "generated-catalog-automerge-eligibility" in job
    assert "--expected-artifact-present true" not in job
    assert "--automerge-job-succeeded \"$MERGED\"" not in job
    assert "AUTOMERGE_JOB_SUCCEEDED" in job
    assert "EXPECTED_ARTIFACT_PRESENT" in job
    assert "python -m tools.openva.generated_catalog_pr_risk --circuit-breaker-evaluate" in job
    assert "python -m tools.openva.generated_catalog_pr_risk \\" in job
    assert "--circuit-breaker-write-pause-file" in job
    assert "maintenance/generated/generated-catalog-circuit-breaker.json" in job
    assert "git switch -c \"$BRANCH\"" in job
    assert "git add maintenance/generated/generated-catalog-circuit-breaker.json" in job
    assert "gh pr create \\" in job
    assert "generated-catalog-circuit-breaker.json" in job
    assert "generated-catalog-circuit-breaker.md" in job
    assert "steps.generated_catalog_circuit_breaker.outputs.pause_required == 'true'" in job
    assert checkout < resolve < validate < drift < release_gate < publication < automerge_evidence < evaluate < upload < write_pause < open_pr < fail_closed


def test_agent_automerge_circuit_breaker_does_not_make_code_policy_workflows_automerge_eligible():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    generated = text[text.index("  generated-catalog:") : text.index("  generated-catalog-rereview:")]
    circuit = text[text.index("  generated-catalog-circuit-breaker:") : text.index("  machine-canonical:")]

    assert "gh pr merge \"$PR_NUMBER\" --auto --squash --delete-branch" in generated
    assert "gh pr merge" not in circuit
    result = classify_generated_catalog_pr_risk(
        [
            ".github/workflows/agent-automerge.yml",
            "tools/openva/generated_catalog_pr_risk.py",
            "docs/operations/contracts/work-package-scope.yaml",
        ]
    )
    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK


def test_agent_automerge_circuit_breaker_uses_durable_pause_remediation_not_artifact_only():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    job = text[text.index("  generated-catalog-circuit-breaker:") : text.index("  machine-canonical:")]

    assert "Upload generated catalog circuit breaker artifacts" in job
    assert "Write generated catalog circuit breaker pause file" in job
    assert "Open generated catalog circuit breaker remediation PR" in job
    assert "--circuit-breaker-write-pause-file" in job
    assert "generated-catalog-circuit-breaker-pause-${SOURCE_PR:-unknown}-${SHORT_SHA}" in job
    assert "gh pr create \\" in job
    assert "git push --set-upstream origin \"$BRANCH\"" in job


def test_agent_automerge_pause_file_blocks_generated_catalog_and_rereview_attempts():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    generated = text[text.index("  generated-catalog:") : text.index("  generated-catalog-rereview:")]
    rereview = text[text.index("  generated-catalog-rereview:") : text.index("  generated-catalog-circuit-breaker:")]

    for job in (generated, rereview):
        assert "Check generated catalog circuit breaker pause" in job
        assert "python -m tools.openva.generated_catalog_pr_risk --circuit-breaker-check-pause" in job
        assert "maintenance/generated/generated-catalog-circuit-breaker.json" in job
        assert job.index("Check generated catalog circuit breaker pause") < job.index("Classify generated catalog PR paths before applying patch")


def test_agent_automerge_keeps_pending_required_checks_non_mergeable_until_rereview():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    job = text[text.index("  generated-catalog:") : text.index("  generated-catalog-rereview:")]

    assert '"pending" in buckets' in job
    assert 'return "pending"' in job
    assert "--checks-file pr-checks.json" in job
    assert "steps.generated_catalog_eligibility.outputs.eligible == 'true'" in job


def test_agent_automerge_generated_catalog_lane_uploads_eligibility_artifact():
    text = AGENT_AUTOMERGE.read_text(encoding="utf-8")
    job = text[text.index("  generated-catalog:") : text.index("  machine-canonical:")]
    upload = job[job.index("- name: Upload generated catalog automerge eligibility report") :]

    assert "if: always()" in upload
    assert "name: generated-catalog-automerge-eligibility" in upload
    assert "generated-catalog-automerge-eligibility.json" in upload
    assert "source-preflight-report.json" in upload
    assert "release-gates.json" in upload
    assert "pr-checks.json" in upload


def test_catalog_pr_guard_has_generated_catalog_fast_path():
    text = CATALOG_PR_GUARD.read_text(encoding="utf-8")

    classify = text.index("- name: Classify generated catalog fast path")
    quarantine = text.index("- name: Classify quarantine fast path")
    validate = text.index("- name: Validate current records")
    install_match = text.index("- name: Install match service test dependencies")
    tests = text.index("- name: Run tests")
    fast_path_block = text[classify:validate]

    assert classify < quarantine < validate < install_match < tests
    assert "is_generated_candidate_promotion_pr(branch, title)" in fast_path_block
    assert "GENERATED_CATALOG_WORK_PACKAGE" in fast_path_block
    assert "classify_generated_catalog_pr_risk(changed_paths)" in fast_path_block
    assert "GeneratedCatalogPrRiskClass.LOW_RISK" in fast_path_block
    assert "fast_path=true" in fast_path_block
    assert "fast_path=false" in fast_path_block
    assert "if: steps.generated_catalog_fast_path.outputs.fast_path != 'true' && steps.quarantine_fast_path.outputs.fast_path != 'true'" in text[validate:]
    assert 'pip install -e "services/openva_match_service[dev]"' in text[install_match:tests]


def test_catalog_pr_guard_has_quarantine_fast_path():
    text = CATALOG_PR_GUARD.read_text(encoding="utf-8")
    block = text[text.index("- name: Classify quarantine fast path") : text.index("- name: Validate current records")]

    assert "check_quarantine_pr_shape" in block
    assert "headRefName" in block
    assert "title" in block
    assert "body" in block
    assert "Source quarantine PR shape accepted" in block
    assert "deferring deep status-only checks to quarantine lane" in block


def test_catalog_pr_guard_fast_path_only_applies_to_generated_candidate_promotion_prs():
    text = CATALOG_PR_GUARD.read_text(encoding="utf-8")
    fast_path_block = text[
        text.index("- name: Classify generated catalog fast path") : text.index("- name: Validate current records")
    ]

    assert "headRefName" in fast_path_block
    assert "title" in fast_path_block
    assert "body" in fast_path_block
    assert "Catalog PR is not a generated candidate-promotion PR; using full guard path." in fast_path_block
    assert "Generated catalog PR must declare" in fast_path_block
    assert "Generated catalog PR is not LOW_RISK" in fast_path_block
