from pathlib import Path

from tools.openva.github_actions_artifacts import (
    select_latest_two_successful_runs,
    skipped_confirmed_p0_scan,
    write_github_env,
    write_github_output,
)


def run(run_id: int, created_at: str, *, status: str = "completed", conclusion: str = "success") -> dict:
    return {
        "databaseId": run_id,
        "status": status,
        "conclusion": conclusion,
        "createdAt": created_at,
        "updatedAt": created_at,
        "workflowName": "source-maintenance-report",
        "event": "schedule",
        "headBranch": "main",
    }


def test_latest_two_successful_maintenance_runs_are_selected_deterministically(tmp_path: Path):
    selection = select_latest_two_successful_runs(
        [
            run(100, "2026-05-01T00:00:00Z"),
            run(102, "2026-05-03T00:00:00Z", conclusion="failure"),
            run(101, "2026-05-02T00:00:00Z"),
            run(103, "2026-05-04T00:00:00Z", status="in_progress", conclusion=""),
        ],
        generated_at="2026-05-05T00:00:00Z",
    )

    assert selection["status"] == "selected"
    assert selection["prior_run_id"] == "100"
    assert selection["fresh_run_id"] == "101"
    assert selection["summary"] == {
        "input_run_count": 4,
        "successful_completed_run_count": 2,
        "selected_run_count": 2,
    }

    github_output = tmp_path / "github-output.txt"
    github_env = tmp_path / "github-env.txt"
    write_github_output(selection, github_output)
    write_github_env(selection, github_env)

    assert "has_history=true" in github_output.read_text(encoding="utf-8")
    assert "prior_run_id=100" in github_output.read_text(encoding="utf-8")
    assert "fresh_run_id=101" in github_output.read_text(encoding="utf-8")
    assert "SOURCE_REFINEMENT_HAS_HISTORY=true" in github_env.read_text(encoding="utf-8")
    assert "PRIOR_RUN_ID=100" in github_env.read_text(encoding="utf-8")
    assert "FRESH_RUN_ID=101" in github_env.read_text(encoding="utf-8")


def test_insufficient_history_does_not_fail_scheduled_scan():
    selection = select_latest_two_successful_runs(
        [run(100, "2026-05-01T00:00:00Z")],
        generated_at="2026-05-05T00:00:00Z",
    )
    skipped = skipped_confirmed_p0_scan(selection)

    assert selection["status"] == "insufficient_history"
    assert selection["reason"] == "fewer_than_two_successful_completed_source_maintenance_runs"
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "fewer_than_two_successful_completed_source_maintenance_runs"
    assert skipped["confirmed_p0"] == []
    assert skipped["summary"]["confirmed_p0_count"] == 0
    assert skipped["posture"]["mutates_catalog"] is False
