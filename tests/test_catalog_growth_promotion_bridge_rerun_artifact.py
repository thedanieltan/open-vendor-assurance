"""Regression pins for rerun-safe discovery artifact selection in the growth bridge."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/catalog-growth-promotion-bridge.yml")
JOB = "catalog-growth-promotion-bridge"


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def step_named(prefix: str) -> dict:
    return next(
        step
        for step in load()["jobs"][JOB]["steps"]
        if step.get("name", "").startswith(prefix)
    )


def test_run_metadata_captures_latest_attempt_boundary():
    step = step_named("Read discovery run metadata")
    run = step["run"]

    assert "--json attempt,conclusion,event,headBranch,headSha,startedAt,workflowName" in run
    assert 'echo "run_attempt=' in run
    assert 'echo "started_at=' in run


def test_artifact_download_is_bound_to_attempt_started_at():
    step = step_named("Download strict-growth promotion plan")
    env = step["env"]
    run = step["run"]

    assert env["RUN_ATTEMPT"] == "${{ steps.run_meta.outputs.run_attempt }}"
    assert env["ATTEMPT_STARTED_AT"] == "${{ steps.run_meta.outputs.started_at }}"
    assert "actions/runs/${RUN_ID}/artifacts?per_page=100" in run
    assert '.name == $name and .expired == false and .created_at >= $started' in run
    assert 'if [ "$MATCH_COUNT" != "1" ]' in run
    assert "expected exactly one discovery artifact for attempt" in run


def test_artifact_is_downloaded_by_exact_id_not_ambiguous_run_name():
    run = step_named("Download strict-growth promotion plan")["run"]

    assert "actions/artifacts/${ARTIFACT_ID}/zip" in run
    assert 'echo "artifact_id=$ARTIFACT_ID" >> "$GITHUB_OUTPUT"' in run
    assert 'gh run download "$RUN_ID"' not in run
    assert "--name openva-catalog-growth-discovery-artifacts" not in run


def test_artifact_selection_fails_closed_on_unbounded_or_ambiguous_sets():
    run = step_named("Download strict-growth promotion plan")["run"]

    assert "set -euo pipefail" in run
    assert 'if [ "$TOTAL_COUNT" -gt 100 ]' in run
    assert "refusing unpaginated selection" in run
    assert 'if [ "$MATCH_COUNT" != "1" ]' in run
    assert "|| true" not in run
    assert "|| echo" not in run


def test_existing_authority_and_dispatch_boundaries_remain():
    workflow = load()
    body = WORKFLOW.read_text(encoding="utf-8")

    assert workflow["permissions"] == {
        "actions": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    assert workflow["jobs"][JOB]["env"]["MUTATION_WORKFLOW"] == "candidate-promotion-pr.yml"
    assert body.count('gh workflow run "$MUTATION_WORKFLOW"') == 1
    assert "gh pr create" not in "\n".join(
        str(step.get("run") or "") for step in workflow["jobs"][JOB]["steps"]
    )
    assert "data/vendors" not in "\n".join(
        str(step.get("run") or "") for step in workflow["jobs"][JOB]["steps"]
    )
