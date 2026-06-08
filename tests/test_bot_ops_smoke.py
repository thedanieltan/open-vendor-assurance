from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_ops_smoke import main, render_markdown, run_smoke

BOT_OPS_SMOKE_DOC = Path("docs/operations/BOT_OPS_SMOKE_HARNESS.md")
REPO_TERMINOLOGY = Path("docs/operations/contracts/repo-terminology.yaml")
WORKFLOW_DIR = Path(".github/workflows")

EXPECTED_SUBSYSTEMS = {
    "contracts",
    "dashboard",
    "queue",
    "failure_router",
    "chatops",
    "dashboard_issue_sync",
    "workflow_retirement",
    "observability",
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


def subsystem_by_name(report: dict) -> dict[str, dict]:
    return {entry["name"]: entry for entry in report["subsystems"]}


def test_smoke_doc_exists():
    assert BOT_OPS_SMOKE_DOC.exists()
    text = BOT_OPS_SMOKE_DOC.read_text(encoding="utf-8")
    assert "local end-to-end smoke harness" in text
    assert "does not call GitHub APIs" in text


def test_smoke_harness_runs_successfully():
    report = run_smoke()

    assert report["status"] == "pass"
    assert report["report_type"] == "bot_ops_smoke"
    assert report["summary"]["local_only"] is True
    assert report["summary"]["report_only"] is True


def test_output_json_is_deterministic():
    assert run_smoke() == run_smoke()


def test_output_markdown_is_deterministic():
    report = run_smoke()

    assert render_markdown(report) == render_markdown(report)
    assert "# OpenVA Bot Ops Smoke Report" in render_markdown(report)


def test_report_includes_each_subsystem():
    report = run_smoke()

    assert set(subsystem_by_name(report)) == EXPECTED_SUBSYSTEMS


def test_clean_queue_sample_allows():
    queue = subsystem_by_name(run_smoke())["queue"]["details"]

    assert queue["clean_decision"] == "allow"


def test_blocked_queue_sample_defers_or_denies():
    queue = subsystem_by_name(run_smoke())["queue"]["details"]

    assert queue["blocked_decision"] in {"defer", "deny"}
    assert queue["blocked_reasons"]


def test_explicit_failure_routes_to_expected_taxonomy_code():
    failure = subsystem_by_name(run_smoke())["failure_router"]["details"]

    assert failure["matched_failure_code"] == "stale_evidence_failure"
    assert failure["classification"] == "taxonomy_match"


def test_allowed_chatops_command_is_report_only():
    chatops = subsystem_by_name(run_smoke())["chatops"]["details"]

    assert chatops["allowed_decision"] == "accepted_report_only"
    assert chatops["allowed_report_only"] is True


def test_denied_chatops_command_is_denied():
    chatops = subsystem_by_name(run_smoke())["chatops"]["details"]

    assert chatops["denied_decision"] == "denied"
    assert "unknown_openva_command" in chatops["denied_reasons"]


def test_dashboard_issue_sync_is_dry_run_only():
    issue = subsystem_by_name(run_smoke())["dashboard_issue_sync"]["details"]

    assert issue["dry_run"] is True
    assert issue["report_only"] is True
    assert issue["decision"] in {"would_create", "would_update", "failed"}


def test_cli_writes_reports(tmp_path):
    out_json = tmp_path / "smoke.json"
    out_md = tmp_path / "smoke.md"

    result = main(["run", "--out-json", str(out_json), "--out-md", str(out_md)])

    assert result == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["report_type"] == "bot_ops_smoke"
    assert "# OpenVA Bot Ops Smoke Report" in out_md.read_text(encoding="utf-8")


def test_no_catalog_data_mutation():
    before = data_vendor_digest()

    run_smoke()

    assert data_vendor_digest() == before


def test_no_workflow_mutation():
    before = workflow_digest()

    run_smoke()

    assert workflow_digest() == before


def test_no_github_api_calls_or_workflow_dispatch_are_introduced():
    source = Path("tools/openva/bot_ops_smoke.py").read_text(encoding="utf-8").lower()

    assert "api.github.com" not in source
    assert "urllib" not in source
    assert "requests" not in source
    assert "subprocess" not in source
    assert "actions/workflows" not in source
    assert "gh " not in source


def test_deprecated_terminology_is_not_introduced():
    deprecated_terms = set(load_yaml(REPO_TERMINOLOGY)["deprecated_terms"])
    paths = [
        BOT_OPS_SMOKE_DOC,
        Path("tools/openva/bot_ops_smoke.py"),
        Path("tests/test_bot_ops_smoke.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for term in deprecated_terms:
        assert term not in combined
