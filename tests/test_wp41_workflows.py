from pathlib import Path


AUTONOMOUS_GROWTH = Path(".github/workflows/autonomous-catalog-growth.yml")
DISCOVERY_LEDGER = Path(".github/workflows/discovery-ledger-append-pr.yml")
MACHINE_MATERIALIZATION = Path(".github/workflows/machine-provisional-materialization.yml")
CANDIDATE_PROMOTION = Path(".github/workflows/candidate-promotion-pr.yml")


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
    pr_create = text.index("- name: Create or update pull request")

    assert sitemap < viability < stash < select < current_validate < restore < apply
    assert apply < cleanup < rebuild < final_validate < preflight < pr_create
    block = text[sitemap:select]
    assert "python -m tools.openva.catalog_growth_discovery_queue run-sitemap-discovery \\" in block
    assert "from tools.openva.source_discovery import write_discovery_outputs" in block
    assert "write_discovery_outputs(" in block
    assert "python -m tools.openva.promotion_planner plan \\" in block
    assert "--discovery-report sitemap-source-discovery-report.json" in block
    assert 'action.get("action") == "promote_candidate_source_for_review"' in block
    assert "candidate_promotion_actions filter-reviewed-plan" in block
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
    commit = text.index("- name: Commit and push promotion branch")
    pr_create = text.index("- name: Create or update pull request")

    assert cleanup < rebuild < final_validate < catalog_changes < preflight < commit < pr_create
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
    pr_create = text.index("- name: Create or update pull request")

    assert apply < cleanup < rebuild < final_validate < catalog_changes < preflight < pr_create
    assert "python -m tools.openva.validate build-indexes" in text[rebuild:final_validate]
    assert "python -m tools.openva.validate validate" in text[final_validate:catalog_changes]
    assert "python -m tools.openva.source_preflight check-changed-sources" in text[preflight:pr_create]


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
    restore = text.index("- name: Restore temporary sitemap candidate-source records for apply")
    apply = text.index("- name: Apply candidate promotions")
    cleanup = text.index("- name: Remove temporary sitemap candidate-source records")
    rebuild = text.index("- name: Rebuild generated outputs")
    final_validate = text.index("- name: Validate generated catalog promotion")
    preflight = text.index("- name: Run source preflight for changed sources")
    pr_create = text.index("- name: Create or update pull request")
    filter_block = text[filter_start:filter_end]

    assert "selected_promotion_action_count" in filter_block
    assert '"action_count": len(selected_actions)' in filter_block
    assert '"action_types": dict(sorted(counts.items()))' in filter_block
    assert "promote_actions[:max_actions]" in filter_block
    assert restore < apply < cleanup < rebuild < final_validate < preflight < pr_create


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
