from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tools.openva.bot_failure_router import load_taxonomy, main, route_failure

BOT_FAILURE_ROUTER_DOC = Path("docs/operations/BOT_FAILURE_ROUTER.md")
BOT_FAILURE_TAXONOMY = Path("docs/operations/contracts/bot-failure-taxonomy.yaml")
REQUIRED_ROUTING_FIELDS = {
    "code",
    "summary",
    "retry_eligible",
    "retry_policy",
    "escalation_target",
    "open_or_update_hardening_issue",
    "defer_candidate",
    "stop_lane",
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def taxonomy_codes() -> list[str]:
    return [entry["code"] for entry in load_yaml(BOT_FAILURE_TAXONOMY)["failure_classes"]]


def data_vendor_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("data/vendors").rglob("*")):
        if path.is_file():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_failure_router_doc_exists():
    assert BOT_FAILURE_ROUTER_DOC.exists()
    text = BOT_FAILURE_ROUTER_DOC.read_text(encoding="utf-8")
    assert "WP10 dashboard" in text
    assert "does not create or update GitHub issues" in text


def test_explicit_code_classification_for_every_taxonomy_code():
    for code in taxonomy_codes():
        report = route_failure(
            {
                "version": 1,
                "lane_id": "catalog_growth_promotion",
                "failure": {"code": code, "message": f"explicit {code}"},
            }
        )
        assert report["matched_failure_code"] == code
        assert report["classification"] == "taxonomy_match"
        assert report["match_confidence"] == "explicit"
        assert report["match_basis"] == "failure.code"


def test_message_based_classification_for_known_examples():
    examples = {
        "Unexpected inputs provided: max_promotion_actions_per_pr": "workflow_input_compatibility_failure",
        "schema validation failed for bot contract": "schema_validation_failure",
        "generated files are stale after build-indexes": "generated_drift_failure",
        "permission denied by bot authority for write action": "permission_policy_denial",
        "source preflight failed for changed source records": "source_preflight_failure",
        "redirect canonicalization failure for final URL": "redirect_canonicalization_failure",
        "external fetch instability while probing source host": "external_fetch_instability",
        "automerge lane mismatch for strict-growth PR": "automerge_lane_mismatch",
    }

    for message, expected_code in examples.items():
        report = route_failure(
            {
                "version": 1,
                "lane_id": "catalog_growth_promotion",
                "failure": {"message": message},
            }
        )
        assert report["matched_failure_code"] == expected_code
        assert report["match_confidence"] == "message"


def test_unknown_messages_do_not_get_unsafe_classifications():
    report = route_failure(
        {
            "version": 1,
            "lane_id": "catalog_growth_promotion",
            "failure": {"message": "something unusual happened in the runner"},
        }
    )

    assert report["matched_failure_code"] is None
    assert report["classification"] == "manual_review_required"
    assert report["retry_eligible"] is False
    assert report["stop_lane"] is True


def test_routing_output_includes_required_behavior_fields():
    report = route_failure(
        {
            "version": 1,
            "lane_id": "catalog_growth_promotion",
            "failure": {"code": "source_preflight_failure"},
        }
    )

    assert report["retry_eligible"] is True
    assert report["retry_policy"]
    assert report["escalation_target"] == "source-maintainer"
    assert report["defer_candidate"] is True
    assert report["stop_lane"] is False
    assert report["next_safe_action"]
    assert report["explanation"]


def test_taxonomy_entries_cannot_miss_required_routing_behavior():
    taxonomy = load_taxonomy()
    for entry in taxonomy["failure_classes"]:
        assert REQUIRED_ROUTING_FIELDS <= set(entry), entry["code"]
        assert isinstance(entry["retry_eligible"], bool)
        assert entry["retry_policy"]
        assert entry["escalation_target"]
        assert isinstance(entry["open_or_update_hardening_issue"], bool)
        assert isinstance(entry["defer_candidate"], bool)
        assert isinstance(entry["stop_lane"], bool)


def test_router_output_is_deterministic():
    observation = {
        "version": 1,
        "lane_id": "catalog_growth_promotion",
        "failure": {
            "code": "stale_evidence_failure",
            "message": "Evidence is older than strict-growth stale evidence limit.",
            "artifact": "promotion-plan.json",
        },
    }

    assert route_failure(observation) == route_failure(observation)


def test_router_does_not_mutate_catalog_data():
    before = data_vendor_digest()

    route_failure(
        {
            "version": 1,
            "lane_id": "catalog_growth_promotion",
            "failure": {"code": "permission_policy_denial"},
        }
    )

    assert data_vendor_digest() == before


def test_router_integrates_with_queue_output_for_stale_evidence():
    report = route_failure(
        {
            "version": 1,
            "lane_id": "catalog_growth_promotion",
            "queue_report": {
                "decision": "defer",
                "reasons": ["stale_evidence"],
            },
        }
    )

    assert report["matched_failure_code"] == "stale_evidence_failure"
    assert report["match_confidence"] == "queue_report"
    assert "queue_report.reasons" in report["match_basis"]


def test_router_integrates_with_queue_output_for_permission_denial():
    report = route_failure(
        {
            "version": 1,
            "lane_id": "catalog_growth_promotion",
            "queue_report": {
                "decision": "deny",
                "reasons": ["lane_not_write_capable"],
            },
        }
    )

    assert report["matched_failure_code"] == "permission_policy_denial"
    assert report["defer_candidate"] is False
    assert report["stop_lane"] is True


def test_router_integrates_with_queue_pause_for_permission_denial():
    report = route_failure(
        {
            "version": 1,
            "lane_id": "source_repair",
            "queue_report": {
                "decision": "pause",
                "reasons": ["pause_switch_active"],
            },
        }
    )

    assert report["matched_failure_code"] == "permission_policy_denial"
    assert report["match_confidence"] == "queue_report"


def test_cli_writes_routing_report_and_markdown(tmp_path):
    input_path = tmp_path / "failure.yaml"
    out_path = tmp_path / "routing.json"
    out_md = tmp_path / "routing.md"
    input_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "lane_id": "catalog_growth_promotion",
                "failure": {
                    "code": "stale_evidence_failure",
                    "message": "Evidence is older than strict-growth stale evidence limit.",
                    "artifact": "promotion-plan.json",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = main(
        [
            "classify",
            "--input",
            str(input_path),
            "--out",
            str(out_path),
            "--out-md",
            str(out_md),
        ]
    )

    assert result == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["matched_failure_code"] == "stale_evidence_failure"
    assert report["next_safe_action"]
    assert "# OpenVA Bot Failure Routing" in out_md.read_text(encoding="utf-8")
