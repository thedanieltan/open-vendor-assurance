from pathlib import Path

import yaml

from tools.openva.materialize_batches import plan_materialization

WORKFLOW = Path(".github/workflows/materialize-batches-pr.yml")
LANES = Path("config/materialization-lanes.yaml")
DOC = Path("docs/batch-materialization-workflow.md")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_materialization_lanes_config_is_non_advisory_and_bounded():
    config = yaml.safe_load(LANES.read_text(encoding="utf-8"))

    assert config["schema_version"] == "0.1.0"
    assert config["non_advisory"] is True
    assert set(config["lanes"]) == {
        "infra-data-ai-devtools",
        "payments-kyc-fintech",
        "hr-health-education-logistics",
        "collaboration-commerce-grc",
        "regional-apac-china",
    }
    for lane in config["lanes"].values():
        assert lane["manifests"]
        assert all(path.startswith("catalog-batches/") for path in lane["manifests"])


def test_materialization_plan_is_local_metadata_only():
    report = plan_materialization("regional-apac-china", [])

    assert report["report_type"] == "materialization_plan"
    assert report["posture"] == {
        "public_sources_only": True,
        "non_advisory": True,
        "raw_documents_mirrored": False,
        "gated_materials_excluded": True,
    }
    assert report["summary"]["manifest_count"] >= 1
    assert "manifests" in report


def test_materialization_workflow_is_manual_pr_only():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)
    text = WORKFLOW.read_text(encoding="utf-8")

    assert set(triggers.keys()) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert "branch_name must start with agent-" in text
    assert "pr_title must start with Catalog:" in text
    assert "peter-evans/create-pull-request@v6" in text
    assert "python -m tools.openva.materialize_batches run" in text
    assert "does not fetch live vendor content" in text


def test_batch_materialization_doc_preserves_scope_boundaries():
    text = DOC.read_text(encoding="utf-8")

    assert "planned batch manifests and materialized catalog records" in text
    assert "does not fetch live vendor content" in text
    assert "does not mirror raw documents" in text
    assert "does not use gated/private materials" in text
    assert "does not write directly to `main`" in text
    assert "does not mean the vendor is approved" in text
