import json
from pathlib import Path

import yaml

from tools.openva.source_repair_actions import build_repair_action_plan, apply_repair_actions


def write_source(root: Path):
    path = root / "data" / "vendors" / "vendor-a" / "sources" / "vendor-a-dpa.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "source_id": "vendor-a-dpa",
                "vendor_id": "vendor-a",
                "source_type": "dpa",
                "title_native": "Vendor A DPA",
                "source_url": "https://example.com/old-dpa",
                "source_language": "en",
                "source_authority_class": "vendor_legal_terms",
                "access_class": "public_web",
                "rights_class": "public_link_only",
                "catalog_tier": "machine_validated",
                "review_state": "auto_validated",
                "advisory_boundary": "non_advisory",
                "provenance": {
                    "publisher": "vendor",
                    "collected_at": "2026-05-24T00:00:00Z",
                    "observer": "agent",
                    "confidence": "medium",
                },
                "not_advice": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def validation_report(**updates):
    row = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-dpa",
        "source_type": "dpa",
        "original_source_url": "https://example.com/old-dpa",
        "replacement_source_url": "https://example.com/new-dpa",
        "replacement_verification_status": "ok",
        "replacement_http_status": 200,
        "replacement_semantic_status": "strong",
        "replacement_authority_status": "vendor_controlled",
        "replacement_access_status": "public",
        "replacement_url_safety_status": "passed",
        "reasons": [],
    }
    row.update(updates)
    return {
        "report_type": "p0_source_repair_plan_validation",
        "approved": [row],
        "rejected": [],
        "unmatched": [],
    }


def test_plans_update_for_matching_approved_row(tmp_path):
    write_source(tmp_path)

    report = build_repair_action_plan(validation_report(), root=tmp_path)

    assert report["summary"] == {
        "approved_repairs_seen": 1,
        "file_actions_planned": 1,
        "blocked_repairs": 0,
    }
    assert report["file_actions"][0]["action"] == "update"
    assert report["posture"]["mutates_catalog"] is False


def test_apply_updates_source_url_and_human_review_metadata(tmp_path, monkeypatch):
    source_path = write_source(tmp_path)
    monkeypatch.setattr("tools.openva.source_repair_actions.build_indexes", lambda: 0)

    report = apply_repair_actions(validation_report(), root=tmp_path)
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))

    assert report["summary"]["file_actions_applied"] == 1
    assert report["posture"]["mutates_catalog"] is True
    assert source["source_url"] == "https://example.com/new-dpa"
    assert source["review_state"] == "human_reviewed"
    assert source["catalog_tier"] == "human_reviewed"
    assert source["provenance"]["observer"] == "human"
    assert source["provenance"]["confidence"] == "high"
    assert source["source_repair"]["original_source_url"] == "https://example.com/old-dpa"


def test_blocks_if_current_source_no_longer_matches_original_url(tmp_path):
    write_source(tmp_path)
    bad = validation_report(original_source_url="https://example.com/not-current")

    report = build_repair_action_plan(bad, root=tmp_path)

    assert report["summary"]["blocked_repairs"] == 1
    assert report["file_actions"][0]["action"] == "blocked"
    assert report["blocked"][0]["reasons"] == ["source_file_url_mismatch"]


def test_rejects_validation_rows_with_reasons(tmp_path):
    write_source(tmp_path)
    bad = validation_report(reasons=["replacement_semantic_status_not_strong"])

    try:
        build_repair_action_plan(bad, root=tmp_path)
    except ValueError as error:
        assert "approved row must not contain rejection reasons" in str(error)
    else:
        raise AssertionError("expected ValueError")
