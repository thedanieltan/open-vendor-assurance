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
    select = text.index("- name: Select candidate promotion plan")
    apply = text.index("- name: Apply candidate promotions")
    cleanup = text.index("- name: Remove temporary sitemap candidate-source records")
    preflight = text.index("- name: Run source preflight for changed sources")

    assert sitemap < select < apply < cleanup < preflight
    block = text[sitemap:select]
    assert "python -m tools.openva.catalog_growth_discovery_queue run-sitemap-discovery \\" in block
    assert "from tools.openva.source_discovery import write_discovery_outputs" in block
    assert "write_discovery_outputs(" in block
    assert "python -m tools.openva.promotion_planner plan \\" in block
    assert "--discovery-report sitemap-source-discovery-report.json" in block
    assert 'action.get("action") == "promote_candidate_source_for_review"' in block
    assert "sitemap-source-promotion-plan.json" in block
    assert "candidate_promotion_actions apply" in text[select:cleanup]
    assert "sitemap-source-candidate-manifest.json" in text[cleanup:preflight]
    assert "openva-candidate-promotion-pr-sitemap-source-evidence" in text


def test_sitemap_source_zero_actions_exits_without_pr_creation():
    text = CANDIDATE_PROMOTION.read_text(encoding="utf-8")
    select = text[text.index("- name: Select candidate promotion plan") : text.index("- name: Validate workflow inputs")]

    assert '[ "$PROMOTION_PLAN_MODE" = "sitemap-source-latest" ]' in select
    assert "GENERATED_PROMOTION_NO_ACTIONS=true" in select
    assert "Generated promotion plan completed with zero selected promotion actions." in text
