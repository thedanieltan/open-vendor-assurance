from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_observability import METRIC_NAMES, build_scorecard, main, render_markdown

BOT_OBSERVABILITY_DOC = Path("docs/operations/BOT_OBSERVABILITY.md")
BOT_OBSERVABILITY = Path("docs/operations/contracts/bot-observability.yaml")
REPO_TERMINOLOGY = Path("docs/operations/contracts/repo-terminology.yaml")

REQUIRED_METRICS = {
    "bot_prs_opened",
    "bot_prs_merged",
    "bot_prs_failed_before_creation",
    "bot_prs_closed",
    "human_interventions_per_pr",
    "average_time_to_merge",
    "failure_reasons_by_class",
    "candidate_conversion_rate",
    "source_preflight_failure_rate",
    "redirect_canonicalization_rate",
    "deferred_backlog_age",
    "review_backlog_age",
    "queue_denials_by_lane",
    "queue_deferrals_by_lane",
    "stale_evidence_denials",
    "chatops_command_decisions_by_status",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_observability_contract_exists_and_parses():
    assert BOT_OBSERVABILITY_DOC.exists()
    contract = load_yaml(BOT_OBSERVABILITY)

    assert contract["contract"] == "bot-observability"
    assert contract["source_document"] == "docs/operations/BOT_OBSERVABILITY.md"
    assert contract["outputs"]["json"] == "maintenance/bot-observability-scorecard.json"
    assert contract["missing_input_behavior"]["missing_inputs_are_reported"] is True


def test_required_metric_names_are_declared():
    contract = load_yaml(BOT_OBSERVABILITY)
    declared = {metric["name"] for metric in contract["metrics"]}

    assert declared == REQUIRED_METRICS
    assert set(METRIC_NAMES) == REQUIRED_METRICS


def test_scorecard_builds_with_missing_optional_inputs(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)

    scorecard = build_scorecard(tmp_path, contract)

    assert scorecard["report_type"] == "bot_observability_scorecard"
    assert scorecard["completeness"]["missing_input_count"] == scorecard["completeness"]["input_count"]
    assert scorecard["metrics"]["queue_denials_by_lane"]["confidence"] == "missing"
    assert scorecard["metrics"]["bot_prs_opened"]["confidence"] == "not_available_without_github_api"
    assert scorecard["missing_inputs"]


def test_scorecard_builds_with_sample_queue_report(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    write_json(
        tmp_path / "maintenance/bot-queue-report.json",
        [
            {"report_type": "bot_queue_decision", "lane_id": "catalog_growth_promotion", "decision": "deny", "reasons": ["unknown_lane"]},
            {
                "report_type": "bot_queue_decision",
                "lane_id": "source_repair",
                "decision": "defer",
                "reasons": ["stale_evidence"],
                "stale_evidence": {"stale": True},
            },
        ],
    )

    scorecard = build_scorecard(tmp_path, contract)

    assert scorecard["metrics"]["queue_denials_by_lane"]["value"] == {"catalog_growth_promotion": 1}
    assert scorecard["metrics"]["queue_deferrals_by_lane"]["value"] == {"source_repair": 1}
    assert scorecard["metrics"]["stale_evidence_denials"]["value"] == 1
    assert scorecard["metrics"]["bot_prs_failed_before_creation"]["value"] == 1


def test_scorecard_builds_with_sample_failure_routing_report(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    write_json(
        tmp_path / "maintenance/bot-failure-routing-report.json",
        [
            {"report_type": "bot_failure_routing", "matched_failure_code": "source_preflight_failure", "classification": "taxonomy_match", "stop_lane": False},
            {
                "report_type": "bot_failure_routing",
                "matched_failure_code": "redirect_canonicalization_failure",
                "classification": "taxonomy_match",
                "stop_lane": True,
            },
        ],
    )

    scorecard = build_scorecard(tmp_path, contract)

    assert scorecard["metrics"]["failure_reasons_by_class"]["value"] == {
        "redirect_canonicalization_failure": 1,
        "source_preflight_failure": 1,
    }
    assert scorecard["metrics"]["source_preflight_failure_rate"]["value"] == 0.5
    assert scorecard["metrics"]["redirect_canonicalization_rate"]["value"] == 0.5
    assert scorecard["metrics"]["bot_prs_failed_before_creation"]["value"] == 1


def test_failure_reasons_are_grouped_by_taxonomy_code(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    write_json(
        tmp_path / "maintenance/bot-failure-routing-report.json",
        [
            {"report_type": "bot_failure_routing", "matched_failure_code": "stale_evidence_failure", "classification": "taxonomy_match"},
            {"report_type": "bot_failure_routing", "matched_failure_code": "stale_evidence_failure", "classification": "taxonomy_match"},
            {"report_type": "bot_failure_routing", "matched_failure_code": None, "classification": "manual_review_required"},
        ],
    )

    scorecard = build_scorecard(tmp_path, contract)

    assert scorecard["groups"]["failure_reasons_by_class"] == {
        "manual_review_required": 1,
        "stale_evidence_failure": 2,
    }


def test_queue_deferrals_are_grouped_by_lane(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    write_json(
        tmp_path / "maintenance/bot-queue-report.json",
        [
            {"report_type": "bot_queue_decision", "lane_id": "source_repair", "decision": "defer", "reasons": ["cooldown_after_failure_active"]},
            {"report_type": "bot_queue_decision", "lane_id": "source_repair", "decision": "defer", "reasons": ["max_open_prs_exceeded"]},
        ],
    )

    scorecard = build_scorecard(tmp_path, contract)

    assert scorecard["groups"]["queue_deferrals_by_lane"] == {"source_repair": 2}


def test_chatops_decisions_are_grouped_by_status(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    write_json(
        tmp_path / "maintenance/bot-chatops-decision.json",
        [
            {"report_type": "bot_chatops_decision", "decision": "accepted_report_only"},
            {"report_type": "bot_chatops_decision", "decision": "denied"},
            {"report_type": "bot_chatops_decision", "decision": "denied"},
        ],
    )

    scorecard = build_scorecard(tmp_path, contract)

    assert scorecard["metrics"]["chatops_command_decisions_by_status"]["value"] == {
        "accepted_report_only": 1,
        "denied": 2,
    }


def test_output_json_is_deterministic(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    write_json(tmp_path / "maintenance/bot-queue-report.json", {"report_type": "bot_queue_decision", "lane_id": "source_repair", "decision": "allow"})

    first = build_scorecard(tmp_path, contract)
    second = build_scorecard(tmp_path, contract)

    assert first == second


def test_output_markdown_is_deterministic(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    scorecard = build_scorecard(tmp_path, contract)

    first = render_markdown(scorecard, contract)
    second = render_markdown(scorecard, contract)

    assert first == second
    for section in contract["expected_markdown_sections"]:
        assert f"## {section}" in first


def test_missing_data_section_is_explicit(tmp_path):
    contract = load_yaml(BOT_OBSERVABILITY)
    markdown = render_markdown(build_scorecard(tmp_path, contract), contract)

    assert "## Missing Inputs" in markdown
    assert "maintenance/bot-queue-report.json" in markdown
    assert "missing local bot reports" in markdown.lower()


def test_cli_writes_json_and_markdown(tmp_path):
    out_json = tmp_path / "scorecard.json"
    out_md = tmp_path / "scorecard.md"

    result = main(["build", "--out-json", str(out_json), "--out-md", str(out_md)])

    assert result == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["report_type"] == "bot_observability_scorecard"
    assert "# OpenVA Bot Observability Scorecard" in out_md.read_text(encoding="utf-8")


def test_no_catalog_data_mutation(tmp_path):
    before = data_vendor_digest()

    build_scorecard(tmp_path, load_yaml(BOT_OBSERVABILITY))

    assert data_vendor_digest() == before


def test_no_github_api_calls_are_introduced():
    source = Path("tools/openva/bot_observability.py").read_text(encoding="utf-8").lower()

    assert "api.github.com" not in source
    assert "urllib" not in source
    assert "requests" not in source
    assert "gh " not in source


def test_deprecated_terminology_is_not_introduced():
    deprecated_terms = set(load_yaml(REPO_TERMINOLOGY)["deprecated_terms"])
    paths = [
        BOT_OBSERVABILITY_DOC,
        BOT_OBSERVABILITY,
        Path("tools/openva/bot_observability.py"),
        Path("tests/test_bot_observability.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for term in deprecated_terms:
        assert term not in combined
