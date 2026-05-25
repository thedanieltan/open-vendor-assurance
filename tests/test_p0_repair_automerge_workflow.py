from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/agent-automerge.yml")
SOURCE_REPAIR_PR_WORKFLOW = Path(".github/workflows/source-repair-pr.yml")


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_p0_source_repair_automerge_installs_match_service_test_dependencies_before_pytest():
    workflow = load_workflow()
    job = workflow["jobs"]["p0-source-repair"]
    steps = job["steps"]
    install_step = next(step for step in steps if step.get("name") == "Install packages")
    test_step = next(step for step in steps if step.get("name") == "Run tests")

    assert 'pip install -e ".[dev]"' in install_step["run"]
    assert 'pip install -e "services/openva_match_service[dev]"' in install_step["run"]
    assert steps.index(install_step) < steps.index(test_step)
    assert test_step["run"] == "pytest -q"


def test_p0_source_repair_automerge_still_uses_strict_label_gate_and_checker():
    workflow = load_workflow()
    job = workflow["jobs"]["p0-source-repair"]
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "source-refinement" in job["if"]
    assert "automerge:p0-source-repair" in job["if"]
    assert "python -m tools.openva.source_repair_automerge check" in text
    assert "gh pr merge" in text


def test_source_repair_pr_runs_collision_check_before_apply():
    workflow = yaml.safe_load(SOURCE_REPAIR_PR_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["source-repair-pr"]["steps"]
    collision_step = next(step for step in steps if step.get("name") == "Check repair source collisions")
    apply_step = next(step for step in steps if step.get("name") == "Apply reviewed P0 source repairs")
    upload_step = next(step for step in steps if step.get("name") == "Upload source repair collision artifacts")

    assert "python -m tools.openva.source_repair_collision_check check" in collision_step["run"]
    assert "--validation \"$VALIDATION_REPORT_PATH\"" in collision_step["run"]
    assert steps.index(collision_step) < steps.index(apply_step)
    assert upload_step["if"] == "always()"
