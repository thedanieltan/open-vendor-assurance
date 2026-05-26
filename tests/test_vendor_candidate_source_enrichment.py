from pathlib import Path

from tools.openva.source_verification import FetchResult
from tools.openva.vendor_candidate_source_enrichment import build_enrichment_report


def vendor_candidate(vendor_id="vendor-a", domain="vendor-a.example"):
    return {
        "candidate_vendor_id": vendor_id,
        "display_name_candidate": "Vendor A",
        "official_domain_candidate": domain,
        "coverage_lane": "security",
        "cohort_id": "security-001",
        "source_index_url": f"https://{domain}",
        "requires_review": True,
        "writes_canonical_vendors": False,
        "non_advisory": True,
    }


def vendor_report(rows):
    return {
        "schema_version": "0.1.0",
        "report_type": "vendor_candidate_discovery_report",
        "vendor_candidates": rows,
    }


def fetcher(url: str) -> FetchResult:
    if url.endswith("/security"):
        return FetchResult(
            url=url,
            final_url=url,
            http_status=200,
            content_type="text/html",
            body_sample="<html><title>Security</title><body>Security encryption SOC 2 compliance</body></html>",
            error=None,
            skipped_reason=None,
        )
    return FetchResult(
        url=url,
        final_url=url,
        http_status=404,
        content_type="text/html",
        body_sample="not found",
        error=None,
        skipped_reason=None,
    )


def test_enrichment_discovers_sources_for_vendor_candidates(tmp_path: Path):
    report = build_enrichment_report(
        vendor_report([vendor_candidate()]),
        root=tmp_path,
        fetcher=fetcher,
        source_types=("security_page",),
    )

    assert report["report_type"] == "source_discovery_report"
    assert report["discovery_context"] == "vendor_candidate_source_enrichment"
    assert report["posture"]["writes_repository_state"] is False
    assert report["posture"]["writes_canonical_sources"] is False
    assert report["summary"]["vendor_candidates_checked"] == 1
    assert report["summary"]["candidate_sources_written_or_reported"] == 1
    candidate = report["vendors"][0]["candidates"][0]
    assert candidate["vendor_id"] == "vendor-a"
    assert candidate["candidate_url"] == "https://vendor-a.example/security"
    assert candidate["confidence"] == "likely"


def test_enrichment_respects_vendor_limit(tmp_path: Path):
    report = build_enrichment_report(
        vendor_report([
            vendor_candidate("vendor-a", "vendor-a.example"),
            vendor_candidate("vendor-b", "vendor-b.example"),
        ]),
        root=tmp_path,
        fetcher=fetcher,
        vendor_limit=1,
        source_types=("security_page",),
    )

    assert report["summary"]["vendor_candidates_checked"] == 1
    assert report["vendors"][0]["vendor_id"] == "vendor-a"


def test_enrichment_reports_unavailable_when_no_candidate_matches(tmp_path: Path):
    def always_404(url: str) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            http_status=404,
            content_type="text/html",
            body_sample="not found",
            error=None,
            skipped_reason=None,
        )

    report = build_enrichment_report(
        vendor_report([vendor_candidate()]),
        root=tmp_path,
        fetcher=always_404,
        source_types=("security_page",),
    )

    assert report["summary"]["candidate_sources_written_or_reported"] == 0
    assert report["summary"]["unavailable_sources_written_or_reported"] == 1
    assert report["vendors"][0]["unavailable_sources"][0]["source_type"] == "security_page"
