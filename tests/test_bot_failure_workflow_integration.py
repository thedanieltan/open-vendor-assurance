from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from tools.openva.bot_failure_router import route_failure
from tools.openva.bot_workflow_failure import build_observation

WORKFLOW_DIR = Path(".github/workflows")
INTEGRATED_WORKFLOWS = {
    "source-repair-pr.yml": {
        "artifacts": {"openva-source-repair-failure-routing"},
        "lanes": {"source_repair"},
        "permissions": {"contents": "write", "pull-requests": "write"},
    },
    "candidate-promotion-pr.yml": {
        "artifacts": {"openva-catalog-promotion-failure-routing"},
        "lanes": {"catalog_growth_promotion"},
        "permissions": {"contents": "write", "pull-requests": "write"},
    },
    "catalog-growth-discovery.yml": {
        "artifacts": {"openva-catalog-growth-discovery-failure-routing"},
        "lanes": {"catalog_growth_discovery"},
        "permissions": {"contents": "read", "issues": "write"},
    },
    "source-maintenance-report.yml": {
        "artifacts": {"openva-source-maintenance-failure-routing"},
        "lanes": {"source_maintenance_report"},
        "permissions": {"contents": "read"},
    },
    "source-refinement-scan.yml": {
        "artifacts": {"openva-source-refinement-failure-routing"},
        "lanes": {"source_maintenance_report"},
        "permissions": {"actions": "read", "contents": "read"},
    },
    "agent-automerge.yml": {
        "artifacts": {
            "openva-automerge-machine-canonical-failure-routing",
            "openva-automerge-strict-growth-failure-routing",
            "openva-automerge-p0-source-repair-failure-routing",
        },
        "lanes": {"pr_safety"},
        "permissions": {
            # actions: read added with the generated-catalog automerge lane (run/artifact
            # reads); any FURTHER widening still fails this freeze.
            "actions": "read",
            "contents": "write",
            "pull-requests": "write",
            "checks": "read",
            "statuses": "read",
        },
    },
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def all_steps(workflow_name: str) -> list[dict]:
    workflow = load_yaml(WORKFLOW_DIR / workflow_name)
    steps: list[dict] = []
    for job in workflow["jobs"].values():
        steps.extend(job["steps"])
    return steps


def artifact_upload_names(steps: list[dict]) -> set[str]:
    names = set()
    for step in steps:
        if step.get("uses") == "actions/upload-artifact@v6":
            name = step.get("with", {}).get("name")
            if name:
                names.add(name)
    return names


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_integrated_workflows_invoke_failure_router_on_failure_paths():
    for workflow_name, expected in INTEGRATED_WORKFLOWS.items():
        text = (WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")
        assert "python -m tools.openva.bot_workflow_failure build" in text
        assert "python -m tools.openva.bot_failure_router classify" in text
        assert "--out-md" in text
        assert "if: failure()" in text
        for lane in expected["lanes"]:
            assert f"--lane {lane}" in text


def test_failure_routing_artifacts_are_uploaded_with_raw_input_and_reports():
    for workflow_name, expected in INTEGRATED_WORKFLOWS.items():
        steps = all_steps(workflow_name)
        names = artifact_upload_names(steps)
        assert expected["artifacts"] <= names
        for artifact_name in expected["artifacts"]:
            artifact_steps = [
                step
                for step in steps
                if step.get("uses") == "actions/upload-artifact@v6"
                and step.get("with", {}).get("name") == artifact_name
            ]
            assert artifact_steps, artifact_name
            raw_path = str(artifact_steps[0]["with"]["path"])
            assert "failure-input.json" in raw_path
            assert "failure-routing-report.json" in raw_path
            assert "failure-routing-report.md" in raw_path


def test_workflow_permissions_are_not_widened_for_failure_routing():
    for workflow_name, expected in INTEGRATED_WORKFLOWS.items():
        workflow = load_yaml(WORKFLOW_DIR / workflow_name)
        assert workflow["permissions"] == expected["permissions"], workflow_name


def test_failure_router_steps_preserve_original_failure_semantics():
    for workflow_name in INTEGRATED_WORKFLOWS:
        for step in all_steps(workflow_name):
            name = step.get("name", "")
            if "failure routing" in name.lower() or name.startswith("Route "):
                assert step.get("if") in {"failure()", "always()"}
                assert step.get("continue-on-error") is not True
                if "run" in step:
                    assert "exit 0" not in step["run"]


def test_known_failure_messages_map_to_expected_taxonomy_codes():
    examples = {
        "Unexpected inputs provided: dry_run": "workflow_input_compatibility_failure",
        "schema validation failed for workflow contract": "schema_validation_failure",
        "generated files are stale after build-indexes": "generated_drift_failure",
        "automerge lane mismatch for strict-growth labels": "automerge_lane_mismatch",
        "source preflight failed for changed source records": "source_preflight_failure",
        "redirect canonicalization failure for final URL": "redirect_canonicalization_failure",
        "external fetch instability while probing source host": "external_fetch_instability",
    }
    for message, expected_code in examples.items():
        report = route_failure({"version": 1, "lane_id": "pr_safety", "failure": {"message": message}})
        assert report["matched_failure_code"] == expected_code


def test_queue_stops_map_to_expected_failure_codes():
    stale = route_failure(
        {
            "version": 1,
            "lane_id": "catalog_growth_promotion",
            "queue_report": {"decision": "defer", "reasons": ["stale_evidence"]},
        }
    )
    pause = route_failure(
        {
            "version": 1,
            "lane_id": "source_repair",
            "queue_report": {"decision": "pause", "reasons": ["pause_switch_active"]},
        }
    )

    assert stale["matched_failure_code"] == "stale_evidence_failure"
    assert pause["matched_failure_code"] == "permission_policy_denial"


def test_workflow_failure_helper_infers_source_preflight_failure():
    observation = build_observation(
        workflow="candidate-promotion-pr.yml",
        lane_id="catalog_growth_promotion",
        message="catalog promotion failed",
        source_preflight_report={"failed_count": 1, "checked_count": 3},
    )

    report = route_failure(observation)

    assert observation["failure"]["code"] == "source_preflight_failure"
    assert report["matched_failure_code"] == "source_preflight_failure"


def test_failure_router_and_helper_do_not_call_github_apis():
    router_source = Path("tools/openva/bot_failure_router.py").read_text(encoding="utf-8")
    helper_source = Path("tools/openva/bot_workflow_failure.py").read_text(encoding="utf-8")

    for source in (router_source, helper_source):
        assert "gh pr" not in source
        assert "gh api" not in source
        assert "subprocess" not in source
        assert "requests." not in source
        assert "api.github.com" not in source
        assert "actions/workflows" not in source
        assert "workflow_dispatches" not in source


def test_failure_routing_integration_does_not_mutate_catalog_data():
    before = data_vendor_digest()

    for workflow_name in INTEGRATED_WORKFLOWS:
        load_yaml(WORKFLOW_DIR / workflow_name)
    build_observation(
        workflow="source-repair-pr.yml",
        lane_id="source_repair",
        message="schema validation failed",
        failure_code="schema_validation_failure",
    )

    assert data_vendor_digest() == before
