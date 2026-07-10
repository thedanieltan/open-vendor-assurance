from pathlib import Path

import yaml


VALIDATE = Path(".github/workflows/validate.yml")
WORKSPACE_DOC = Path("docs/operations/OPENVA_WORKSPACE.md")
OWNERSHIP = Path(".github/validation-ownership.yaml")


def load_validate() -> dict:
    return yaml.safe_load(VALIDATE.read_text(encoding="utf-8"))


def test_workspace_lane_is_part_of_existing_validate_authority() -> None:
    workflow = load_validate()
    job = workflow["jobs"]["workspace-affected-tests"]

    assert workflow["permissions"] == {"contents": "read"}
    assert job["if"] == "github.event_name == 'pull_request'"
    assert job["runs-on"] == "ubuntu-latest"


def test_workspace_lane_uses_full_history_and_real_pr_base_head() -> None:
    workflow = load_validate()
    job = workflow["jobs"]["workspace-affected-tests"]
    text = VALIDATE.read_text(encoding="utf-8")

    checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v5")
    assert checkout["with"]["fetch-depth"] == 0
    assert "github.event.pull_request.base.sha" in text
    assert "github.event.pull_request.head.sha" in text


def test_workspace_lane_validates_plans_installs_and_runs_selected_tests() -> None:
    text = VALIDATE.read_text(encoding="utf-8")

    assert "python -m tools.openva.workspace validate" in text
    assert "python -m tools.openva.workspace plan" in text
    assert "workspace-plan.json" in text
    assert "plan['install_paths']" in text
    assert "plan['test_paths']" in text
    assert "subprocess.run([sys.executable, '-m', 'pytest', '-q'" in text


def test_workspace_lane_is_registered_as_a_required_owned_context() -> None:
    ownership = yaml.safe_load(OWNERSHIP.read_text(encoding="utf-8"))

    assert "validate / workspace-affected-tests" in ownership["required_status_contexts"]
    job = ownership["jobs"]["workspace-affected-tests"]
    assert job["owner_loop"] == "workspace_control_plane"
    assert "tools/openva/workspace.py" in job["protects"]
    assert "tools/openva/workspace.yaml" in job["protects"]


def test_workspace_lane_is_additive_not_a_replacement() -> None:
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
        "full-regression-shards",
        "workspace-affected-tests",
    } <= jobs


def test_workspace_operating_model_preserves_conservative_boundaries() -> None:
    text = WORKSPACE_DOC.read_text(encoding="utf-8")

    assert "single validation authority" in text
    assert "additive" in text
    assert "fail safe to the full Python suite" in text
    assert "Google Sheets JavaScript tests remain in the dedicated Node lane" in text
    assert "Replacing or removing existing validation lanes is a separate future decision" in text
