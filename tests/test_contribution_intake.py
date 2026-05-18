from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.contribution_intake import (
    CONTEXT_LABEL,
    PUBLIC_SOURCES_LABEL,
    REQUEST_TYPE_LABEL,
    SUBMITTER_ROLE_LABEL,
    VENDOR_LABEL,
    extract_urls,
    intake_decision,
    parse_issue_form,
)
from tools.openva.source_verification import FetchResult


def issue_body(
    *,
    request_type: str = "Add a public source to an existing vendor",
    vendor: str = "Stripe",
    urls: str = "- https://stripe.com/legal/new-dpa",
    context: str = "Please add this public data processing page.",
) -> str:
    return f"""### {REQUEST_TYPE_LABEL}

{request_type}

### {VENDOR_LABEL}

{vendor}

### {SUBMITTER_ROLE_LABEL}

contributor

### {PUBLIC_SOURCES_LABEL}

{urls}

### {CONTEXT_LABEL}

{context}
"""


def write_vendor(root: Path, vendor_id: str = "stripe") -> None:
    vendor_dir = root / "data" / "vendors" / vendor_id
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "vendor.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "display_name": "Stripe",
                "legal_name": "Stripe, Inc.",
                "headquarters_country": "US",
                "regions_served": ["global"],
                "official_domains": ["stripe.com"],
                "public_entrypoints": ["https://stripe.com/legal"],
                "vendor_categories": ["payments"],
                "source_policy": {
                    "public_sources_only": True,
                    "gated_materials_excluded": True,
                    "raw_documents_mirrored_by_default": False,
                },
                "status": "active",
                "notes": "Public-source catalog record for Stripe.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def fetch_ok(url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        http_status=200,
        content_type="text/html",
        content_length=80,
        etag=None,
        last_modified=None,
        body_sample=b"Data Processing Addendum processor controller personal data",
    )


def fetch_forbidden(url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        http_status=403,
        content_type="text/html",
        content_length=9,
        etag=None,
        last_modified=None,
        body_sample=b"forbidden",
    )


def test_parse_issue_form_extracts_contributor_inputs():
    sections = parse_issue_form(issue_body())

    assert sections[REQUEST_TYPE_LABEL] == "Add a public source to an existing vendor"
    assert sections[VENDOR_LABEL] == "Stripe"
    assert extract_urls(sections[PUBLIC_SOURCES_LABEL]) == ["https://stripe.com/legal/new-dpa"]
    assert "data processing" in sections[CONTEXT_LABEL]


def test_low_risk_existing_vendor_source_generates_catalog_pr_manifest(tmp_path: Path):
    write_vendor(tmp_path)

    report = intake_decision(
        issue_body(),
        issue_number=42,
        root=tmp_path,
        network_check=True,
        fetcher=fetch_ok,
        generated_at="2026-05-18T00:00:00Z",
    )

    assert report["decision"] == "open_catalog_pr"
    assert report["manifest_path"] == "catalog-batches/intake/issue-42-stripe.yaml"
    assert report["pr"]["title"].startswith("Catalog:")
    assert report["manifest"]["operation"] == "create"
    source = report["manifest"]["vendors"][0]["sources"][0]
    assert source["source_type"] == "dpa"
    assert source["artifact"]["artifact_type"] == "dpa"
    assert source["access_class"] == "public_web"


def test_unknown_vendor_requires_human_review(tmp_path: Path):
    report = intake_decision(issue_body(vendor="Unknown Vendor"), issue_number=43, root=tmp_path)

    assert report["decision"] == "needs_human_review"
    assert "unknown_vendor_requires_human_review" in report["reasons"]


def test_unsafe_and_duplicate_issue_urls_are_rejected(tmp_path: Path):
    write_vendor(tmp_path)

    report = intake_decision(
        issue_body(urls="- http://127.0.0.1/metadata\n- http://127.0.0.1/metadata"),
        issue_number=44,
        root=tmp_path,
    )

    assert report["decision"] == "needs_human_review"
    assert "duplicate_url_in_issue" in report["reasons"]
    assert "unsafe_url" in report["reasons"]


def test_advisory_context_blocks_auto_pr(tmp_path: Path):
    write_vendor(tmp_path)

    report = intake_decision(
        issue_body(context="Please mark this vendor as compliant and low risk."),
        issue_number=45,
        root=tmp_path,
    )

    assert report["decision"] == "needs_human_review"
    assert "advisory_language_needs_human_review" in report["reasons"]


def test_403_network_check_does_not_remove_or_deprecate_source(tmp_path: Path):
    write_vendor(tmp_path)

    report = intake_decision(
        issue_body(),
        issue_number=46,
        root=tmp_path,
        network_check=True,
        fetcher=fetch_forbidden,
    )

    assert report["decision"] == "needs_human_review"
    assert "automated_observation_blocked_not_source_removal" in report["reasons"]
    assert report["posture"]["does_not_remove_sources_from_fetch_failures"] is True
    assert "manifest" not in report
