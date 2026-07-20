from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "discovery-mesh-intake-recovery.yml"


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
    assert 'gh pr merge "$PR_NUMBER" --auto --squash --delete-branch' in text
    assert "candidate-promotion-pr.yml" in text
    assert "Canonical vendor/source mutation: false" in text
    assert "out-of-scope intake paths" in text
    assert "expected one staged partition plan" in text


def test_recovery_filters_only_exact_plan_referenced_candidates() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "INDEX(.key)" in text
    assert "candidate filter mismatch" in text
    assert "promotion candidates missing from candidate NDJSON" not in text
    assert "tools.openva.discovery_mesh_intake materialize" in text


def test_recovery_uses_bounded_repository_transactions_not_catalog_limits() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'default: "2500"' in text
    assert 'default: "25000000"' in text
    assert "The transaction budget partitions repository writes only." in text
    assert "It does not truncate catalog growth." in text
