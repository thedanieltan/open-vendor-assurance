from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_queue import main

WORKFLOW_DIR = Path(".github/workflows")
SOURCE_REPAIR = WORKFLOW_DIR / "source-repair-pr.yml"
CATALOG_PROMOTION = WORKFLOW_DIR / "candidate-promotion-pr.yml"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_steps(path: Path) -> list[dict]:
    workflow = load_yaml(path)
    job = workflow["jobs"][path.stem]
    return job["steps"]


def step_index(steps: list[dict], name: str) -> int:
    for index, step in enumerate(steps):
        if step.get("name") == name:
            return index
    raise AssertionError(f"missing workflow step: {name}")


def artifact_paths(steps: list[dict], artifact_name: str) -> set[str]:
    for step in steps:
        if step.get("uses") != "actions/upload-artifact@v6":
            continue
        if step.get("with", {}).get("name") != artifact_name:
            continue
        raw_path = step.get("with", {}).get("path", "")
        return {line.strip() for line in str(raw_path).splitlines() if line.strip()}
    raise AssertionError(f"missing artifact: {artifact_name}")


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_source_repair_queue_gate_runs_before_branch_push_and_pr_creation():
    steps = workflow_steps(SOURCE_REPAIR)

    evaluate = step_index(steps, "Evaluate source repair queue gate")
    enforce = step_index(steps, "Enforce source repair queue gate")
    branch_push = step_index(steps, "Commit and push source repair branch")
    pr_create = step_index(steps, "Create or update pull request")

    assert evaluate < enforce < branch_push < pr_create
    assert "--lane source_repair" in SOURCE_REPAIR.read_text(encoding="utf-8")


def test_catalog_promotion_queue_gate_runs_before_preflight_branch_push_and_pr_creation():
    steps = workflow_steps(CATALOG_PROMOTION)

    evaluate = step_index(steps, "Evaluate catalog promotion queue gate")
    enforce = step_index(steps, "Enforce catalog promotion queue gate")
    preflight = step_index(steps, "Run source preflight for changed sources")
    branch_push = step_index(steps, "Commit and push promotion branch")
    pr_create = step_index(steps, "Create or update pull request")

    assert evaluate < enforce < preflight < branch_push < pr_create
    assert "--lane catalog_growth_promotion" in CATALOG_PROMOTION.read_text(encoding="utf-8")


def test_queue_gate_workflows_keep_existing_minimal_write_permissions():
    assert load_yaml(SOURCE_REPAIR)["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }
    assert load_yaml(CATALOG_PROMOTION)["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }


def test_queue_state_declares_workflow_fallback_and_report_only_live_checks():
    for path in (SOURCE_REPAIR, CATALOG_PROMOTION):
        text = path.read_text(encoding="utf-8")
        assert '"state_source": "workflow_local_fallback"' in text
        assert '"fallback_state": True' in text
        assert '"live_state_checks_report_only"' in text
        assert '"max_open_prs"' in text
        assert '"recent_bot_prs_per_day"' in text
        assert '"recent_bot_prs_per_week"' in text


def test_queue_gate_uploads_state_json_report_json_and_markdown_artifacts():
    source_paths = artifact_paths(workflow_steps(SOURCE_REPAIR), "openva-source-repair-queue-report")
    promotion_paths = artifact_paths(
        workflow_steps(CATALOG_PROMOTION), "openva-catalog-promotion-queue-report"
    )

    assert source_paths == {
        "reports/openva-queue/source-repair-queue-state.json",
        "reports/openva-queue/source-repair-queue-report.json",
        "reports/openva-queue/source-repair-queue-report.md",
    }
    assert promotion_paths == {
        "reports/openva-queue/catalog-promotion-queue-state.json",
        "reports/openva-queue/catalog-promotion-queue-report.json",
        "reports/openva-queue/catalog-promotion-queue-report.md",
    }


def test_queue_gate_hard_stops_on_denied_paused_stale_or_missing_authority_conditions():
    required = {
        "unknown_lane",
        "lane_missing_queue_policy",
        "lane_not_deny_by_default",
        "lane_not_write_capable",
        "missing_evidence",
        "stale_evidence",
        "pause_switch_active",
        "max_open_prs_exceeded",
        "max_bot_prs_per_day_exceeded",
        "max_bot_prs_per_week_exceeded",
    }
    for path in (SOURCE_REPAIR, CATALOG_PROMOTION):
        text = path.read_text(encoding="utf-8")
        assert "workflow_local_fallback" in text
        assert "report.get(\"decision\") in {\"deny\", \"pause\"}" in text
        for reason in required:
            assert reason in text


def test_queue_gate_does_not_dispatch_workflows_or_add_automerge_behavior():
    for path in (SOURCE_REPAIR, CATALOG_PROMOTION):
        text = path.read_text(encoding="utf-8")
        assert "actions/workflows" not in text
        assert "workflow_dispatches" not in text
        assert "enable-auto-merge" not in text
        assert "agent-automerge" not in text


def test_queue_integration_preserves_openva_terms():
    source_text = SOURCE_REPAIR.read_text(encoding="utf-8")
    promotion_text = CATALOG_PROMOTION.read_text(encoding="utf-8")

    assert "reviewed evidence" in source_text
    assert "strict-growth" in promotion_text
    assert "promotion actions" in promotion_text
    assert "candidate promotion" in promotion_text


def test_queue_markdown_report_cli_is_deterministic(tmp_path):
    state_path = tmp_path / "queue-state.json"
    out_json = tmp_path / "queue-report.json"
    out_md = tmp_path / "queue-report.md"
    state = {
        "version": 1,
        "lane_id": "source_repair",
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "evidence": {"generated_at": "2026-06-07T11:00:00Z"},
        "pause": {"active": False},
        "requested_action": {"duplicate_key": "repair-001"},
    }
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    first = main(
        [
            "evaluate",
            "--lane",
            "source_repair",
            "--state",
            str(state_path),
            "--out",
            str(out_json),
            "--out-md",
            str(out_md),
            "--now",
            "2026-06-07T12:00:00Z",
        ]
    )
    first_json = out_json.read_text(encoding="utf-8")
    first_md = out_md.read_text(encoding="utf-8")
    second = main(
        [
            "evaluate",
            "--lane",
            "source_repair",
            "--state",
            str(state_path),
            "--out",
            str(out_json),
            "--out-md",
            str(out_md),
            "--now",
            "2026-06-07T12:00:00Z",
        ]
    )

    assert first == 0
    assert second == 0
    assert out_json.read_text(encoding="utf-8") == first_json
    assert out_md.read_text(encoding="utf-8") == first_md
    assert "# OpenVA Bot Queue Decision" in first_md


def test_queue_integration_does_not_mutate_catalog_data():
    before = data_vendor_digest()

    for path in (SOURCE_REPAIR, CATALOG_PROMOTION):
        load_yaml(path)

    assert data_vendor_digest() == before
