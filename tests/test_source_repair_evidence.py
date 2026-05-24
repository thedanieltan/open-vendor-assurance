import pytest

from tools.openva.source_repair_evidence import build_source_repair_evidence


def scan(rows):
    return {
        "report_type": "confirmed_p0_source_refinement_scan",
        "generated_at": "2026-05-24T00:00:00Z",
        "prior_report_run_id": "1",
        "fresh_report_run_id": "2",
        "prior_report_generated_at": "2026-05-23T01:00:00Z",
        "fresh_report_generated_at": "2026-05-23T02:00:00Z",
        "confirmed_p0": rows,
    }


def row(status="not_found", http_status=404):
    return {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-dpa",
        "source_url": "url-a",
        "prior_status": status,
        "fresh_status": status,
        "prior_http_status": http_status,
        "fresh_http_status": http_status,
        "prior_final_url": "url-a",
        "fresh_final_url": "url-a",
        "prior_verified_at": "2026-05-23T01:00:00Z",
        "fresh_verified_at": "2026-05-23T02:00:00Z",
    }


def test_builds_raw_original_evidence_without_replacement_or_automerge_signal():
    report = build_source_repair_evidence(scan([row()]))

    assert report["report_type"] == "p0_source_repair_evidence"
    assert report["summary"] == {
        "repair_evidence_count": 1,
        "contains_replacement_evidence": False,
        "contains_automerge_recommendation": False,
    }
    assert report["posture"]["contains_replacement_evidence"] is False
    assert report["posture"]["contains_automerge_recommendation"] is False
    assert "eligible" not in str(report).lower()
    repair = report["repairs"][0]
    assert repair["replacement"] is None
    assert repair["proposed_change"] is None
    assert repair["original"]["prior"]["verification_status"] == "not_found"
    assert repair["original"]["fresh"]["verification_status"] == "not_found"


def test_accepts_confirmed_gone_pair():
    report = build_source_repair_evidence(scan([row(status="gone", http_status=410)]))

    assert report["summary"]["repair_evidence_count"] == 1
    assert report["repairs"][0]["original"]["fresh"]["verification_status"] == "gone"


def test_rejects_non_confirmed_status_pair():
    bad = row()
    bad["fresh_status"] = "ok"
    bad["fresh_http_status"] = 200

    with pytest.raises(ValueError, match="non-confirmed status pair"):
        build_source_repair_evidence(scan([bad]))


def test_rejects_missing_required_fields():
    bad = row()
    del bad["fresh_verified_at"]

    with pytest.raises(ValueError, match="missing required field"):
        build_source_repair_evidence(scan([bad]))
