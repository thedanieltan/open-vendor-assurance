"""WP40A human-submission bridge tests.

Every supplied URL is verified individually; unsafe and declared-gated URLs are
never fetched; one bad source does not sink a vendor that has enough valid
sources; the bridge produces one deterministic candidate record on the shared
lifecycle.
"""

from __future__ import annotations

from pathlib import Path

from tools.openva import candidate_record as cr
from tools.openva import submission_bridge as sb
from tools.openva.source_verification import FetchResult

OBSERVED_AT = "2026-06-14T00:00:00Z"
NEW_VENDOR_LABELS = ["status:needs-triage", "submission:new-vendor"]


def html_fetch_map(pages: dict[str, tuple[str, int, str | None]]):
    """Build a fetcher keyed by requested URL -> (body, status, final_url)."""

    def fetcher(url: str) -> FetchResult:
        body, status, final_url = pages.get(url, ("", None, None))
        return FetchResult(
            requested_url=url,
            final_url=final_url or url,
            http_status=status,
            content_type="text/html; charset=utf-8" if status else None,
            content_length=len(body) if body else None,
            etag=None,
            last_modified=None,
            body_sample=body.encode("utf-8"),
            error=None if status else "URLError",
        )

    return fetcher


def forbidden_fetcher(url: str) -> FetchResult:
    raise AssertionError(f"fetcher must not be called for {url}")


def new_vendor_body(*, vendor_name="Acme Corp", vendor_domain="acme.example", sources, public_access="Yes - public, no login, paywall, or bot-wall"):
    return "\n".join(
        [
            "### Vendor name", "", vendor_name, "",
            "### Vendor domain", "", vendor_domain, "",
            "### Vendor legal name", "", "Acme Corporation Inc.", "",
            "### Headquarters country", "", "United States", "",
            "### Known public assurance source URLs", "", sources, "",
            "### Public access confirmed", "", public_access, "",
            "### Machine-readable surface", "", "none", "",
        ]
    )


def build(body, fetcher, *, title="Vendor candidate: Acme Corp", labels=None, root=None):
    return sb.build_new_vendor_candidate(
        title,
        body,
        labels if labels is not None else list(NEW_VENDOR_LABELS),
        issue_number=501,
        fetcher=fetcher,
        root=root or Path("."),
        observed_at=OBSERVED_AT,
    )


def test_held_issue_is_skipped():
    record = build(new_vendor_body(sources="https://acme.example/trust"), forbidden_fetcher, labels=["openva-hold", "submission:new-vendor"])
    assert record["skipped"] and record["skip_reason"] == "skipped_hold"


def test_non_submission_issue_is_skipped():
    record = build(new_vendor_body(sources="https://acme.example/trust"), forbidden_fetcher, labels=["bug"])
    assert record["skipped"]


def test_non_new_vendor_form_is_skipped():
    record = build(new_vendor_body(sources="https://acme.example/trust"), forbidden_fetcher,
                   title="Source candidate: Acme", labels=["submission:new-source"])
    assert record["skipped"] and record["skip_reason"] == "skipped_not_new_vendor"


def test_every_supplied_url_is_parsed_and_verified():
    pages = {
        "https://acme.example/trust": ("acme trust center security compliance", 200, None),
        "https://acme.example/dpa": ("data processing addendum processor controller", 200, None),
    }
    body = new_vendor_body(sources="https://acme.example/trust\nhttps://acme.example/dpa")
    record = build(body, html_fetch_map(pages))
    urls = {s["candidate_url"] for s in record["source_candidates"]}
    assert urls == set(pages)
    assert len(record["evidence_references"]) == 2
    for source in record["source_candidates"]:
        assert source["http_status"] == 200
        assert source["evidence_digest"].startswith("sha256:")


def test_unsafe_url_is_never_fetched():
    # an internal IP must be rejected on safety before any fetch
    body = new_vendor_body(sources="https://acme.example/trust\nhttp://10.0.0.1/secret")

    fetched: list[str] = []

    def tracking_fetch(url: str) -> FetchResult:
        fetched.append(url)
        return FetchResult(url, url, 200, "text/html", 10, None, None, b"acme trust center security compliance")

    record = build(body, tracking_fetch)
    assert "http://10.0.0.1/secret" not in fetched
    unsafe = [s for s in record["source_candidates"] if s["candidate_url"] == "http://10.0.0.1/secret"][0]
    assert unsafe["access_state"] == "unsafe_url"
    # the good source survives -> vendor still eligible
    assert record["eligibility_state"] == "eligible"


def test_declared_gated_source_is_never_fetched():
    body = new_vendor_body(sources="https://acme.example/trust", public_access="No - gated or restricted")
    record = build(body, forbidden_fetcher)
    source = record["source_candidates"][0]
    assert source["access_state"] == "declared_gated"
    assert record["eligibility_state"] == "rejected_gated"


def test_duplicate_vendor_rejected(tmp_path):
    # seed an existing vendor whose domain matches the submission
    vendor_dir = tmp_path / "data" / "vendors" / "acme"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "vendor.yaml").write_text(
        "vendor_id: acme\nvendor_name: Acme Corp\nofficial_domains:\n  - acme.example\n", encoding="utf-8"
    )
    pages = {"https://acme.example/trust": ("acme trust center security compliance", 200, None)}
    record = build(new_vendor_body(sources="https://acme.example/trust"), html_fetch_map(pages), root=tmp_path)
    assert record["eligibility_state"] == "rejected_duplicate"
    assert record["vendor_identity_candidate"]["matches_existing_vendor_id"] == "acme"


def test_insufficient_source_coverage_defers():
    # the only source fails to fetch -> no usable assurance source
    pages = {"https://acme.example/trust": ("", None, None)}
    record = build(new_vendor_body(sources="https://acme.example/trust"), html_fetch_map(pages))
    assert record["eligibility_state"] == "deferred_insufficient_evidence"


def test_eligible_submission_produces_one_candidate():
    pages = {"https://acme.example/trust": ("acme trust center security compliance encryption", 200, None)}
    record = build(new_vendor_body(sources="https://acme.example/trust"), html_fetch_map(pages))
    assert record["eligibility_state"] == "eligible"
    assert record["candidate_id"] == "cand-human-submission-issue-501"
    assert record["candidate_origin"] == "human_submission"
    assert cr.validate_candidate(record) == []


def test_candidate_generation_is_deterministic():
    pages = {"https://acme.example/trust": ("acme trust center security compliance", 200, None)}
    body = new_vendor_body(sources="https://acme.example/trust")
    first = build(body, html_fetch_map(pages))
    second = build(body, html_fetch_map(pages))
    assert first == second


def test_redirect_chain_and_final_url_recorded():
    pages = {"https://acme.example/trust": ("acme trust center security", 200, "https://trust.acme.example/")}
    record = build(new_vendor_body(sources="https://acme.example/trust"), html_fetch_map(pages))
    source = record["source_candidates"][0]
    assert source["final_url"] == "https://trust.acme.example/"
    assert source["redirect_chain"] == ["https://acme.example/trust", "https://trust.acme.example/"]


def test_bot_protected_source_recorded_not_bypassed():
    pages = {"https://acme.example/trust": ("Just a moment... cloudflare cf-ray attention required", 403, None)}
    record = build(new_vendor_body(sources="https://acme.example/trust"), html_fetch_map(pages))
    source = record["source_candidates"][0]
    assert source["access_state"] in {"bot_protected", "gated_or_auth_required"}
    assert source["source_role"] == "rejected"
