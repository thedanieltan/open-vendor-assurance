from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_calibration import build_calibration, load_contract, main, render_markdown

BOT_CALIBRATION_DOC = Path("docs/operations/BOT_OPS_CALIBRATION.md")
BOT_CALIBRATION_CONTRACT = Path("docs/operations/contracts/bot-calibration.yaml")
REPO_TERMINOLOGY = Path("docs/operations/contracts/repo-terminology.yaml")
WORKFLOW_DIR = Path(".github/workflows")

REQUIRED_SECTION_IDS = {
    "baseline_repo_posture",
    "dashboard_usefulness_review",
    "queue_decision_quality",
    "failure_router_classification_quality",
    "chatops_safety_review",
    "workflow_retirement_posture",
    "observability_completeness",
    "smoke_harness_coverage",
    "missing_artifact_inventory",
    "noise_false_positive_inventory",
    "automation_authority_recommendation",
    "next_safe_action",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def workflow_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_calibration_doc_and_contract_exist():
    assert BOT_CALIBRATION_DOC.exists()
    assert BOT_CALIBRATION_CONTRACT.exists()
    doc = BOT_CALIBRATION_DOC.read_text(encoding="utf-8")
    contract = load_yaml(BOT_CALIBRATION_CONTRACT)

    assert "local-only and report-only" in doc
    assert contract["contract"] == "bot-calibration"
    assert contract["source_document"] == BOT_CALIBRATION_DOC.as_posix()


def test_contract_declares_required_sections_and_recommendations():
    contract = load_contract()
    section_ids = {entry["id"] for entry in contract["required_sections"]}

    assert REQUIRED_SECTION_IDS <= section_ids
    assert {
        "hold_current_authority",
        "tune_dashboard_signals",
        "tune_queue_policy",
        "tune_failure_taxonomy",
        "allow_limited_label_activation",
        "block_authority_expansion",
    } <= set(contract["allowed_recommendations"])


def test_calibration_runner_builds_report_with_all_sections():
    report = build_calibration()

    assert report["report_type"] == "bot_ops_calibration"
    assert report["local_only"] is True
    assert report["report_only"] is True
    assert report["github_api_calls"] is False
    assert report["workflow_dispatch"] is False
    assert report["catalog_mutation"] is False
    assert {entry["id"] for entry in report["sections"]} == REQUIRED_SECTION_IDS


def test_recommendations_are_allowed_values():
    contract = load_contract()
    report = build_calibration()

    assert set(report["recommendations"]) <= set(contract["allowed_recommendations"])
    assert "hold_current_authority" in report["recommendations"]


def test_calibration_output_is_deterministic():
    assert build_calibration() == build_calibration()


def test_calibration_markdown_is_deterministic():
    report = build_calibration()

    assert render_markdown(report) == render_markdown(report)
    assert "# OpenVA Bot Ops Calibration Report" in render_markdown(report)
    for section_id in REQUIRED_SECTION_IDS:
        title = section_id.replace("_", " ").capitalize()
        assert title or section_id


def test_calibration_cli_writes_reports(tmp_path):
    out_json = tmp_path / "calibration.json"
    out_md = tmp_path / "calibration.md"

    result = main(["run", "--out-json", str(out_json), "--out-md", str(out_md)])

    assert result == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["report_type"] == "bot_ops_calibration"
    assert "# OpenVA Bot Ops Calibration Report" in out_md.read_text(encoding="utf-8")


def test_missing_inputs_are_explicit():
    report = build_calibration()

    missing_section = next(entry for entry in report["sections"] if entry["id"] == "missing_artifact_inventory")
    assert "missing_inputs" in missing_section["evidence"]
    assert isinstance(report["missing_inputs"], list)


def test_no_catalog_data_mutation():
    before = data_vendor_digest()

    build_calibration()

    assert data_vendor_digest() == before


def test_no_workflow_mutation():
    before = workflow_digest()

    build_calibration()

    assert workflow_digest() == before


def test_no_github_api_calls_or_workflow_dispatch_are_introduced():
    source = Path("tools/openva/bot_calibration.py").read_text(encoding="utf-8").lower()

    assert "api.github.com" not in source
    assert "urllib" not in source
    assert "requests" not in source
    assert "subprocess" not in source
    assert "actions/workflows" not in source
    assert "gh " not in source


def test_deprecated_terminology_is_not_introduced():
    deprecated_terms = set(load_yaml(REPO_TERMINOLOGY)["deprecated_terms"])
    paths = [
        BOT_CALIBRATION_DOC,
        BOT_CALIBRATION_CONTRACT,
        Path("tools/openva/bot_calibration.py"),
        Path("tests/test_bot_calibration.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for term in deprecated_terms:
        assert term not in combined
