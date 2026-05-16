from pathlib import Path

from tools.openva.source_verification import (
    FetchResult,
    build_source_verification_report,
    verify_source,
)


def source_record(source_type: str, url: str) -> dict:
    return {
        "vendor_id": "example",
        "source_id": f"example-{source_type}",
        "source_type": source_type,
        "source_url": url,
    }


def html_fetch(url: str, body: str, status: int = 200, final_url: str | None = None) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=final_url or url,
        http_status=status,
        content_type="text/html; charset=utf-8",
        content_length=len(body),
        etag=None,
        last_modified=None,
        body_sample=body.encode("utf-8"),
    )


def test_dpa_with_matching_terms_is_ok():
    source = source_record("dpa", "https://example.com/legal/dpa")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-dpa.yaml"),
        fetcher=lambda url: html_fetch(url, "Data Processing Addendum processor controller"),
    )

    assert result["verification_status"] == "ok"
    assert result["requires_review"] is False
    assert result["semantic_match"]["status"] == "strong"


def test_template_url_with_weak_semantic_match_is_suspect():
    source = source_record("dpa", "https://example.com/legal/data-processing-addendum")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-dpa.yaml"),
        fetcher=lambda url: html_fetch(url, "Data processing"),
    )

    assert result["verification_status"] == "suspect_inferred_url"
    assert result["requires_review"] is True


def test_404_is_not_found():
    source = source_record("subprocessors_list", "https://example.com/legal/subprocessors")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-subprocessors.yaml"),
        fetcher=lambda url: html_fetch(url, "not found", status=404),
    )

    assert result["verification_status"] == "not_found"
    assert result["requires_review"] is True


def test_gated_or_forbidden_source_requires_review():
    source = source_record("security_page", "https://trust.example.com/security")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-security.yaml"),
        fetcher=lambda url: html_fetch(url, "forbidden", status=403),
    )

    assert result["verification_status"] == "forbidden_or_gated"
    assert result["requires_review"] is True


def test_homepage_redirect_requires_review():
    source = source_record("dpa", "https://example.com/legal/dpa")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-dpa.yaml"),
        fetcher=lambda url: html_fetch(
            url,
            "Welcome to Example",
            final_url="https://example.com/",
        ),
    )

    assert result["verification_status"] == "homepage_or_generic_redirect"
    assert result["requires_review"] is True


def test_semantic_mismatch_requires_review():
    source = source_record("subprocessors_list", "https://example.com/legal/subprocessors")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-subprocessors.yaml"),
        fetcher=lambda url: html_fetch(url, "Welcome to our careers page."),
    )

    assert result["verification_status"] == "possible_mismatch"
    assert result["semantic_match"]["status"] == "mismatch"
    assert result["requires_review"] is True


def test_pdf_samples_do_not_attempt_semantic_text_matching():
    source = source_record("dpa", "https://example.com/legal/dpa.pdf")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-dpa.yaml"),
        fetcher=lambda url: FetchResult(
            requested_url=url,
            final_url=url,
            http_status=200,
            content_type="application/pdf",
            content_length=100,
            etag=None,
            last_modified=None,
            body_sample=b"%PDF",
        ),
    )

    assert result["verification_status"] == "ok"
    assert result["semantic_match"]["status"] == "not_evaluated_pdf_sample"


def test_report_is_network_aware_and_non_mutating(tmp_path):
    vendor_dir = tmp_path / "data/vendors/example/sources"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "example-privacy.yaml").write_text(
        "vendor_id: example\n"
        "source_id: example-privacy\n"
        "source_type: privacy_notice\n"
        "source_url: https://example.com/privacy\n",
        encoding="utf-8",
    )

    report = build_source_verification_report(
        root=tmp_path,
        fetcher=lambda url: html_fetch(url, "Privacy policy personal data"),
    )

    assert report["report_type"] == "source_verification_report"
    assert report["posture"] == {
        "network_fetch_performed": True,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "public_sources_only": True,
        "non_advisory": True,
    }
    assert report["summary"]["source_count"] == 1
    assert report["summary"]["sources_requiring_review"] == 0
