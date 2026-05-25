from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/agent-automerge.yml")


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
