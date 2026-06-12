from pathlib import Path

import yaml

from tools.openva.contribution_intake import ADVISORY_RE
from tools.openva.source_verification import FetchResult
from tools.openva.submission_fields import (
    FORM_FIELD_LABELS,
    FORM_TEMPLATES,
    TITLE_PREFIXES,
    detect_form_kind,
)
from tools.openva.submission_verify import (
    CANDIDATE_LABELS,
    COMMENT_FILENAME,
    COMMENT_MARKER,
    NO_REVIEW_RESULTS,
    REPORT_FILENAME,
    RESULT_LABELS,
    SKIPPED_HOLD,
    SKIPPED_NOT_SUBMISSION,
    VERIFICATION_RESULTS,
    preflight_skip,
    render_comment,
    verify_submission,
    write_outputs,
)

ISSUE_TEMPLATE_DIR = Path(".github/ISSUE_TEMPLATE")
OBSERVED_AT = "2026-06-12T00:00:00Z"
SUBMISSION_LABELS = ["status:needs-triage", "submission:new-source"]

NOTES_SENTINEL = "SENTINEL-SUBMITTER-NOTES-DO-NOT-ECHO"
AUTHORITATIVE_SENTINEL = "SENTINEL-AUTHORITATIVE-DO-NOT-ECHO"
BODY_SENTINEL = "SENTINEL-PAGE-BODY-DO-NOT-ECHO"


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


def failing_fetch(url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        http_status=None,
        content_type=None,
        content_length=None,
        etag=None,
        last_modified=None,
        body_sample=b"",
        error="URLError",
    )


def forbidden_fetcher(url: str):
    raise AssertionError("fetcher must not be called")


def new_source_body(
    *,
    source_url: str = "https://vendor.example/legal/dpa",
    vendor_domain: str = "vendor.example",
    source_type: str = "dpa",
    public_access: str = "Yes - public, no login, paywall, or bot-wall",
    belief: str = "This is the vendor's canonical page for this source type",
    surface: str = "none",
) -> str:
    return "\n".join(
        [
            "### Vendor name",
            "",
            "Example Vendor",
            "",
            "### Vendor domain",
            "",
            vendor_domain,
            "",
            "### OpenVA vendor ID",
            "",
            "_No response_",
            "",
            "### Source URL",
            "",
            source_url,
            "",
            "### Source type",
            "",
            source_type,
            "",
            "### Canonical location belief",
            "",
            belief,
            "",
            "### Why this is authoritative",
            "",
            AUTHORITATIVE_SENTINEL,
            "",
            "### Public access confirmed",
            "",
            public_access,
            "",
            "### Machine-readable surface",
            "",
            surface,
            "",
            "### Submitter notes",
            "",
            NOTES_SENTINEL,
            "",
        ]
    )


def verify(
    body: str,
    *,
    fetcher,
    title: str = "Source candidate: Example Vendor DPA",
    labels: list[str] | None = None,
    root: Path | None = None,
) -> dict:
    return verify_submission(
        title,
        body,
        labels if labels is not None else list(SUBMISSION_LABELS),
        issue_number=999,
        fetcher=fetcher,
        root=root or Path("."),
        observed_at=OBSERVED_AT,
    )


DPA_BODY_TEXT = "Data Processing Addendum describing processor and controller obligations"


def test_field_label_constants_match_issue_form_templates():
    for form_kind, template_name in FORM_TEMPLATES.items():
        template = yaml.safe_load((ISSUE_TEMPLATE_DIR / template_name).read_text(encoding="utf-8"))
        fields_by_id = {
            item["id"]: item
            for item in template["body"]
            if isinstance(item, dict) and "id" in item
        }
        for field_id, label in FORM_FIELD_LABELS[form_kind].items():
            assert field_id in fields_by_id, (template_name, field_id)
            assert fields_by_id[field_id]["attributes"]["label"] == label, (template_name, field_id)
        assert template["title"] == TITLE_PREFIXES[form_kind], template_name


def test_form_kind_detection_by_title_and_label_fallback():
    assert detect_form_kind("Source candidate: Acme DPA") == "new_source"
    assert detect_form_kind("Broken source: Acme DPA moved") == "broken_source"
    assert detect_form_kind("Renamed by user", ["submission:vendor-identity"]) == "vendor_identity"
    assert (
        detect_form_kind("Renamed", ["submission:new-source", "submission:machine-readable"])
        == "subprocessor_feed"
    )
    assert detect_form_kind("Unrelated", ["bug"]) is None


def test_canonical_candidate_for_on_domain_consistent_content():
    report = verify(new_source_body(), fetcher=lambda url: html_fetch(url, DPA_BODY_TEXT))
    assert report["verification_result"] == "canonical_candidate"
    assert report["canonical_confidence_candidate"] == "canonical"
    assert report["requires_review"] is False
    assert report["retrieval_method_candidate"] == "html_page"
    assert report["not_advice"] is True


def test_likely_vendor_published_for_on_domain_redirect():
    report = verify(
        new_source_body(belief="Unsure"),
        fetcher=lambda url: html_fetch(
            url, DPA_BODY_TEXT, final_url="https://trust.vendor.example/legal/dpa"
        ),
    )
    assert report["verification_result"] == "likely_vendor_published"
    assert report["canonical_confidence_candidate"] == "redirected_entrypoint"
    assert report["requires_review"] is False


def test_possible_match_for_off_domain_url_without_redirect():
    report = verify(
        new_source_body(source_url="https://docs.otherhost.example/dpa"),
        fetcher=lambda url: html_fetch(url, DPA_BODY_TEXT),
    )
    assert report["verification_result"] == "possible_match"
    assert report["canonical_confidence_candidate"] == "ambiguous"
    assert report["requires_review"] is True


def test_redirected_ambiguous_for_off_domain_redirect():
    report = verify(
        new_source_body(),
        fetcher=lambda url: html_fetch(
            url, DPA_BODY_TEXT, final_url="https://cdn.unrelated.example/dpa"
        ),
    )
    assert report["verification_result"] == "redirected_ambiguous"


def test_source_type_mismatch_on_strong_contradiction():
    report = verify(
        new_source_body(),
        fetcher=lambda url: html_fetch(url, "Quarterly marketing newsletter signup page"),
    )
    assert report["verification_result"] == "source_type_mismatch"
    assert RESULT_LABELS[report["verification_result"]] == "candidate:ambiguous"


def test_unknown_source_type_routes_to_needs_review_not_mismatch():
    report = verify(
        new_source_body(source_type="other_public_source", belief="Unsure"),
        fetcher=lambda url: html_fetch(url, "Some vendor page text"),
    )
    assert report["verification_result"] in {"possible_match", "likely_vendor_published"}
    assert report["verification_result"] != "source_type_mismatch"


def test_gated_or_auth_required_from_http_status():
    report = verify(
        new_source_body(),
        fetcher=lambda url: html_fetch(url, "please sign in to continue", status=401),
    )
    assert report["verification_result"] == "gated_or_auth_required"
    assert RESULT_LABELS[report["verification_result"]] == "candidate:gated"


def test_bot_protected_from_challenge_page():
    report = verify(
        new_source_body(),
        fetcher=lambda url: html_fetch(url, "Checking your browser - cloudflare", status=403),
    )
    assert report["verification_result"] == "bot_protected"
    assert RESULT_LABELS[report["verification_result"]] == "candidate:gated"


def test_fetch_failed_when_unreachable():
    report = verify(new_source_body(), fetcher=failing_fetch)
    assert report["verification_result"] == "fetch_failed"
    assert report["verification_reason"] == "unreachable"


def test_fetch_failed_when_no_verifiable_url():
    report = verify(new_source_body(source_url="not a url"), fetcher=forbidden_fetcher)
    assert report["verification_result"] == "fetch_failed"
    assert report["verification_reason"] == "no_verifiable_url"


def test_unsafe_url_short_circuits_without_fetch():
    report = verify(
        new_source_body(source_url="https://127.0.0.1/internal"),
        fetcher=forbidden_fetcher,
    )
    assert report["verification_result"] == "unsafe_url"
    assert RESULT_LABELS[report["verification_result"]] == "candidate:rejected"


def test_declared_gated_short_circuits_without_fetch():
    report = verify(
        new_source_body(public_access="No - gated or restricted (mark as gated)"),
        fetcher=forbidden_fetcher,
    )
    assert report["verification_result"] == "gated_or_auth_required"
    assert report["verification_reason"] == "declared_gated_by_submitter"


def broken_source_body(*, public_access: str) -> str:
    return "\n".join(
        [
            "### Vendor name",
            "",
            "Example Vendor",
            "",
            "### Vendor domain",
            "",
            "vendor.example",
            "",
            "### Existing source URL or OpenVA source ID",
            "",
            "https://vendor.example/legal/dpa",
            "",
            "### Observed state",
            "",
            "Broken - unreachable or page removed",
            "",
            "### Replacement URL",
            "",
            "_No response_",
            "",
            "### Source type",
            "",
            "dpa",
            "",
            "### Public access confirmed",
            "",
            public_access,
            "",
        ]
    )


def test_broken_source_not_applicable_option_is_fetched_not_gated():
    # Regression: "Not applicable - reporting breakage only" starts with "no"
    # when lowercased; it must NOT be treated as a declared-gated claim.
    seen: list[str] = []

    def fetcher(url: str) -> FetchResult:
        seen.append(url)
        return failing_fetch(url)

    report = verify_submission(
        "Broken source: Example Vendor DPA gone",
        broken_source_body(public_access="Not applicable - reporting breakage only"),
        ["status:needs-triage", "submission:broken-source"],
        issue_number=998,
        fetcher=fetcher,
        root=Path("."),
        observed_at=OBSERVED_AT,
    )
    assert seen == ["https://vendor.example/legal/dpa"]
    assert report["verification_result"] == "fetch_failed"


def test_broken_source_gated_option_still_short_circuits():
    report = verify_submission(
        "Broken source: Example Vendor DPA now gated",
        broken_source_body(public_access="No - gated or restricted (mark as gated)"),
        ["status:needs-triage", "submission:broken-source"],
        issue_number=998,
        fetcher=forbidden_fetcher,
        root=Path("."),
        observed_at=OBSERVED_AT,
    )
    assert report["verification_result"] == "gated_or_auth_required"
    assert report["verification_reason"] == "declared_gated_by_submitter"


def test_redirect_to_blocked_host_is_unsafe_url():
    report = verify(
        new_source_body(),
        fetcher=lambda url: html_fetch(
            url, DPA_BODY_TEXT, final_url="http://127.0.0.1/internal"
        ),
    )
    assert report["verification_result"] == "unsafe_url"
    assert report["verification_reason"] == "redirect_target_failed_url_safety"
    assert RESULT_LABELS[report["verification_result"]] == "candidate:rejected"


def test_duplicate_detection_against_existing_catalog(tmp_path):
    source_dir = tmp_path / "data" / "vendors" / "example-vendor" / "sources"
    source_dir.mkdir(parents=True)
    (source_dir / "example-vendor-dpa.yaml").write_text(
        "vendor_id: example-vendor\n"
        "source_id: example-vendor-dpa\n"
        "source_url: https://vendor.example/legal/dpa\n",
        encoding="utf-8",
    )
    report = verify(
        new_source_body(),
        fetcher=lambda url: html_fetch(url, DPA_BODY_TEXT),
        root=tmp_path,
    )
    assert report["verification_result"] == "duplicate_existing_source"
    assert report["duplicate_match"] == {
        "vendor_id": "example-vendor",
        "source_id": "example-vendor-dpa",
        "source_url": "https://vendor.example/legal/dpa",
    }
    assert report["requires_review"] is False


def test_verification_is_deterministic():
    fetcher = lambda url: html_fetch(url, DPA_BODY_TEXT)  # noqa: E731
    first = verify(new_source_body(), fetcher=fetcher)
    second = verify(new_source_body(), fetcher=fetcher)
    assert first == second


def test_every_result_has_exactly_one_label():
    assert set(RESULT_LABELS) == set(VERIFICATION_RESULTS)
    assert set(RESULT_LABELS.values()) == set(CANDIDATE_LABELS)
    assert NO_REVIEW_RESULTS <= set(VERIFICATION_RESULTS)


def test_report_contains_required_spec_fields():
    report = verify(new_source_body(), fetcher=lambda url: html_fetch(url, DPA_BODY_TEXT))
    for field in (
        "candidate_source_id",
        "vendor_id_or_candidate",
        "submitted_url",
        "final_url",
        "http_status",
        "source_type_candidate",
        "retrieval_method_candidate",
        "canonical_confidence_candidate",
        "duplicate_match",
        "requires_review",
        "verification_result",
        "verification_reason",
        "observed_at",
        "not_advice",
    ):
        assert field in report, field
    assert report["candidate_source_id"] == "submission-issue-999"
    assert report["not_advice"] is True


def test_comment_has_marker_yaml_block_and_no_advisory_vocabulary():
    report = verify(new_source_body(), fetcher=lambda url: html_fetch(url, DPA_BODY_TEXT))
    comment = render_comment(report)
    assert comment.startswith(COMMENT_MARKER)
    assert "```yaml" in comment
    assert "not change catalog data" in comment
    assert not ADVISORY_RE.search(comment)


def test_report_and_comment_never_echo_free_text(tmp_path):
    body = new_source_body() + f"\nextra body text {BODY_SENTINEL}\n"
    report = verify(body, fetcher=lambda url: html_fetch(url, f"dpa processor {BODY_SENTINEL}"))
    comment = render_comment(report)
    serialized = yaml.safe_dump(report)
    for sentinel in (NOTES_SENTINEL, AUTHORITATIVE_SENTINEL, BODY_SENTINEL):
        assert sentinel not in serialized
        assert sentinel not in comment


def test_hold_skips_on_every_path_including_dispatch():
    for labels in (
        ["openva-hold", "submission:new-source", "status:needs-triage"],
        ["openva-hold"],
    ):
        report = verify(new_source_body(), fetcher=forbidden_fetcher, labels=labels)
        assert report["skipped"] is True
        assert report["skip_reason"] == SKIPPED_HOLD
    assert preflight_skip(["openva-hold", "submission:new-source"]) == SKIPPED_HOLD


def test_non_submission_issue_skips():
    report = verify(new_source_body(), fetcher=forbidden_fetcher, labels=["bug"])
    assert report["skipped"] is True
    assert report["skip_reason"] == SKIPPED_NOT_SUBMISSION


def test_skips_write_no_report_or_comment_files(tmp_path):
    for skip_labels in (["openva-hold", "submission:new-source"], ["bug"]):
        out = tmp_path / "-".join(skip_labels).replace(":", "_")
        env = tmp_path / "env.txt"
        report = verify(new_source_body(), fetcher=forbidden_fetcher, labels=skip_labels)
        write_outputs(report, out, github_env=env)
        assert not out.exists() or not list(out.iterdir())
    env_text = (tmp_path / "env.txt").read_text(encoding="utf-8")
    assert "OPENVA_SUBMISSION_SKIP=true" in env_text


def test_write_outputs_emits_report_comment_and_env(tmp_path):
    report = verify(new_source_body(), fetcher=lambda url: html_fetch(url, DPA_BODY_TEXT))
    out = tmp_path / "out"
    env = tmp_path / "env.txt"
    write_outputs(report, out, github_env=env)
    assert (out / REPORT_FILENAME).exists()
    assert (out / COMMENT_FILENAME).exists()
    env_text = env.read_text(encoding="utf-8")
    assert "OPENVA_SUBMISSION_SKIP=false" in env_text
    assert "OPENVA_SUBMISSION_VERIFICATION_RESULT=canonical_candidate" in env_text
    assert "OPENVA_SUBMISSION_VERIFICATION_LABEL=candidate:verified" in env_text


def test_new_vendor_form_verifies_domain_homepage():
    body = "\n".join(
        [
            "### Vendor name",
            "",
            "Example Vendor",
            "",
            "### Vendor domain",
            "",
            "vendor.example",
            "",
            "### Public access confirmed",
            "",
            "Yes - public, no login, paywall, or bot-wall",
            "",
            "### Machine-readable surface",
            "",
            "none",
            "",
        ]
    )
    seen: list[str] = []

    def fetcher(url: str) -> FetchResult:
        seen.append(url)
        return html_fetch(url, "Example Vendor trust and security")

    report = verify_submission(
        "Vendor candidate: Example Vendor",
        body,
        ["status:needs-triage", "submission:new-vendor"],
        issue_number=1000,
        fetcher=fetcher,
        root=Path("."),
        observed_at=OBSERVED_AT,
    )
    assert seen == ["https://vendor.example/"]
    assert report["form_kind"] == "new_vendor"
    assert report["verification_result"] in {"likely_vendor_published", "possible_match"}


def test_machine_readable_surface_drives_retrieval_method():
    body = new_source_body(surface="llms_txt")
    report = verify(body, fetcher=lambda url: html_fetch(url, DPA_BODY_TEXT))
    assert report["retrieval_method_candidate"] == "llms_txt"


def test_workflow_contract_is_verification_only():
    workflow_path = Path(".github/workflows/submitted-source-verification.yml")
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    text = workflow_path.read_text(encoding="utf-8")
    triggers = workflow.get("on") or workflow.get(True) or {}

    assert set(triggers.keys()) == {"issues", "workflow_dispatch"}
    assert triggers["issues"]["types"] == ["opened", "labeled"]
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    assert "gh issue view" in text
    assert "--issue-labels" in text
    assert "OPENVA_SUBMISSION_SKIP != 'true'" in text
    assert COMMENT_MARKER in text
    assert "peter-evans/create-pull-request" not in text
    assert "merge" not in text.lower()
    assert "actions/upload-artifact@v6" in text
