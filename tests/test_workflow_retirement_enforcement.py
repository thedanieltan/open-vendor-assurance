from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/source-refinement-queue.yml")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")
WORKFLOW_RETIREMENT = Path("docs/operations/contracts/workflow-retirement.yaml")
SOURCE_REFINEMENT_DOC = Path("docs/source-refinement-workflow.md")
OPERATING_MODEL = Path("docs/operations/WORKFLOW_OPERATING_MODEL.md")
WORKFLOW_DIR = Path(".github/workflows")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def workflow_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def catalog_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def inventory_entry(name: str) -> dict:
    return next(
        entry for entry in load_yaml(WORKFLOW_INVENTORY)["public_workflows"] if entry["name"] == name
    )


def retirement_entry(name: str) -> dict:
    return next(entry for entry in load_yaml(WORKFLOW_RETIREMENT)["workflows"] if entry["name"] == name)


def test_source_refinement_queue_is_quarantined_consistently_across_contracts():
    inventory = inventory_entry("source-refinement-queue.yml")
    retirement = retirement_entry("source-refinement-queue.yml")

    assert inventory["status"] == "quarantined"
    assert retirement["inventory_status"] == "quarantined"
    assert retirement["current_status"] == "quarantined"
    assert retirement["retirement_candidate"] is True
    assert retirement["retirement_ready"] is False
    assert retirement["must_not_retire_yet"] is True


def test_quarantined_source_refinement_queue_has_no_schedule_trigger():
    workflow = load_yaml(WORKFLOW)
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"workflow_dispatch"}
    assert "schedule" not in triggers
    assert workflow["permissions"] == {"contents": "read"}


def test_replacement_owners_remain_active_public_workflows():
    retirement = retirement_entry("source-refinement-queue.yml")
    inventory = {
        entry["name"]: entry for entry in load_yaml(WORKFLOW_INVENTORY)["public_workflows"]
    }

    assert "source-refinement-scan.yml" in retirement["replacement_owner"]
    assert "source-maintenance-report.yml" in retirement["replacement_owner"]
    assert inventory["source-refinement-scan.yml"]["status"] == "core"
    assert inventory["source-maintenance-report.yml"]["status"] == "core"


def test_docs_mark_source_refinement_queue_as_legacy_not_primary():
    text = SOURCE_REFINEMENT_DOC.read_text(encoding="utf-8")

    assert "WP22 quarantine notice" in text
    assert "Do not use it as the primary source cleanup path" in text
    assert "Use `source-maintenance-report.yml`" in text
    assert "source-refinement-scan.yml" in text


def test_operating_model_reflects_quarantine_action():
    text = OPERATING_MODEL.read_text(encoding="utf-8")

    assert "Quarantined legacy source refinement queue" in text
    assert "| Quarantined |" in text


def test_quarantine_does_not_mutate_workflow_files_or_catalog_data():
    workflow_before = workflow_digest()
    catalog_before = catalog_digest()

    load_yaml(WORKFLOW_RETIREMENT)
    load_yaml(WORKFLOW_INVENTORY)

    assert workflow_digest() == workflow_before
    assert catalog_digest() == catalog_before
