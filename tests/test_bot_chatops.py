from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_chatops import build_decision, main

BOT_CHATOPS_DOC = Path("docs/operations/BOT_CHATOPS.md")
BOT_CHATOPS_CONTRACT = Path("docs/operations/contracts/bot-chatops.yaml")
BOT_OPERATING_MODEL = Path("docs/operations/BOT_OPERATING_MODEL.md")
BOT_AUTHORITY = Path("docs/operations/contracts/bot-authority.yaml")
BOT_QUEUE_POLICY = Path("docs/operations/contracts/bot-queue-policy.yaml")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
REPO_TERMINOLOGY = Path("docs/operations/contracts/repo-terminology.yaml")

REQUIRED_COMMANDS = {
    "/openva retry-source-preflight",
    "/openva defer-candidate",
    "/openva promote-reviewed-plan",
    "/openva explain-strict-growth",
    "/openva quarantine-source",
    "/openva recheck-final-url",
    "/openva hold",
    "/openva unhold",
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


def test_chatops_contract_exists_parses_and_points_to_source_document():
    assert BOT_CHATOPS_DOC.exists()
    contract = load_yaml(BOT_CHATOPS_CONTRACT)

    assert contract["contract"] == "bot-chatops"
    assert contract["source_document"] == "docs/operations/BOT_CHATOPS.md"
    assert contract["prefix"] == "/openva"
    assert contract["default_posture"]["unknown_commands_are_denied"] is True
    assert contract["default_posture"]["commands_are_report_only_until_explicitly_enabled"] is True


def test_all_required_commands_are_declared_and_match_operating_model():
    contract = load_yaml(BOT_CHATOPS_CONTRACT)
    declared = {entry["full_command"] for entry in contract["commands"]}
    operating_model = BOT_OPERATING_MODEL.read_text(encoding="utf-8")

    assert declared == REQUIRED_COMMANDS
    for command in REQUIRED_COMMANDS:
        assert command in operating_model
        assert command in BOT_CHATOPS_DOC.read_text(encoding="utf-8")


def test_unknown_commands_are_denied():
    report = build_decision("/openva frobnicate", "maintainer")

    assert report["decision"] == "denied"
    assert report["authorized"] is False
    assert "unknown_openva_command" in report["reasons"]


def test_non_openva_comments_are_ignored():
    report = build_decision("Looks good to me.", "maintainer")

    assert report["decision"] == "ignored"
    assert report["parsed_command"] is None
    assert report["normalized_command"] is None
    assert report["reasons"] == ["no_openva_command"]


def test_non_maintainer_commands_are_denied():
    report = build_decision("/openva explain-strict-growth", "reviewer")

    assert report["decision"] == "denied"
    assert report["authorized"] is False
    assert "actor_not_authorized" in report["reasons"]


def test_maintainer_commands_are_accepted_as_report_only():
    for command in REQUIRED_COMMANDS:
        report = build_decision(command, "maintainer")
        assert report["decision"] == "accepted_report_only", command
        assert report["authorized"] is True
        assert report["executable"] is False
        assert report["report_only"] is True
        assert report["side_effect_class"] == "report_only"
        assert "chatops decision report" in report["audit_artifacts"]


def test_multiple_commands_in_one_comment_are_denied():
    report = build_decision("/openva hold\n/openva unhold", "maintainer")

    assert report["decision"] == "denied"
    assert report["authorized"] is False
    assert "multiple_openva_commands" in report["reasons"]


def test_command_arguments_are_denied_until_explicitly_supported():
    report = build_decision("/openva hold pr-123", "maintainer")

    assert report["decision"] == "denied"
    assert "invalid_openva_command_syntax" in report["reasons"]


def test_lane_ids_exist_in_authority_contract():
    contract = load_yaml(BOT_CHATOPS_CONTRACT)
    lane_ids = {lane["id"] for lane in load_yaml(BOT_AUTHORITY)["lanes"]}

    for command in contract["commands"]:
        assert command["lane_id"] in lane_ids, command["full_command"]


def test_queue_required_commands_reference_valid_queue_lanes():
    contract = load_yaml(BOT_CHATOPS_CONTRACT)
    queue_lane_ids = {lane["lane_id"] for lane in load_yaml(BOT_QUEUE_POLICY)["lanes"]}

    for command in contract["commands"]:
        if command["requires_queue_check"]:
            assert command["queue_lane_id"] in queue_lane_ids, command["full_command"]


def test_failure_router_required_commands_reference_taxonomy_codes():
    contract = load_yaml(BOT_CHATOPS_CONTRACT)
    failure_codes = {entry["code"] for entry in load_yaml(BOT_FAILURE_TAXONOMY)["failure_classes"]}

    for command in contract["commands"]:
        codes = command.get("failure_router_codes", [])
        if command["requires_failure_router"]:
            assert codes, command["full_command"]
            assert set(codes) <= failure_codes, command["full_command"]
        else:
            assert codes == [], command["full_command"]


def test_decision_output_is_deterministic():
    first = build_decision("/openva retry-source-preflight", "maintainer")
    second = build_decision("/openva retry-source-preflight", "maintainer")

    assert first == second
    assert first["next_safe_action"]
    assert first["requires_queue_check"] is True
    assert first["requires_failure_router"] is True


def test_cli_writes_decision_report(tmp_path):
    comment = tmp_path / "comment.txt"
    output = tmp_path / "decision.json"
    comment.write_text("/openva promote-reviewed-plan\n", encoding="utf-8")

    result = main(["parse", "--comment-file", str(comment), "--actor-role", "maintainer", "--out", str(output)])

    assert result == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == "accepted_report_only"
    assert report["normalized_command"] == "/openva promote-reviewed-plan"


def test_command_parser_does_not_mutate_catalog_data():
    before = data_vendor_digest()

    build_decision("/openva quarantine-source", "maintainer")

    assert data_vendor_digest() == before


def test_command_parser_does_not_call_github_apis():
    source = Path("tools/openva/bot_chatops.py").read_text(encoding="utf-8")

    assert "api.github.com" not in source
    assert "subprocess" not in source
    assert "github" not in source.lower()
    assert "requests" not in source
    assert "urllib.request" not in source


def test_deprecated_terminology_is_not_introduced():
    deprecated_terms = set(load_yaml(REPO_TERMINOLOGY)["deprecated_terms"])
    paths = [
        BOT_CHATOPS_DOC,
        BOT_CHATOPS_CONTRACT,
        Path("tools/openva/bot_chatops.py"),
        Path("tests/test_bot_chatops.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for term in deprecated_terms:
        assert term not in combined
