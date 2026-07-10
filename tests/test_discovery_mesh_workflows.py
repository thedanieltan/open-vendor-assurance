from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = ROOT / ".github" / "workflows" / "discovery-mesh.yml"


def test_scheduled_discovery_mesh_processes_full_catalog_without_vendor_cap() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert 'cron: "37 3 * * *"' in text
    assert "scheduled discovery mesh must not define a catalog vendor cap" in text
    assert "matrix: ${{ fromJson(needs.plan.outputs.matrix) }}" in text
    assert "max-parallel: 32" in text
    assert '--vendor-limit "$LIMIT"' in text
    assert "Catalog breadth was not capped" in text


def test_mesh_uses_large_per_vendor_bounds_without_limiting_catalog_breadth() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "MAX_PAGES_PER_VENDOR" in text
    assert "MAX_TOTAL_REQUESTS_PER_VENDOR" in text
    assert "MAX_LOCATOR_CANDIDATES_PER_VENDOR" in text
    assert '--max-pages "$MESH_MAX_PAGES"' in text
    assert '--max-total-requests "$MESH_MAX_TOTAL_REQUESTS"' in text


def test_mesh_intake_uses_workflow_triggering_token_and_stages_candidates_only() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "OPENVA_AUTOMERGE_TOKEN || github.token" in text
    assert "--write-candidates" in text
    assert "candidate_promotion_actions filter-reviewed-plan" in text
    assert 'title "Ops: stage discovery mesh candidates"' in text
    assert "gh pr merge \"$PR_NUMBER\" --auto --squash --delete-branch" in text
    assert "sole canonical mutation authority" in text


def test_mesh_replenishes_stable_vendor_breadth_state_idempotently() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "vendor_breadth_replenishment build" in text
    assert '--relationship-report "$IDENTITY_REPORT"' in text
    assert '--existing-ledger "$LEDGER"' in text
    assert '--existing-queue "$QUEUE"' in text
    assert '--existing-candidates "$CANDIDATES"' in text
    assert '--existing-metrics "$METRICS"' in text
    assert 'LEDGER="maintenance/generated/vendor-breadth-signal-ledger.json"' in text
    assert 'QUEUE="maintenance/generated/vendor-breadth-resolution-queue.json"' in text
    assert 'CANDIDATES="maintenance/generated/vendor-breadth-candidates.json"' in text
    assert 'METRICS="maintenance/generated/vendor-breadth-provider-metrics.json"' in text
    assert "vendor-breadth-replenishment-run-" in text


def test_mesh_intake_persists_breadth_outputs_without_new_mutation_workflow() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "git add maintenance/generated/vendor-breadth-*.json" in text
    assert "maintenance/generated/vendor-breadth-*.json" in text
    assert "stable vendor-breadth ledger, resolution queue, candidate projection" in text
    assert "Provider signals are not catalog facts" in text
    assert "provider-replenished identities are not truncated by the curated seed target" in text


def test_merged_intake_handoff_dispatches_existing_canonical_mutation_workflow() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "promotion-handoff:" in text
    assert "github.event.pull_request.merged == true" in text
    assert "agent-discovery-mesh-intake-" in text
    assert "Ops: stage discovery mesh candidates" in text
    assert "candidate-promotion-pr.yml" in text
    assert "promotion_plan_mode=reviewed-path" in text
    assert "Catalog breadth cap: none" in text


def test_handoff_fails_closed_on_ambiguous_or_empty_plan() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert 'if [ "$COUNT" != "1" ]' in text
    assert "Expected exactly one discovery mesh promotion plan" in text
    assert "Discovery mesh plan contains zero viable actions" in text
