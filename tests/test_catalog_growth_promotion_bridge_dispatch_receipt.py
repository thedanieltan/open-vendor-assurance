"""Regression pins for catalog-growth promotion dispatch acknowledgement.

The bridge remains dispatch-only: it must target the existing candidate-promotion
workflow on main, prefer the repository's autonomous workflow token when configured,
and fail closed unless a new workflow_dispatch run is observed after the dispatch.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/catalog-growth-promotion-bridge.yml")
JOB = "catalog-growth-promotion-bridge"


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps() -> list[dict]:
    return load()["jobs"][JOB]["steps"]


def step_named(prefix: str) -> dict:
    return next(step for step in steps() if step.get("name", "").startswith(prefix))


def test_dispatch_targets_main_and_prefers_autonomous_token():
    dispatch = step_named("Dispatch existing strict-growth promotion workflow")
    run = dispatch["run"]
    env = dispatch["env"]

    assert dispatch["id"] == "dispatch"
    assert env["GH_TOKEN"] == "${{ github.token }}"
    assert env["OPENVA_AUTOMERGE_TOKEN"] == "${{ secrets.OPENVA_AUTOMERGE_TOKEN }}"
    assert 'DISPATCH_TOKEN="${OPENVA_AUTOMERGE_TOKEN:-$GH_TOKEN}"' in run
    assert 'GH_TOKEN="$DISPATCH_TOKEN" gh workflow run "$MUTATION_WORKFLOW" --ref main' in run
    assert 'promotion_plan_mode=$MODE' in run
    assert 'pr_title=Catalog: apply reviewed candidate source promotion' in run


def test_dispatch_records_a_pre_dispatch_watermark_and_target_head():
    run = step_named("Dispatch existing strict-growth promotion workflow")["run"]

    assert 'gh run list --workflow "$MUTATION_WORKFLOW" --branch main --event workflow_dispatch' in run
    assert "map(.databaseId) | max // 0" in run
    assert 'TARGET_HEAD_SHA="$(git rev-parse origin/main)"' in run
    assert 'REQUESTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"' in run
    assert 'echo "before_max=$BEFORE_MAX" >> "$GITHUB_OUTPUT"' in run
    assert 'echo "target_head_sha=$TARGET_HEAD_SHA" >> "$GITHUB_OUTPUT"' in run
    assert 'echo "requested_at=$REQUESTED_AT" >> "$GITHUB_OUTPUT"' in run


def test_dispatch_receipt_is_bounded_and_fail_closed():
    workflow = load()
    receipt = step_named("Verify promotion workflow dispatch receipt")
    run = receipt["run"]
    job_env = workflow["jobs"][JOB]["env"]

    assert job_env["DISPATCH_RECEIPT_WAIT_ATTEMPTS"] == "12"
    assert job_env["DISPATCH_RECEIPT_WAIT_SECONDS"] == "5"
    assert receipt.get("continue-on-error") in (None, False)
    assert "set -euo pipefail" in run
    assert 'gh run list --workflow "$MUTATION_WORKFLOW" --branch main --event workflow_dispatch' in run
    assert ".databaseId > $before" in run
    assert ".createdAt >= $requested" in run
    assert ".headSha == $head" in run
    assert 'sleep "$SLEEP_SECONDS"' in run
    assert "workflow dispatch returned without a verifiable candidate-promotion run; failing closed" in run
    assert "|| true" not in run
    assert "|| echo 0" not in run


def test_dispatch_receipt_is_bound_to_dispatch_outputs_and_authority_gates():
    receipt = step_named("Verify promotion workflow dispatch receipt")
    condition = str(receipt["if"])
    env = receipt["env"]

    assert "steps.eligibility.outputs.eligible == 'true'" in condition
    assert "steps.ancestry.outputs.ancestor == 'true'" in condition
    assert "steps.decide.outputs.dispatch == 'true'" in condition
    assert env["RUN_ID"] == "${{ steps.resolve.outputs.run_id }}"
    assert env["BEFORE_MAX"] == "${{ steps.dispatch.outputs.before_max }}"
    assert env["TARGET_HEAD_SHA"] == "${{ steps.dispatch.outputs.target_head_sha }}"
    assert env["REQUESTED_AT"] == "${{ steps.dispatch.outputs.requested_at }}"


def test_dispatch_receipt_is_uploaded_with_bridge_decision_artifacts():
    upload = step_named("Upload promotion bridge decision artifacts")
    receipt_run = step_named("Verify promotion workflow dispatch receipt")["run"]

    assert "reports/promotion-bridge-dispatch-receipt.json" in receipt_run
    assert "catalog_growth_promotion_bridge_dispatch_receipt" in receipt_run
    assert "source_discovery_run_id" in receipt_run
    assert "downstream_candidate_promotion_run_id" in receipt_run
    assert "reports/promotion-bridge-dispatch-receipt.json" in upload["with"]["path"]


def test_bridge_still_has_only_one_catalog_promotion_dispatch_call():
    promotion_steps = load()["jobs"][JOB]["steps"]
    run_text = "\n".join(str(step.get("run") or "") for step in promotion_steps)

    assert run_text.count("gh workflow run") == 1
    assert 'gh workflow run "$MUTATION_WORKFLOW" --ref main' in run_text
    assert "gh pr create" not in run_text
    assert "gh pr merge" not in run_text
    assert "git commit" not in run_text
    assert "git push" not in run_text
