from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "discovery-mesh-intake-recovery.yml"
DISCOVERY = ROOT / ".github" / "workflows" / "discovery-mesh.yml"


def test_recovery_is_scoped_to_full_catalog_runs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflows: [discovery-mesh]" in text
    assert "github.event.workflow_run.event == 'schedule'" in text
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in text
    assert "github.event.workflow_run.event == 'push'" not in text
    assert "source_run_id" in text


def test_recovery_reuses_exact_aggregate_and_partitions_without_total_cap() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "openva-discovery-mesh-aggregate" in text
    assert "run-id: ${{ steps.source.outputs.run_id }}" in text
    assert "tools.openva.discovery_mesh_intake prepare" in text
    assert "Catalog vendor count cap: none" in text
    assert "Total candidate action cap: none" in text
    assert "transaction_max_files" in text
    assert "transaction_max_bytes" in text


def test_recovery_is_replay_safe_and_preserves_promotion_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'gh pr list --state all --head "$BRANCH"' in text
    assert "workflow-owned branch exists with unexpected commit" in text
    assert 'gh pr merge "$pr_number" --auto --squash --delete-branch' in text
    assert text.count('wait_for_mergeable_then_automerge "$PR_NUMBER"') == 2
    assert 'wait_for_mergeable_then_automerge "$EXISTING_PR_NUMBER"' in text
    assert "candidate-promotion-pr.yml" in text
    assert "Canonical vendor/source mutation: false" in text
    assert "out-of-scope intake paths" in text
    assert "expected one staged partition plan" in text


def test_generated_transactions_use_existing_operational_scope() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    declaration = "Work-Package: WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01"
    assert text.count(declaration) == 2
    assert "WP-DISCOVERY-MESH-INTAKE-RECOVERY-01" not in text
    assert '--title "$TITLE"' in text
    assert '"title": "Ops: stage discovery mesh candidates"' not in text


def test_recovery_filters_only_exact_plan_referenced_candidates() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "INDEX(.key)" in text
    assert "candidate filter mismatch" in text
    assert "tools.openva.discovery_mesh_intake materialize" in text


def test_recovery_uses_bounded_repository_transactions_not_catalog_limits() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'default: "2500"' in text
    assert 'default: "25000000"' in text
    assert "The transaction budget partitions repository writes only." in text
    assert "It does not truncate catalog growth." in text


def test_recovery_waits_for_mergeable_before_enabling_automerge() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "wait_for_mergeable_then_automerge()" in text
    assert 'gh pr view "$pr_number" --json mergeable --jq .mergeable' in text
    assert 'if [ "$mergeable" != "UNKNOWN" ]; then' in text
    assert 'EXISTING_STATE=$(jq -r \'.[0].state\' <<< "$EXISTING")' in text


def test_discovery_mesh_no_longer_attempts_monolithic_repository_intake() -> None:
    text = DISCOVERY.read_text(encoding="utf-8")

    assert "Record partitioned intake handoff" in text
    assert "Prepare exact intake branch" not in text
    assert "Open candidate-intake PR and enable native auto-merge" not in text
    assert "discovery-mesh-intake-recovery.yml" in text
