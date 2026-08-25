from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / ".github" / "workflows" / "candidate-promotion-pr.yml"
BRIDGE = ROOT / ".github" / "workflows" / "catalog-growth-promotion-bridge.yml"


def candidate_text() -> str:
    return CANDIDATE.read_text(encoding="utf-8")


def bridge_text() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def artifact_step() -> str:
    body = candidate_text()
    start = body.index("- name: Load artifact-bound strict-growth evidence")
    end = body.index("- name: Regenerate strict-growth promotion plan", start)
    return body[start:end]


def test_artifact_bound_mode_is_explicit_and_has_read_only_actions_access():
    body = candidate_text()
    assert "- strict-growth-artifact" in body
    assert "actions: read" in body
    assert "SOURCE_DISCOVERY_RUN_ID" in body
    assert "SOURCE_DISCOVERY_ARTIFACT_ID" in body
    assert "SOURCE_DISCOVERY_PLAN_DIGEST" in body


def test_artifact_bound_mode_binds_exact_run_artifact_and_plan_digest():
    step = artifact_step()
    assert "gh run view \"$SOURCE_DISCOVERY_RUN_ID\"" in step
    assert "actions/artifacts/${SOURCE_DISCOVERY_ARTIFACT_ID}" in step
    assert '.workflow_run.id // 0' in step
    assert 'ACTUAL_PLAN_DIGEST="sha256:' in step
    assert '[ "$ACTUAL_PLAN_DIGEST" = "$SOURCE_DISCOVERY_PLAN_DIGEST" ]' in step
    assert 'schedule|workflow_dispatch' in step
    assert 'artifact-bound promotion source event is not authorized' in step
    assert 'DISCOVERY_BRANCH" = "main"' in step
    assert "git merge-base --is-ancestor" in step


def test_artifact_bound_mode_does_not_repeat_network_discovery():
    step = artifact_step()
    assert "source_discovery discover-vendor-candidates" not in step
    assert "vendor_candidate_discovery discover" not in step
    assert "catalog_growth_eligibility classify" in step
    assert "catalog_growth_backlog build" in step
    assert "strict_growth_shortlist build" in step
    assert "--max-vendors 5" in step
    assert "strict_growth_shortlist plan" in step


def test_artifact_bound_revalidation_preserves_original_evidence_clock():
    step = artifact_step()
    assert "SOURCE_EVIDENCE_GENERATED_AT" in step
    assert 'payload["generated_at"] = source_time' in step
    assert 'payload["artifact_bound_source"] = binding' in step


def test_existing_strict_growth_and_source_preflight_gates_cover_artifact_mode():
    body = candidate_text()
    assert "env.PROMOTION_PLAN_MODE == 'strict-growth-artifact'" in body
    assert "strict_growth_automerge check-plan" in body
    assert "source_preflight check-changed-sources" in body
    assert "release_gates check --profile pr" in body


def test_bridge_dispatches_exact_artifact_binding_to_single_mutation_workflow():
    body = bridge_text()
    assert 'promotion_plan_mode=$MODE' in body
    assert 'discovery_run_id=$RUN_ID' in body
    assert 'discovery_artifact_id=$ARTIFACT_ID' in body
    assert 'discovery_plan_digest=$PLAN_DIGEST' in body
    assert "candidate-promotion-pr.yml" in body
    assert "gh pr create" not in body
    assert "git push" not in body


def test_bridge_receipt_records_source_binding():
    body = bridge_text()
    assert '"source_discovery_artifact_id": os.environ["SOURCE_ARTIFACT_ID"]' in body
    assert '"source_discovery_plan_digest": os.environ["SOURCE_PLAN_DIGEST"]' in body
