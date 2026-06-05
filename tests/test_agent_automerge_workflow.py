from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/agent-automerge.yml")


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def step_index(steps: list[dict], name: str) -> int:
    return next(index for index, step in enumerate(steps) if step.get("name") == name)


def step(steps: list[dict], name: str) -> dict:
    return steps[step_index(steps, name)]


def test_strict_growth_job_is_separate_and_requires_both_labels():
    workflow = load_workflow()
    jobs = workflow["jobs"]
    condition = jobs["strict-growth"]["if"]

    assert "machine-canonical" in jobs
    assert "p0-source-repair" in jobs
    assert "strict-growth" in jobs
    assert "catalog-growth" in condition
    assert "automerge:strict-growth" in condition
    assert "!contains(join(github.event.pull_request.labels.*.name, ','), 'automerge:machine-canonical')" in condition
    assert "automerge:machine-canonical" not in condition.replace(
        "!contains(join(github.event.pull_request.labels.*.name, ','), 'automerge:machine-canonical')",
        "",
    )


def test_machine_canonical_job_does_not_handle_strict_growth_prs():
    workflow = load_workflow()
    condition = workflow["jobs"]["machine-canonical"]["if"]

    assert "automerge:machine-canonical" in condition
    assert "!contains(join(github.event.pull_request.labels.*.name, ','), 'automerge:strict-growth')" in condition


def test_strict_growth_job_checks_policy_and_safety_before_automerge():
    workflow = load_workflow()
    steps = workflow["jobs"]["strict-growth"]["steps"]
    names = [step.get("name") for step in steps]

    install = step(steps, "Install packages")
    collect_inputs = step(steps, "Collect strict growth inputs")
    policy_check = step(steps, "Check strict growth automerge eligibility")
    preflight = step(steps, "Check changed source record preflight")
    validate = step(steps, "Validate repository")
    build_indexes = step(steps, "Rebuild generated outputs")
    drift = step(steps, "Refuse generated drift")
    tests = step(steps, "Run tests")
    site = step(steps, "Build site")
    merge = step(steps, "Enable GitHub native auto-merge")

    assert 'pip install -e "services/openva_match_service[dev]"' in install["run"]
    assert "python -m tools.openva.strict_growth_automerge extract-inputs" in collect_inputs["run"]
    assert "python -m tools.openva.strict_growth_automerge check-plan" in policy_check["run"]
    assert "--promotion-plan \"$PROMOTION_PLAN_PATH\"" in policy_check["run"]
    assert "--eligibility-report \"$ELIGIBILITY_REPORT_PATH\"" in policy_check["run"]
    assert "--recorded-head-sha \"$STRICT_GROWTH_HEAD_SHA\"" in policy_check["run"]
    assert "python -m tools.openva.source_preflight check-changed-sources" in preflight["run"]
    assert validate["run"] == "python -m tools.openva.validate validate"
    assert build_indexes["run"] == "python -m tools.openva.validate build-indexes"
    assert drift["run"] == "git diff --exit-code openva-pack.json indexes/ dist/"
    assert tests["run"] == "pytest -q"
    assert site["run"] == "python site/build.py --out site/dist"
    assert "gh pr merge \"$PR_NUMBER\" --auto --squash --delete-branch" in merge["run"]

    for required in (
        "Collect strict growth inputs",
        "Check strict growth automerge eligibility",
        "Check changed source record preflight",
        "Validate repository",
        "Rebuild generated outputs",
        "Refuse generated drift",
        "Run tests",
        "Build site",
    ):
        assert names.index(required) < names.index("Enable GitHub native auto-merge")
