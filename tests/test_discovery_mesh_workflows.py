from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = ROOT / ".github" / "workflows" / "discovery-mesh.yml"
BRIDGE = ROOT / ".github" / "workflows" / "discovery-mesh-promotion-bridge.yml"


def test_scheduled_discovery_mesh_processes_full_catalog_without_vendor_cap() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert 'cron: "37 3 * * *"' in text
    assert "scheduled discovery mesh must not define a catalog vendor cap" in text
    assert '--vendor-limit "$LIMIT"' in text
    assert "REQUESTED_VENDOR_LIMIT" in text
    assert "config/discovery-mesh.yaml" in text
    assert "matrix: ${{ fromJson(needs.plan.outputs.matrix) }}" in text
    assert "max-parallel: 32" in text


def test_mesh_bounds_are_explicitly_per_vendor_not_catalog_breadth() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "Resolve growth-oriented per-vendor bounds" in text
    assert '--max-pages "$MESH_MAX_PAGES"' in text
    assert '--max-total-requests "$MESH_MAX_TOTAL_REQUESTS"' in text
    assert "Catalog breadth was not capped" in text


def test_mesh_intake_stages_candidates_before_canonical_mutation() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "--write-candidates" in text
    assert "tools.openva.promotion_planner plan" in text
    assert "tools.openva.candidate_promotion_actions filter-reviewed-plan" in text
    assert 'title "Ops: stage discovery mesh candidates"' in text
    assert "candidate-promotion-pr.yml" in text
    assert "gh pr merge \"$PR_NUMBER\" --auto --squash --delete-branch" in text


def test_bridge_dispatches_existing_canonical_mutation_authority() -> None:
    text = BRIDGE.read_text(encoding="utf-8")

    assert "github.event.pull_request.merged == true" in text
    assert "agent-discovery-mesh-intake-" in text
    assert "Ops: stage discovery mesh candidates" in text
    assert "candidate-promotion-pr.yml" in text
    assert "promotion_plan_mode=reviewed-path" in text
    assert "strict-growth-discovery-mesh-" in text
    assert "Catalog breadth cap: none" in text


def test_bridge_requires_exactly_one_merged_plan() -> None:
    text = BRIDGE.read_text(encoding="utf-8")

    assert 'if [ "$COUNT" != "1" ]' in text
    assert "Expected exactly one discovery mesh promotion plan" in text
    assert "Discovery mesh plan contains zero viable actions" in text
