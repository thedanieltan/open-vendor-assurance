from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_chatops_execute import execute_command, main

BOT_CHATOPS_EXECUTION_DOC = Path("docs/operations/BOT_CHATOPS_EXECUTION.md")
BOT_CHATOPS_CONTRACT = Path("docs/operations/contracts/bot-chatops.yaml")
EXECUTABLE_COMMANDS = {
    "/openva explain-strict-growth",
    "/openva hold",
    "/openva unhold",
}
NON_EXECUTABLE_COMMANDS = {
    "/openva retry-source-preflight",
    "/openva defer-candidate",
    "/openva promote-reviewed-plan",
    "/openva quarantine-source",
    "/openva recheck-final-url",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def queue_state(lane_id: str = "support_agent_pr") -> dict:
    return {
        "version": 1,
        "lane_id": lane_id,
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "evidence": {"generated_at": "2099-01-01T00:00:00Z"},
        "pause": {"active": False},
        "requested_action": {
            "duplicate_key": "chatops-hold",
            "vendor_domain": "",
            "source_host": "",
            "base_sha": "a" * 40,
            "head_sha": "a" * 40,
        },
    }


def write_queue_state(tmp_path: Path) -> Path:
    path = tmp_path / "queue-state.json"
    path.write_text(json.dumps(queue_state(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_execution_document_exists_and_names_enabled_commands():
    assert BOT_CHATOPS_EXECUTION_DOC.exists()
    text = BOT_CHATOPS_EXECUTION_DOC.read_text(encoding="utf-8")

    for command in EXECUTABLE_COMMANDS | NON_EXECUTABLE_COMMANDS:
        assert command in text
    assert "openva-hold" in text
    assert "does not apply or remove labels" in text


def test_only_three_approved_commands_are_executable_in_contract():
    contract = load_yaml(BOT_CHATOPS_CONTRACT)
    executable = {
        command["full_command"]
        for command in contract["commands"]
        if command["executable"] is True
    }

    assert executable == EXECUTABLE_COMMANDS
    for command in contract["commands"]:
        if command["full_command"] in NON_EXECUTABLE_COMMANDS:
            assert command["status"] == "planned_report_only"
            assert command["executable"] is False
            assert command["report_only"] is True


def test_non_maintainer_execution_is_denied():
    report = execute_command("/openva explain-strict-growth", "reviewer")

    assert report["decision"] == "denied"
    assert report["executed"] is False
    assert report["authorization_decision"]["authorized"] is False
    assert "actor_not_authorized" in report["reasons"]


def test_unknown_and_multiple_commands_are_denied():
    unknown = execute_command("/openva frobnicate", "maintainer")
    multiple = execute_command("/openva hold\n/openva unhold", "maintainer")

    assert unknown["decision"] == "denied"
    assert "unknown_openva_command" in unknown["reasons"]
    assert multiple["decision"] == "denied"
    assert "multiple_openva_commands" in multiple["reasons"]


def test_non_openva_comments_are_ignored():
    report = execute_command("Thanks, this looks good.", "maintainer")

    assert report["decision"] == "ignored"
    assert report["executed"] is False
    assert report["reasons"] == ["no_openva_command"]


def test_higher_risk_commands_remain_report_only_not_executed():
    for command in NON_EXECUTABLE_COMMANDS:
        report = execute_command(command, "maintainer")
        assert report["decision"] == "report_only_not_executable", command
        assert report["executed"] is False
        assert report["execution_report"] is None
        assert "command_remains_report_only" in report["reasons"]


def test_explain_strict_growth_produces_deterministic_explanation():
    first = execute_command("/openva explain-strict-growth", "maintainer")
    second = execute_command("/openva explain-strict-growth", "maintainer")

    assert first == second
    assert first["decision"] == "executed"
    assert first["executed"] is True
    assert first["execution_report"]["side_effect_class"] == "informational_report"
    assert first["execution_report"]["mutates_catalog"] is False
    assert "Strict-growth is OpenVA" in first["execution_report"]["markdown"]


def test_hold_only_reports_allowed_hold_label(tmp_path):
    report = execute_command(
        "/openva hold",
        "maintainer",
        queue_state_path=write_queue_state(tmp_path),
        context_kind="pull_request",
    )

    label = report["execution_report"]["label_mutation"]
    assert report["decision"] == "executed"
    assert label["allowed_label"] == "openva-hold"
    assert label["requested_action"] == "apply"
    assert label["context_kind"] == "pull_request"
    assert label["applied"] is False
    assert report["execution_report"]["mutates_remote_state"] is False


def test_unhold_only_reports_allowed_hold_label(tmp_path):
    report = execute_command(
        "/openva unhold",
        "maintainer",
        queue_state_path=write_queue_state(tmp_path),
        context_kind="issue",
    )

    label = report["execution_report"]["label_mutation"]
    assert report["decision"] == "executed"
    assert label["allowed_label"] == "openva-hold"
    assert label["requested_action"] == "remove"
    assert label["context_kind"] == "issue"
    assert label["applied"] is False


def test_hold_requires_queue_state_and_routes_failure():
    report = execute_command("/openva hold", "maintainer")

    assert report["decision"] == "denied"
    assert report["executed"] is False
    assert "queue_decision_not_allow" in report["reasons"]
    assert report["queue_decision"]["decision"] == "deny"
    assert report["failure_routing_report"]["matched_failure_code"] == "permission_policy_denial"


def test_command_execution_cli_writes_json_and_markdown(tmp_path):
    comment = tmp_path / "comment.txt"
    out_json = tmp_path / "execution.json"
    out_md = tmp_path / "execution.md"
    comment.write_text("/openva explain-strict-growth\n", encoding="utf-8")

    result = main(
        [
            "execute",
            "--comment-file",
            str(comment),
            "--actor-role",
            "maintainer",
            "--out",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )

    assert result == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["decision"] == "executed"
    assert "# OpenVA Chat-Ops Execution Report" in out_md.read_text(encoding="utf-8")


def test_execution_layer_does_not_mutate_catalog_data(tmp_path):
    before = data_vendor_digest()

    execute_command("/openva hold", "maintainer", queue_state_path=write_queue_state(tmp_path))
    execute_command("/openva explain-strict-growth", "maintainer")

    assert data_vendor_digest() == before


def test_execution_layer_does_not_call_remote_apis_or_dispatch_workflows():
    source = Path("tools/openva/bot_chatops_execute.py").read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "requests." not in source
    assert "api.github.com" not in source
    assert "actions/workflows" not in source
    assert "workflow_dispatches" not in source
