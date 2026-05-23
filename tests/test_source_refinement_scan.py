import pytest

from tools.openva.source_refinement_scan import compare_verification_reports


def row(vendor, source_id, url, status, http_status=None):
    return {
        "vendor_id": vendor,
        "source_id": source_id,
        "source_url": url,
        "final_url": url,
        "http_status": http_status,
        "verification_status": status,
        "requires_review": status not in {"ok", "redirected"},
    }


def report(rows, generated_at="2026-05-23T00:00:00Z"):
    return {
        "report_type": "source_verification_report",
        "generated_at": generated_at,
        "sources": rows,
    }


def test_confirms_exact_repeated_p0_status():
    prior = report([
        row("vendor-a", "shared", "url-a", "not_found", 404),
        row("vendor-b", "shared", "url-b", "not_found", 404),
    ], "2026-05-23T01:00:00Z")
    fresh = report([
        row("vendor-a", "shared", "url-a", "not_found", 404),
        row("vendor-b", "shared", "url-b", "ok", 200),
    ], "2026-05-23T02:00:00Z")

    result = compare_verification_reports(prior, fresh)

    assert result["summary"]["confirmed_p0_count"] == 1
    assert result["confirmed_p0"][0]["vendor_id"] == "vendor-a"
    assert result["summary"]["inconclusive_count"] == 1
    assert result["inconclusive"][0]["reason"] == "status_changed_between_runs"


def test_rejects_unknown_status():
    prior = report([row("vendor-a", "dpa", "url-a", "renamed_status", 404)])
    fresh = report([row("vendor-a", "dpa", "url-a", "renamed_status", 404)])

    with pytest.raises(ValueError, match="unknown verification_status"):
        compare_verification_reports(prior, fresh)
