"""Contract pins for the catalog-growth-promotion-bridge workflow (WP zero-install PR2).

These assert the structural guarantees of the discovery -> strict-growth promotion
handoff: the promotion job only auto-runs after a successful *scheduled* main-branch
discovery run, reads the upstream event from authoritative run metadata, fails closed via
the eligibility gate, waits boundedly for transient active promotion runs to drain,
re-checks promotion-run state before dispatch, dispatches the single existing mutation
workflow and nothing else, never writes catalog state or opens a PR, and is registered
consistently across the operating-model contracts. The workflow also hosts a separate
exact-gated Discovery Mesh acceptance-dispatch job; promotion-job assertions are scoped
to the promotion job so that independent authority boundary is not conflated with the
strict-growth handoff.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.discovery_promotion_bridge import DISPATCH_MODE, MUTATION_WORKFLOW

WORKFLOW = Path(".github/workflows/catalog-growth-promotion-bridge.yml")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")
WORKFLOW_RETIREMENT = Path("docs/operations/contracts/workflow-retirement.yaml")
OPERATING_MODEL = Path("docs/operations/WORKFLOW_OPERATING_MODEL.md")

NAME = "catalog-growth-promotion-bridge.yml"
JOB = "catalog-growth-promotion-bridge"


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def steps() -> list[dict]:
    return load()["jobs"][JOB]["steps"]


def step_named(prefix: str) -> dict:
    return next(s for s in steps() if s.get("name", "").startswith(prefix))


def promotion_job_run_text() -> str:
    return "\n".join(str(step.get("run") or "") for step in steps())


def inventory_entry() -> dict:
    entries = yaml.safe_load(WORKFLOW_INVENTORY.read_text(encoding="utf-8"))["public_workflows"]
    return next(entry for entry in entries if entry["name"] == NAME)


def retirement_entry() -> dict:
    entries = yaml.safe_load(WORKFLOW_RETIREMENT.read_text(encoding="utf-8"))["workflows"]
    return next(entry for entry in entries if entry["name"] == NAME)


def test_permissions_are_minimal_and_have_no_content_write():
    workflow = load()
    # Minimum required: actions:write (dispatch + run queries), read-only everything else.
    assert workflow["permissions"] == {
        "actions": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    assert workflow["permissions"]["contents"] == "read"


def test_triggers_on_discovery_completion_and_manual_exact_id():
    workflow = load()
    trig = triggers(workflow)
    body = text()
    assert set(trig.keys()) == {"workflow_run", "workflow_dispatch"}
    assert trig["workflow_run"]["workflows"] == ["catalog-growth-discovery", "discovery-mesh"]
    assert trig["workflow_run"]["types"] == ["completed"]
    # Manual dispatch must require an EXACT run id.
    assert trig["workflow_dispatch"]["inputs"]["discovery_run_id"]["required"] is True
    assert "github.event.workflow_run.id" in body


def test_job_level_guard_requires_successful_catalog_growth_workflow_run():
    guard = str(load()["jobs"][JOB]["if"])
    assert "github.event_name == 'workflow_dispatch'" in guard
    assert "github.event.workflow_run.name == 'catalog-growth-discovery'" in guard
    assert "github.event.workflow_run.conclusion == 'success'" in guard


def test_reads_upstream_event_from_authoritative_run_metadata():
    body = text()
    # The upstream event is read from gh run view --json (authoritative), not guessed.
    assert "gh run view" in body
    assert "--json conclusion,event,headBranch,headSha,workflowName" in body
    assert "upstream_event=" in body


def test_eligibility_gate_enforces_scheduled_only_authority_boundary():
    body = text()
    # The eligibility command is invoked with the bridge's own event and the upstream
    # discovery event, plus workflow name / conclusion / branch -- the Python gate
    # enforces "scheduled discovery only" on the automatic path (unit-tested).
    assert "python -m tools.openva.discovery_promotion_bridge eligibility" in body
    assert "--bridge-event" in body
    assert "--upstream-event" in body
    assert "--workflow-name" in body
    assert "--conclusion" in body
    assert "--head-branch" in body
    # The bridge passes its own event name through.
    assert "BRIDGE_EVENT: ${{ github.event_name }}" in body


def test_all_downstream_steps_are_gated_on_eligibility():
    gate = "steps.eligibility.outputs.eligible == 'true'"
    for prefix in (
        "Verify upstream commit",
        "Download strict-growth promotion plan",
        "Wait for active promotion lane",
        "Compute hold",
        "Decide promotion dispatch",
        "Dispatch existing strict-growth promotion workflow",
    ):
        assert gate in str(step_named(prefix)["if"]), prefix


def test_does_not_infer_a_latest_discovery_run():
    body = text()
    # The discovery run id comes only from the dispatch input or the workflow_run id;
    # the promotion job never lists discovery runs to pick a "latest" one. The separate
    # acceptance job may use a bounded --limit 100 query for deduplication.
    assert "--limit 1 " not in body
    assert "gh run list --workflow \"$DISCOVERY_WORKFLOW\"" not in body
    assert 'gh run list --workflow "$DISCOVERY_WORKFLOW"' not in body


def test_reads_strict_growth_plan_from_discovery_artifact():
    body = text()
    assert "--name openva-catalog-growth-discovery-artifacts" in body
    assert "strict-growth-promotion-plan.json" in body


def test_waits_boundedly_for_active_promotion_runs_scoped_to_main():
    workflow = load()
    wait = step_named("Wait for active promotion lane")
    wait_run = wait["run"]
    env = workflow["jobs"][JOB]["env"]
    assert env["PROMOTION_LANE_WAIT_ATTEMPTS"] == "30"
    assert env["PROMOTION_LANE_WAIT_SECONDS"] == "60"
    assert workflow["jobs"][JOB]["timeout-minutes"] == 45
    assert 'gh run list --workflow "$MUTATION_WORKFLOW" --branch main' in wait_run
    assert 'select(.status == "queued" or .status == "in_progress")' in wait_run
    assert "sleep \"$SLEEP_SECONDS\"" in wait_run
    assert "ATTEMPT<=ATTEMPTS" in wait_run
    assert "promotion lane remained active for the full bounded wait" in wait_run
    assert "refusing to drop or race the discovery handoff" in wait_run
    assert "|| echo 0" not in wait_run
    assert "|| true" not in wait_run
    assert "set -euo pipefail" in wait_run


def test_wait_precedes_final_active_run_recheck():
    names = [s.get("name", "") for s in steps()]
    wait_idx = next(i for i, n in enumerate(names) if n.startswith("Wait for active promotion lane"))
    state_idx = next(i for i, n in enumerate(names) if n.startswith("Compute hold"))
    assert wait_idx < state_idx

    state_run = step_named("Compute hold")["run"]
    # The post-wait query is retained as a race guard rather than treating the initial
    # contention observation as a terminal no-op.
    assert 'gh run list --workflow "$MUTATION_WORKFLOW" --branch main' in state_run
    assert 'select(.status == "queued" or .status == "in_progress")' in state_run
    assert "final fail-closed" in state_run
    assert "--active-promotion-run-count" in text()


def test_uses_decision_module_gate_with_all_state_inputs():
    body = text()
    assert "python -m tools.openva.discovery_promotion_bridge decide" in body
    assert "--hold-active" in body
    assert "--open-growth-pr-count" in body
    assert "--active-promotion-run-count" in body


def test_computes_hold_and_open_growth_pr_state():
    body = text()
    assert "openva-bot-paused" in body
    assert "--label catalog-growth" in body


def test_promotion_job_dispatches_only_the_existing_mutation_workflow():
    job_body = promotion_job_run_text()
    workflow = load()
    env = workflow["jobs"][JOB]["env"]
    assert env["MUTATION_WORKFLOW"] == MUTATION_WORKFLOW == "candidate-promotion-pr.yml"
    # The promotion job has exactly one workflow-dispatch call, targeting the single
    # canonical mutation workflow. A separate job may dispatch Discovery Mesh acceptance.
    assert job_body.count("gh workflow run") == 1
    assert 'gh workflow run "$MUTATION_WORKFLOW"' in job_body
    assert "gh workflow run discovery-mesh.yml" not in job_body
    assert "promotion_plan_mode=$MODE" in job_body
    assert DISPATCH_MODE == "strict-growth-latest"


def test_dispatch_is_gated_on_eligibility_ancestry_and_decision():
    dispatch_step = step_named("Dispatch existing")
    assert dispatch_step["if"] == (
        "steps.eligibility.outputs.eligible == 'true' "
        "&& steps.ancestry.outputs.ancestor == 'true' "
        "&& steps.decide.outputs.dispatch == 'true'"
    )


# ---------------------------------------------------------------------------
# Finding 1: mandatory fail-closed live-state queries
# ---------------------------------------------------------------------------


def test_live_state_step_has_no_fail_open_fallbacks():
    state_run = step_named("Compute hold")["run"]
    assert "|| echo 0" not in state_run
    assert "|| true" not in state_run
    assert "2>/dev/null" not in state_run
    assert "set -euo pipefail" in state_run


def test_live_state_counts_validated_as_non_negative_integers():
    state_run = step_named("Compute hold")["run"]
    # A non-negative-integer guard for each numeric query (paused issues, open growth
    # PRs, active promotion runs).
    assert state_run.count("*[!0-9]*") >= 3
    assert "invalid open growth PR count" in state_run
    assert "invalid active promotion run count" in state_run


def test_pause_state_queries_are_mandatory_and_fail_closed():
    state_run = step_named("Compute hold")["run"]
    assert "gh label list --json name" in state_run
    # JSON validated before interpretation; an indeterminate result stops the run.
    assert 'jq -e \'type == "array"\'' in state_run
    assert "could not determine pause label state" in state_run
    # No fallback that infers "not paused" from a failed query.
    assert "|| echo 0" not in state_run
    assert "|| true" not in state_run


def test_state_and_decide_and_ancestry_steps_have_no_continue_on_error():
    for prefix in ("Verify upstream commit", "Wait for active promotion lane", "Compute hold", "Decide promotion dispatch"):
        assert step_named(prefix).get("continue-on-error") in (None, False), prefix


def test_decide_consumes_state_outputs_so_state_failure_blocks_dispatch():
    decide_env = step_named("Decide promotion dispatch")["env"]
    assert decide_env["HOLD"] == "${{ steps.state.outputs.pause }}"
    assert decide_env["OPEN_GROWTH_PRS"] == "${{ steps.state.outputs.open_growth_prs }}"
    assert decide_env["ACTIVE_PROMOTION_RUNS"] == "${{ steps.state.outputs.active_promotion_runs }}"


# ---------------------------------------------------------------------------
# Finding 2: upstream commit ancestry validation
# ---------------------------------------------------------------------------


def test_head_sha_read_from_authoritative_run_metadata():
    body = text()
    assert "--json conclusion,event,headBranch,headSha,workflowName" in body
    assert "head_sha=" in body


def test_ancestry_step_fetches_main_and_uses_merge_base():
    ancestry_run = step_named("Verify upstream commit")["run"]
    assert "git fetch origin main" in ancestry_run
    assert 'git merge-base --is-ancestor "$HEAD_SHA" origin/main' in ancestry_run
    assert "is not an ancestor of current main" in ancestry_run


def test_ancestry_step_gated_on_eligibility_only():
    assert step_named("Verify upstream commit")["if"] == "steps.eligibility.outputs.eligible == 'true'"


def test_ancestry_check_precedes_artifact_download():
    names = [s.get("name", "") for s in steps()]
    ancestry_idx = next(i for i, n in enumerate(names) if n.startswith("Verify upstream commit"))
    download_idx = next(i for i, n in enumerate(names) if n.startswith("Download strict-growth"))
    assert ancestry_idx < download_idx


def test_download_state_decide_dispatch_gated_on_ancestry():
    gate = "steps.ancestry.outputs.ancestor == 'true'"
    for prefix in (
        "Download strict-growth promotion plan",
        "Wait for active promotion lane",
        "Compute hold",
        "Decide promotion dispatch",
        "Dispatch existing strict-growth promotion workflow",
    ):
        assert gate in str(step_named(prefix)["if"]), prefix


def test_no_latest_successful_run_fallback():
    body = text()
    assert "--limit 1 " not in body
    assert 'gh run list --workflow "$DISCOVERY_WORKFLOW"' not in body


def test_bridge_never_writes_catalog_or_opens_or_merges_prs():
    body = text()
    assert "gh pr create" not in body
    assert "gh pr merge" not in body
    assert "git commit" not in body
    assert "git push" not in body
    assert "data/vendors" not in body
    assert "indexes/" not in body
    assert "maintenance/candidates" not in body
    # candidate intake stays inert; the bridge must not touch its flag.
    assert "execution_wired" not in body


def test_records_source_run_provenance():
    # #594 aligned the dispatched PR title with the generated-catalog automerge lane,
    # so the discovery-run id no longer rides the PR title. Provenance now lives in the
    # bridge's own audit trail: the eligibility summary line, the step summary, and the
    # --source-run-id passed to the promotion planner.
    body = text()
    assert "bridged from discovery run $RUN_ID" not in body
    assert 'pr_title=Catalog: apply reviewed candidate source promotion' in body
    assert "Provenance remains in this step's audit and workflow summary" in body
    assert 'Discovery run \`$RUN_ID\`' in body
    assert '--source-run-id "$RUN_ID"' in body
    assert "GITHUB_STEP_SUMMARY" in body


def test_uses_node24_compatible_actions():
    body = text()
    assert "actions/checkout@v5" in body
    assert "actions/setup-python@v6" in body
    assert "actions/upload-artifact@v6" in body
    for stale in ("actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4"):
        assert stale not in body


def test_concurrency_serializes_without_cancelling_in_progress():
    workflow = load()
    assert workflow["concurrency"]["group"] == "catalog-growth-promotion-bridge"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_registered_in_workflow_inventory_as_dispatch_only():
    entry = inventory_entry()
    assert entry["loop"] == "catalog_growth"
    assert entry["status"] == "core"
    assert set(entry["triggers"]) == {"workflow_run", "workflow_dispatch"}
    assert entry["permissions"] == {
        "actions": "write",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    assert entry["creates_prs"] is False
    assert entry["merges_prs"] is False
    assert entry["writes_repository_state"] is False


def test_registered_in_workflow_retirement_as_active_core():
    entry = retirement_entry()
    assert entry["current_status"] == "active"
    assert entry["inventory_status"] == "core"
    assert entry["retirement_candidate"] is False
    assert entry["retirement_ready"] is False
    assert entry["must_not_retire_yet"] is True


def test_operating_model_documents_the_bridge_handoff():
    body = OPERATING_MODEL.read_text(encoding="utf-8")
    assert "catalog-growth-promotion-bridge.yml" in body
