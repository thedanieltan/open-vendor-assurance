from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from tools.openva.bot_queue import evaluate, load_policy, load_state, main

BOT_QUEUE_STATE_SCHEMA = Path("docs/operations/contracts/bot-queue-state.schema.yaml")
NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def clean_state(lane_id: str = "catalog_growth_promotion") -> dict:
    return {
        "version": 1,
        "lane_id": lane_id,
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "evidence": {"generated_at": "2026-06-07T11:00:00Z"},
        "pause": {"active": False},
        "requested_action": {
            "duplicate_key": "batch-001",
            "vendor_domain": "example.com",
            "source_host": "example.com",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
        },
    }


def test_queue_state_contract_exists_and_parses():
    contract = load_yaml(BOT_QUEUE_STATE_SCHEMA)

    assert contract["contract"] == "bot-queue-state-schema"
    assert contract["source_document"] == "docs/operations/BOT_QUEUE_ENFORCER.md"
    assert set(contract["decisions"]) == {"allow", "defer", "deny", "pause"}
    assert "lane_id" in contract["required_fields"]


def test_unknown_lane_is_denied():
    report = evaluate("unknown_lane", clean_state("unknown_lane"), now=NOW)

    assert report["decision"] == "deny"
    assert "unknown_lane" in report["reasons"]
    assert "authority.lanes" in report["violated_policies"]


def test_lane_not_in_queue_policy_is_denied():
    report = evaluate("catalog_growth_discovery", clean_state("catalog_growth_discovery"), now=NOW)

    assert report["decision"] == "deny"
    assert "lane_missing_queue_policy" in report["reasons"]


def test_lane_without_write_authority_is_denied_even_if_queue_declares_it():
    policies = load_policy()
    policies["queue"]["lanes"].append(
        {
            "lane_id": "catalog_quality",
            "max_open_prs": 1,
            "max_actions_per_pr": 1,
            "schedule_window": "manual_only",
            "duplicate_pr_policy": "do_not_create_duplicate_quality_prs",
            "base_change_policy": "rebase_before_merge",
            "source_host_rate_limit": "conservative",
            "vendor_domain_concurrency_limit": 1,
            "stale_evidence_max_age_hours": 24,
        }
    )

    report = evaluate("catalog_quality", clean_state("catalog_quality"), policies=policies, now=NOW)

    assert report["decision"] == "deny"
    assert "lane_not_write_capable" in report["reasons"]


def test_pause_switch_causes_pause_decision():
    state = clean_state()
    state["pause"] = {"active": True, "reason": "maintainer hold"}

    report = evaluate("catalog_growth_promotion", state, now=NOW)

    assert report["decision"] == "pause"
    assert "pause_switch_active" in report["reasons"]


def test_max_open_pr_limit_causes_defer():
    state = clean_state()
    state["open_prs"] = [
        {
            "number": 123,
            "title": "Catalog growth promotion",
            "lane_id": "catalog_growth_promotion",
            "created_at": "2026-06-07T00:00:00Z",
        }
    ]

    report = evaluate("catalog_growth_promotion", state, now=NOW)

    assert report["decision"] == "defer"
    assert "max_open_prs_exceeded" in report["reasons"]


def test_max_daily_and_weekly_pr_limits_cause_defer():
    state = clean_state()
    state["recent_bot_prs"] = {"day_count": 3, "week_count": 10}

    report = evaluate("catalog_growth_promotion", state, now=NOW)

    assert report["decision"] == "defer"
    assert "max_bot_prs_per_day_exceeded" in report["reasons"]
    assert "max_bot_prs_per_week_exceeded" in report["reasons"]


def test_cooldown_after_failure_causes_defer():
    state = clean_state()
    state["last_failure"] = {
        "code": "source_preflight_failure",
        "occurred_at": "2026-06-07T00:00:00Z",
    }

    report = evaluate("catalog_growth_promotion", state, now=NOW)

    assert report["decision"] == "defer"
    assert "cooldown_after_failure_active" in report["reasons"]
    assert report["cooldown"]["active"] is True


def test_stale_evidence_causes_defer():
    state = clean_state()
    state["evidence"] = {"generated_at": "2026-06-07T00:00:00Z"}

    report = evaluate("catalog_growth_promotion", state, now=NOW)

    assert report["decision"] == "defer"
    assert "stale_evidence" in report["reasons"]
    assert report["stale_evidence"]["stale"] is True


def test_duplicate_pr_policy_causes_defer():
    state = clean_state()
    state["open_prs"] = [
        {
            "number": 124,
            "title": "Catalog growth promotion",
            "lane_id": "catalog_growth_promotion",
            "created_at": "2026-06-07T00:00:00Z",
            "duplicate_key": "batch-001",
        }
    ]

    report = evaluate("catalog_growth_promotion", state, now=NOW)

    assert report["decision"] == "defer"
    assert "duplicate_pr_policy" in report["reasons"]
    assert report["duplicate_pr"]["duplicate_open_pr_numbers"] == [124]


def test_clean_state_allows():
    report = evaluate("catalog_growth_promotion", clean_state(), now=NOW)

    assert report["decision"] == "allow"
    assert report["reasons"] == ["queue_policy_satisfied"]


def test_decision_report_is_deterministic_and_includes_next_safe_action():
    first = evaluate("catalog_growth_promotion", clean_state(), now=NOW)
    second = evaluate("catalog_growth_promotion", clean_state(), now=NOW)

    assert first == second
    assert first["next_safe_action"]
    assert first["referenced_queue_policy_values"]["lane"]["lane_id"] == "catalog_growth_promotion"
    assert first["referenced_authority_values"]["deny_by_default"] is True


def test_cli_writes_report(tmp_path):
    state_path = tmp_path / "state.yaml"
    out_path = tmp_path / "report.json"
    state_path.write_text(yaml.safe_dump(clean_state(), sort_keys=True), encoding="utf-8")

    result = main(
        [
            "evaluate",
            "--lane",
            "catalog_growth_promotion",
            "--state",
            str(state_path),
            "--out",
            str(out_path),
            "--now",
            "2026-06-07T12:00:00Z",
        ]
    )

    assert result == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["decision"] == "allow"
    assert report["next_safe_action"]


def test_report_only_mode_does_not_mutate_catalog_data():
    before = data_vendor_digest()

    evaluate("catalog_growth_promotion", clean_state(), now=NOW)

    assert data_vendor_digest() == before


def test_queue_enforcer_respects_deny_by_default():
    policies = load_policy()
    for lane in policies["authority"]["lanes"]:
        if lane["id"] == "catalog_growth_promotion":
            lane["deny_by_default"] = False

    report = evaluate("catalog_growth_promotion", clean_state(), policies=policies, now=NOW)

    assert report["decision"] == "deny"
    assert "lane_not_deny_by_default" in report["reasons"]


def test_load_state_applies_defaults(tmp_path):
    state_path = tmp_path / "state.yaml"
    state_path.write_text(
        "version: 1\nlane_id: catalog_growth_promotion\nrecent_bot_prs: null\npause: null\n",
        encoding="utf-8",
    )

    state = load_state(state_path)

    assert state["open_prs"] == []
    assert state["recent_bot_prs"] == {"day_count": 0, "week_count": 0}
    assert state["pause"] == {"active": False}
