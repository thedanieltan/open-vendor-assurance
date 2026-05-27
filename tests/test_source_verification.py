from pathlib import Path

import pytest

from tools.openva.source_verification import (
    FetchResult,
    build_source_verification_report,
    select_source_shard,
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


def test_http_200_soft_404_is_soft_not_found():
    source = source_record("compliance_page", "https://mixpanel.com/legal/security/#compliance")

    result = verify_source(
        source,
        Path("data/vendors/mixpanel/sources/mixpanel-compliance.yaml"),
        fetcher=lambda url: html_fetch(
            url,
            "<title>404 Error</title><main><h1>404 Error</h1><p>There's nothing here.</p></main>",
        ),
    )

    assert result["verification_status"] == "soft_not_found"
    assert result["soft_404_detected"] is True
    assert result["requires_review"] is True


def test_incidental_404_text_on_valid_page_is_not_soft_not_found():
    source = source_record("security_page", "https://example.com/security")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-security.yaml"),
        fetcher=lambda url: html_fetch(
            url,
            "<title>Security Overview</title><main>Security encryption incident response. "
            "Our logs may include 404 responses for missing assets.</main>",
        ),
    )

    assert result["verification_status"] == "ok"
    assert result["soft_404_detected"] is False


def test_401_login_required_source_requires_review():
    source = source_record("security_page", "https://trust.example.com/security")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-security.yaml"),
        fetcher=lambda url: html_fetch(url, "login required", status=401),
    )

    assert result["verification_status"] == "gated_or_login_required"
    assert result["requires_review"] is True


def test_plain_403_is_forbidden_unknown():
    source = source_record("security_page", "https://trust.example.com/security")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-security.yaml"),
        fetcher=lambda url: html_fetch(url, "forbidden", status=403),
    )

    assert result["verification_status"] == "forbidden_unknown"
    assert result["requires_review"] is True


def test_waf_like_403_is_bot_protected():
    source = source_record("security_page", "https://trust.example.com/security")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-security.yaml"),
        fetcher=lambda url: html_fetch(url, "Checking your browser before accessing", status=403),
    )

    assert result["verification_status"] == "bot_protected"
    assert result["requires_review"] is True


def test_login_like_403_is_gated_or_login_required():
    source = source_record("security_page", "https://trust.example.com/security")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-security.yaml"),
        fetcher=lambda url: html_fetch(url, "Sign in to continue to the trust portal", status=403),
    )

    assert result["verification_status"] == "gated_or_login_required"
    assert result["requires_review"] is True


def test_429_is_rate_limited():
    source = source_record("security_page", "https://trust.example.com/security")

    result = verify_source(
        source,
        Path("data/vendors/example/sources/example-security.yaml"),
        fetcher=lambda url: html_fetch(url, "too many requests", status=429),
    )

    assert result["verification_status"] == "rate_limited"
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
    assert report["scope"] == {
        "total_source_paths": 1,
        "candidate_source_paths": 1,
        "verified_source_paths": 1,
        "source_path_file": None,
        "limit": None,
        "shard_count": None,
        "shard_index": None,
        "is_partial": False,
    }
    assert report["summary"]["source_count"] == 1
    assert report["summary"]["sources_requiring_review"] == 0


def test_select_source_shard_is_stable_and_non_overlapping():
    paths = [Path(f"source-{index}.yaml") for index in range(10)]

    shards = [select_source_shard(paths, 3, index) for index in range(3)]

    assert shards == [
        [Path("source-0.yaml"), Path("source-3.yaml"), Path("source-6.yaml"), Path("source-9.yaml")],
        [Path("source-1.yaml"), Path("source-4.yaml"), Path("source-7.yaml")],
        [Path("source-2.yaml"), Path("source-5.yaml"), Path("source-8.yaml")],
    ]
    assert sorted(path for shard in shards for path in shard) == paths


@pytest.mark.parametrize(
    ("shard_count", "shard_index"),
    [(None, 0), (2, None), (0, 0), (2, -1), (2, 2)],
)
def test_select_source_shard_rejects_invalid_bounds(shard_count, shard_index):
    with pytest.raises(ValueError):
        select_source_shard([Path("source.yaml")], shard_count, shard_index)


def test_report_can_verify_only_one_source_shard(tmp_path):
    for vendor in ["alpha", "bravo", "charlie", "delta"]:
        vendor_dir = tmp_path / f"data/vendors/{vendor}/sources"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / f"{vendor}-privacy.yaml").write_text(
            f"vendor_id: {vendor}\n"
            f"source_id: {vendor}-privacy\n"
            "source_type: privacy_notice\n"
            f"source_url: https://example.com/{vendor}/privacy\n",
            encoding="utf-8",
        )

    fetched_urls: list[str] = []
    report = build_source_verification_report(
        root=tmp_path,
        fetcher=lambda url: fetched_urls.append(url) or html_fetch(url, "Privacy policy personal data"),
        shard_count=2,
        shard_index=1,
    )

    assert report["scope"]["total_source_paths"] == 4
    assert report["scope"]["candidate_source_paths"] == 4
    assert report["scope"]["verified_source_paths"] == 2
    assert report["scope"]["shard_count"] == 2
    assert report["scope"]["shard_index"] == 1
    assert report["scope"]["is_partial"] is True
    assert report["summary"]["source_count"] == 2
    assert fetched_urls == [
        "https://example.com/bravo/privacy",
        "https://example.com/delta/privacy",
    ]


def test_report_can_use_source_path_file_scope(tmp_path):
    for vendor in ["alpha", "bravo"]:
        vendor_dir = tmp_path / f"data/vendors/{vendor}/sources"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / f"{vendor}-privacy.yaml").write_text(
            f"vendor_id: {vendor}\n"
            f"source_id: {vendor}-privacy\n"
            "source_type: privacy_notice\n"
            f"source_url: https://example.com/{vendor}/privacy\n",
            encoding="utf-8",
        )
    scope_file = tmp_path / "source-paths.txt"
    scope_file.write_text("data/vendors/bravo/sources/bravo-privacy.yaml\n", encoding="utf-8")

    report = build_source_verification_report(
        root=tmp_path,
        fetcher=lambda url: html_fetch(url, "Privacy policy personal data"),
        source_path_file=scope_file,
    )

    assert report["scope"]["total_source_paths"] == 2
    assert report["scope"]["candidate_source_paths"] == 1
    assert report["scope"]["verified_source_paths"] == 1
    assert report["scope"]["source_path_file"] == "source-paths.txt"
    assert report["scope"]["is_partial"] is True
    assert [source["vendor_id"] for source in report["sources"]] == ["bravo"]
