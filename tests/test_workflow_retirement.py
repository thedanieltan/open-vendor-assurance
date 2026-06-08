from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from tools.openva.workflow_retirement import build_report, load_contracts, main, validate_contracts

WORKFLOW_DIR = Path(".github/workflows")
WORKFLOW_INVENTORY = Path("docs/operations/contracts/workflow-inventory.yaml")
WORKFLOW_RETIREMENT_DOC = Path("docs/operations/WORKFLOW_RETIREMENT_PLAN.md")
WORKFLOW_RETIREMENT = Path("docs/operations/contracts/workflow-retirement.yaml")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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


def inventory_names() -> set[str]:
    return {entry["name"] for entry in load_yaml(WORKFLOW_INVENTORY)["public_workflows"]}


def retirement_entries() -> list[dict]:
    return load_yaml(WORKFLOW_RETIREMENT)["workflows"]


def test_retirement_contract_exists_parses_and_points_to_source_document():
    assert WORKFLOW_RETIREMENT_DOC.exists()
    contract = load_yaml(WORKFLOW_RETIREMENT)

    assert contract["contract"] == "workflow-retirement"
    assert contract["source_document"] == "docs/operations/WORKFLOW_RETIREMENT_PLAN.md"
    assert contract["default_posture"]["unclassified_workflows_block_retirement"] is True
    assert contract["default_posture"]["destructive_retirement_requires_followup_pr"] is True


def test_every_inventory_workflow_has_a_retirement_entry():
    assert inventory_names() == {entry["name"] for entry in retirement_entries()}


def test_every_retirement_entry_references_inventory_workflow():
    names = inventory_names()

    for entry in retirement_entries():
        assert entry["name"] in names


def test_statuses_are_valid_and_expected_statuses_are_declared():
    contract = load_yaml(WORKFLOW_RETIREMENT)
    statuses = set(contract["statuses"])

    assert statuses == {"active", "shadow_report_only", "deprecated_callable", "quarantined", "retired"}
    for entry in contract["workflows"]:
        assert entry["current_status"] in statuses, entry["name"]


def test_unclassified_workflows_block_retirement_and_destructive_changes_are_disallowed():
    posture = load_yaml(WORKFLOW_RETIREMENT)["default_posture"]

    assert posture["unclassified_workflows_block_retirement"] is True
    assert posture["workflow_deletion_allowed_in_this_contract"] is False
    assert posture["workflow_disable_allowed_in_this_contract"] is False
    assert posture["workflow_rename_allowed_in_this_contract"] is False
    assert posture["workflow_trigger_changes_allowed_in_this_contract"] is False
    assert posture["workflow_permission_changes_allowed_in_this_contract"] is False


def test_consolidation_candidates_have_replacement_owners_or_explicit_blockers():
    inventory = {
        entry["name"]: entry
        for entry in load_yaml(WORKFLOW_INVENTORY)["public_workflows"]
        if entry["status"] == "consolidation_candidate"
    }

    for entry in retirement_entries():
        if entry["name"] not in inventory:
            continue
        assert entry["current_status"] == "shadow_report_only"
        assert entry["retirement_candidate"] is True
        assert entry["replacement_owner"] or entry["retirement_blockers"], entry["name"]
        assert entry["write_permissions_allowed_until_retired"] is False


def test_quarantined_source_refinement_queue_is_not_retirement_ready():
    entry = next(entry for entry in retirement_entries() if entry["name"] == "source-refinement-queue.yml")

    assert entry["current_status"] == "quarantined"
    assert entry["inventory_status"] == "quarantined"
    assert entry["retirement_candidate"] is True
    assert entry["retirement_ready"] is False
    assert entry["must_not_retire_yet"] is True
    assert entry["allowed_triggers_until_retired"] == ["workflow_dispatch"]
    assert entry["write_permissions_allowed_until_retired"] is False


def test_active_workflows_are_not_marked_retirement_ready():
    for entry in retirement_entries():
        if entry["current_status"] == "active":
            assert entry["retirement_ready"] is False, entry["name"]
            assert entry["retirement_candidate"] is False, entry["name"]
            assert entry["must_not_retire_yet"] is True, entry["name"]


def test_retired_workflows_do_not_appear_in_active_inventory():
    retired = [entry for entry in retirement_entries() if entry["current_status"] == "retired"]

    assert retired == []


def test_contract_validator_accepts_current_contracts():
    assert validate_contracts(load_contracts()) == []


def test_contract_validator_blocks_missing_retirement_entry():
    contracts = load_contracts()
    contracts["retirement"]["workflows"] = contracts["retirement"]["workflows"][:-1]

    errors = validate_contracts(contracts)

    assert any(error.startswith("missing_retirement_entries:") for error in errors)


def test_report_output_is_deterministic(tmp_path):
    contracts = load_contracts()
    first = build_report(contracts)
    second = build_report(contracts)

    assert first == second
    assert "Workflow Retirement Report" in first
    assert "`catalog-maintenance.yml`" in first

    out = tmp_path / "workflow-retirement-report.md"
    result = main(["report", "--out", str(out)])

    assert result == 0
    assert out.read_text(encoding="utf-8") == first


def test_tool_does_not_mutate_workflows():
    before = workflow_digest()

    build_report(load_contracts())

    assert workflow_digest() == before


def test_tool_does_not_change_catalog_data():
    before = catalog_digest()

    build_report(load_contracts())

    assert catalog_digest() == before
