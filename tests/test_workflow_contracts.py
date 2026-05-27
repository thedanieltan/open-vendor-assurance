import json
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")
VALIDATION_OWNERSHIP = Path(".github/validation-ownership.yaml")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")
REVIEWER_HANDOFF = Path("docs/operations/contracts/reviewer-decision-handoff.yaml")
CATALOG_GROWTH = Path("docs/maintenance/contracts/catalog-growth-scale-readiness.yaml")
CATALOG_GROWTH_QUEUE = Path("maintenance/queues/catalog-growth-discovery.json")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    # PyYAML uses YAML 1.1 boolean parsing for the plain scalar key `on`.
    return workflow.get("on") or workflow.get(True) or {}


def normalized_command(command: str) -> str:
    return " ".join(command.split())


def artifact_upload_steps(workflow_name: str) -> dict[str, set[str]]:
    workflow = load_yaml(WORKFLOW_DIR / workflow_name)
    steps = workflow["jobs"][workflow_name.removesuffix(".yml")]["steps"]
    artifacts: dict[str, set[str]] = {}
    for step in steps:
        if step.get("uses") != "actions/upload-artifact@v6":
            continue
        with_block = step.get("with", {})
        name = with_block.get("name")
        raw_path = with_block.get("path", "")
        paths = {line.strip() for line in str(raw_path).splitlines() if line.strip()}
        artifacts[name] = paths
    return artifacts


def test_validation_ownership_contract_matches_validate_workflow_jobs_and_commands():
    contract = load_yaml(VALIDATION_OWNERSHIP)
    workflow = load_yaml(Path(contract["workflow"]))

    assert set(workflow["jobs"]) == set(contract["jobs"])
    assert contract["required_status_contexts"] == [
        f"validate / {job_name}" for job_name in contract["jobs"]
    ]

    for job_name, job_contract in contract["jobs"].items():
        job = workflow["jobs"][job_name]
        runs = [
            normalized_command(step["run"])
            for step in job["steps"]
            if "run" in step
        ]
        combined_runs = "\n".join(runs)
        for command in job_contract["commands"]:
            assert normalized_command(command) in combined_runs, f"{job_name}: missing {command}"


def test_workflow_inventory_contract_matches_public_workflow_surface():
    contract = load_yaml(WORKFLOW_INVENTORY)
    contract_names = {entry["name"] for entry in contract["public_workflows"]}
    actual_names = {path.name for path in WORKFLOW_DIR.glob("*.yml")}

    assert actual_names == contract_names

    for entry in contract["public_workflows"]:
        workflow = load_yaml(WORKFLOW_DIR / entry["name"])
        assert set(workflow_triggers(workflow).keys()) == set(entry["triggers"]), entry["name"]
        assert workflow.get("permissions", {}) == entry["permissions"], entry["name"]
        if entry["creates_prs"]:
            assert workflow["permissions"].get("pull-requests") == "write", entry["name"]
        if entry["merges_prs"]:
            assert workflow["permissions"].get("contents") == "write", entry["name"]


def test_reviewer_decision_handoff_contract_matches_reviewer_artifact_split():
    contract = load_yaml(REVIEWER_HANDOFF)
    artifacts = artifact_upload_steps("source-maintenance-report.yml")

    assert contract["boundary"]["raw_reviewer_input_is_catalog_truth"] is False
    assert contract["boundary"]["catalog_mutation_from_raw_sheet_allowed"] is False
    assert contract["reviewer_inbox"]["artifact_name"] in artifacts
    assert artifacts[contract["reviewer_inbox"]["artifact_name"]] == set(
        contract["reviewer_inbox"]["allowed_files"]
    )
    assert contract["validation"]["invalid_rows_allowed"] == 0
    assert contract["export"]["output_root"] == "maintenance/reviewed/"
    assert contract["controlled_write_path"]["requires_committed_reviewed_evidence"] is True
    assert contract["controlled_write_path"]["may_run_from_uncommitted_reviewer_sheet"] is False


def test_catalog_growth_scale_readiness_contract_matches_queue_posture():
    contract = load_yaml(CATALOG_GROWTH)
    queue = json.loads(CATALOG_GROWTH_QUEUE.read_text(encoding="utf-8"))

    assert contract["canonical_catalog_root"] == "data/vendors/**"
    assert contract["reviewed_evidence_root"] == "maintenance/reviewed/"
    assert contract["promotion_boundary"]["reviewed_plan_required"] is True
    assert contract["promotion_boundary"]["controlled_write_workflow"] == "candidate-promotion-pr.yml"
    assert contract["promotion_boundary"]["discovery_writes_catalog_truth"] is False
    assert contract["promotion_boundary"]["queue_writes_catalog_truth"] is False

    posture = contract["posture"].copy()
    assert posture.pop("non_advisory") == queue["non_advisory"]
    assert posture == queue["posture"]
