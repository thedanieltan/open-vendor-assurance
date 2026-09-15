from pathlib import Path

import yaml
import subprocess
import sys


VALIDATE = Path(".github/workflows/validate.yml")
WORKSPACE_DOC = Path("docs/operations/OPENVA_WORKSPACE.md")
OWNERSHIP = Path(".github/validation-ownership.yaml")


def load_validate() -> dict:
    return yaml.safe_load(VALIDATE.read_text(encoding="utf-8"))


def test_regression_shards_cover_every_test_file_once(monkeypatch) -> None:
    job = load_validate()["jobs"]["full-regression-shards"]
    step = next(s for s in job["steps"] if s.get("name") == "Run sharded regression tests")
    script = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    for shard in job["strategy"]["matrix"]["include"]:
        monkeypatch.setenv("REGRESSION_SHARD", shard["shard"])
        exec(compile(script, "regression-shard", "exec"), {})
    selected = []
    for args, kwargs in calls:
        assert args[:4] == [sys.executable, "-m", "pytest", "-q"]
        assert kwargs == {"check": True}
        selected.extend(args[4:])
    assert len(selected) == len(set(selected))
    assert set(selected) == {p.as_posix() for p in Path("tests").rglob("test_*.py")}
    remaining = next(s for s in job["strategy"]["matrix"]["include"] if s["shard"] == "remaining-unit")
    assert remaining["install_mcp"] and remaining["install_match_service"]


def test_targeted_mcp_ci_executes_oci_smoke() -> None:
    job = load_validate()["jobs"]["mcp-integration"]
    commands = "\n".join(s.get("run", "") for s in job["steps"])
    assert "tests/test_openva_mcp_oci.py" in commands
    assert "docker info" in commands


def test_workspace_required_context_is_a_delegating_aggregator() -> None:
    workflow = load_validate()
    job = workflow["jobs"]["workspace-affected-tests"]

    assert workflow["permissions"] == {"contents": "read"}
    assert job["needs"] == [
        "pr-change-classifier",
        "workspace-plan",
        "workspace-component-tests",
        "full-regression-shards",
    ]
    assert "always()" in job["if"]
    assert "workspace_affected == 'true'" in job["if"]
    text = VALIDATE.read_text(encoding="utf-8")
    assert "Full-suite plan validated by parallel regression shards." in text
    assert "Targeted plan validated by component-scoped tests." in text


def test_workspace_plan_uses_full_history_and_real_pr_base_head() -> None:
    workflow = load_validate()
    job = workflow["jobs"]["workspace-plan"]
    text = VALIDATE.read_text(encoding="utf-8")

    assert job["needs"] == "pr-change-classifier"
    assert job["outputs"]["full_suite"] == "${{ steps.plan.outputs.full_suite }}"
    checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v5")
    assert checkout["with"]["fetch-depth"] == 0
    assert "github.event.pull_request.base.sha" in text
    assert "github.event.pull_request.head.sha" in text
    assert "python -m tools.openva.workspace validate" in text
    assert "python -m tools.openva.workspace plan" in text
    assert "workspace-plan.json" in text


def test_component_lane_installs_and_runs_only_non_full_suite_plans() -> None:
    workflow = load_validate()
    job = workflow["jobs"]["workspace-component-tests"]
    text = VALIDATE.read_text(encoding="utf-8")

    assert job["needs"] == ["pr-change-classifier", "workspace-plan"]
    assert "full_suite != 'true'" in job["if"]
    assert "targeted workspace lane received a full-suite plan" in text
    assert "plan['install_paths']" in text
    assert "plan['test_paths']" in text
    assert "subprocess.run([sys.executable, '-m', 'pytest', '-q'" in text


def test_full_suite_plans_use_parallel_shards_on_prs_and_main() -> None:
    workflow = load_validate()
    job = workflow["jobs"]["full-regression-shards"]

    assert job["needs"] == ["pr-change-classifier", "workspace-plan"]
    assert "github.event_name != 'pull_request'" in job["if"]
    assert "needs.workspace-plan.outputs.full_suite == 'true'" in job["if"]
    assert job["strategy"]["fail-fast"] is False
    assert len(job["strategy"]["matrix"]["include"]) == 9
    assert "needs.pr-change-classifier.outputs.test_changes == 'true'" in job["if"]


def test_workspace_lane_is_registered_as_a_required_owned_context() -> None:
    ownership = yaml.safe_load(OWNERSHIP.read_text(encoding="utf-8"))

    assert "validate / workspace-affected-tests" in ownership["required_status_contexts"]
    job = ownership["jobs"]["workspace-affected-tests"]
    assert job["owner_loop"] == "workspace_control_plane"
    assert "tools/openva/workspace.py" in job["protects"]
    assert "tools/openva/workspace.yaml" in job["protects"]
    assert "site/**" not in job["protects"]


def test_workspace_validation_remains_within_existing_validate_authority() -> None:
    jobs = set(load_validate()["jobs"])

    assert {
        "repository-integrity",
        "workflow-operating-model",
        "catalog-growth",
        "source-maintenance",
        "catalog-quality",
        "release-site",
        "mcp-integration",
        "google-sheets-integration",
        "workspace-plan",
        "workspace-component-tests",
        "full-regression-shards",
        "workspace-affected-tests",
    } <= jobs


def test_workspace_operating_model_documents_delegated_execution() -> None:
    text = WORKSPACE_DOC.read_text(encoding="utf-8")

    assert "single validation authority" in text
    assert "required status aggregator" in text
    assert "component-scoped tests" in text
    assert "parallel regression shards" in text
    assert "Google Sheets JavaScript tests remain in the dedicated Node lane" in text
    assert "does not remove a regression boundary" in text
