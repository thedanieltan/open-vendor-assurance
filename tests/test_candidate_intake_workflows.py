"""WP-OPENVA-CANDIDATE-ACTIVATION-01 workflow + authority contract tests.

Covers the producer (candidate-intake-pr.yml), the consuming agent-automerge
candidate-intake lane, the candidate-bound mutation job in candidate-promotion-pr.yml,
and the candidate_intake authority lane.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PRODUCER = Path(".github/workflows/candidate-intake-pr.yml")
AUTOMERGE = Path(".github/workflows/agent-automerge.yml")
PROMOTION = Path(".github/workflows/candidate-promotion-pr.yml")
GROWTH = Path(".github/workflows/autonomous-catalog-growth.yml")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(wf):
    return wf.get("on") or wf.get(True)


# --- producer: candidate-intake-pr.yml --------------------------------------


def test_producer_is_dispatch_driven_with_workflow_triggering_token():
    wf = _load(PRODUCER)
    triggers = _on(wf)
    assert set(triggers.keys()) == {"workflow_dispatch"}
    assert wf["permissions"] == {"contents": "write", "pull-requests": "write"}
    text = PRODUCER.read_text(encoding="utf-8")
    # External boundary: a workflow-triggering token so the candidate-intake
    # automerge lane runs (not the default GITHUB_TOKEN alone).
    assert "secrets.OPENVA_AUTOMERGE_TOKEN || github.token" in text


def test_producer_stages_via_canonical_ingress_and_labels():
    text = PRODUCER.read_text(encoding="utf-8")
    assert "tools.openva.vendor_resolution resolve" in text
    assert "--enqueue" in text
    assert "--add-label \"candidate-intake\"" in text
    assert "--add-label \"automerge:candidate-intake\"" in text


def test_producer_is_path_confined_and_never_writes_catalog_or_merges():
    text = PRODUCER.read_text(encoding="utf-8")
    assert "maintenance/candidates" in text
    # never canonical truth, never a merge from the producer
    assert "git add data" not in text
    assert "gh pr merge" not in text


# --- consumer: agent-automerge candidate-intake lane ------------------------


def test_automerge_candidate_intake_job_is_label_gated():
    wf = _load(AUTOMERGE)
    job = wf["jobs"]["candidate-intake"]
    cond = job["if"]
    assert "candidate-intake" in cond
    assert "automerge:candidate-intake" in cond


def test_automerge_candidate_intake_checks_out_pr_head():
    wf = _load(AUTOMERGE)
    steps = wf["jobs"]["candidate-intake"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"


def test_automerge_candidate_intake_guards_and_recomputes_before_merge():
    steps = _load(AUTOMERGE)["jobs"]["candidate-intake"]["steps"]
    names = [s.get("name", "") for s in steps]
    text = "\n".join(yaml.safe_dump(s) for s in steps)
    assert "tools.openva.candidate_intake_guard" in text
    assert "tools.openva.candidate_activation verify-intake" in text
    assert "release_gates check --profile pr" in text
    merge_idx = next(i for i, n in enumerate(names) if "auto-merge" in n.lower())
    guard_idx = next(i for i, n in enumerate(names) if "guard" in n.lower())
    recompute_idx = next(i for i, n in enumerate(names) if "Recompute" in n)
    assert guard_idx < merge_idx
    assert recompute_idx < merge_idx


# --- candidate-bound mutation job in candidate-promotion-pr.yml -------------


def test_promotion_main_job_skips_candidate_bound_mode():
    wf = _load(PROMOTION)
    condition = wf["jobs"]["candidate-promotion-pr"]["if"]

    for mode in (
        "reviewed-path",
        "strict-growth-latest",
        "strict-growth-shortlist",
        "machine-provisional-from-queue",
    ):
        assert mode in condition

    for mode in (
        "candidate-bound",
        "quarantine",
        "rollback",
        "quorum-promotion",
    ):
        assert mode not in condition

    assert "!= 'candidate-bound'" not in condition


def test_candidate_bound_job_is_mode_gated_with_binding_inputs():
    wf = _load(PROMOTION)
    triggers_inputs = _on(wf)["workflow_dispatch"]["inputs"]
    for field in ("candidate_id", "candidate_path", "content_digest", "selected_vendor", "candidate_origin"):
        assert field in triggers_inputs
    job = wf["jobs"]["candidate-bound-materialization"]
    assert "candidate-bound" in job["if"]


def test_candidate_bound_job_materializes_and_verifies_before_pr():
    steps = _load(PROMOTION)["jobs"]["candidate-bound-materialization"]["steps"]
    names = [s.get("name", "") for s in steps]
    text = "\n".join(yaml.safe_dump(s) for s in steps)
    assert "tools.openva.candidate_activation materialize" in text
    assert "tools.openva.candidate_activation verify" in text
    assert "--add-label machine-provisional" in text
    materialize_idx = next(i for i, n in enumerate(names) if "Materialize" in n)
    pr_idx = next(i for i, n in enumerate(names) if "Create pull request" in n)
    assert materialize_idx < pr_idx
    # never a self-merge from the mutation job
    assert "gh pr merge" not in text


# --- candidate_intake authority lane ----------------------------------------


def test_candidate_intake_authority_lane_is_level1_stager():
    lanes = {lane["id"]: lane for lane in _load(BOT_AUTHORITY)["lanes"]}
    lane = lanes["candidate_intake"]
    assert lane["authority_level"] == 1
    assert lane["may_write_catalog_truth"] is False
    assert lane["may_merge_prs"] is False
    assert lane["deny_by_default"] is True
    assert lane["allowed_paths"] == ["maintenance/candidates/**"]
    # The producer opens/labels the PR; agent-automerge merges it (pr_safety
    # holds the merge authority). Both workflows participate in the lane.
    assert "candidate-intake-pr.yml" in lane["workflows"]
    assert "agent-automerge.yml" in lane["workflows"]
