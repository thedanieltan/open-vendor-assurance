"""WP31 submitted source verification.

Deterministically verifies source claims filed through the WP30 submission
issue forms. The verifier classifies a claim and emits a verification report
plus a maintainer-readable comment. It never writes catalog truth, never
creates branches or PRs, never probes declared-gated sources, and never
bypasses bot protection.

Classification is a pure function of (parsed claim, fetch observations):
the fetcher is injected, and ``observed_at`` is supplied by the caller, so
identical inputs always produce identical reports.
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from tools.openva.contribution_intake import (
    existing_source_urls,
    extract_urls,
    host_for,
    host_matches_domain,
    match_vendor,
    normalize_url,
    parse_issue_form,
    slugify,
)
from tools.openva.source_verification import (
    FetchResult,
    classify_status,
    fetch_url,
    normalize_text,
)
from tools.openva.submission_fields import (
    NEW_VENDOR,
    TARGET_URL_FIELDS,
    detect_form_kind,
    parse_submission_fields,
)
from tools.openva.url_safety import validate_url_safety

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
COMMENT_MARKER = "<!-- openva-submitted-source-verification -->"
HOLD_LABEL = "openva-hold"
SUBMISSION_LABEL_PREFIX = "submission:"

SKIPPED_HOLD = "skipped_hold"
SKIPPED_NOT_SUBMISSION = "skipped_not_submission"

REPORT_FILENAME = "verification-report.yaml"
COMMENT_FILENAME = "verification-comment.md"

# WP31-local source-type keyword coverage for all 14 schema source_type
# values. The shared SOURCE_TYPE_KEYWORDS table in source_verification.py
# uses a combined kyc_aml_statement key and does not cover every type;
# submission verification semantics are slightly different, so this table is
# intentionally separate.
SUBMISSION_SOURCE_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dpa": ("data processing", "data processing addendum", "data processing agreement", "dpa", "processor", "controller"),
    "subprocessors_list": ("subprocessor", "sub-processor", "sub-processors", "sub processors", "third party processors", "service providers"),
    "privacy_notice": ("privacy", "personal data", "personal information", "privacy policy", "privacy notice"),
    "trust_center": ("trust center", "trust centre", "trust portal", "security and compliance", "trust"),
    "security_page": ("security", "encryption", "availability", "vulnerability", "incident", "trust"),
    "compliance_page": ("compliance", "certification", "soc", "iso", "audit", "trust"),
    "certification_reference": ("certification", "certificate", "iso", "soc", "attestation", "audit report"),
    "terms_of_service": ("terms of service", "terms of use", "terms and conditions", "agreement", "license"),
    "kyc_statement": ("kyc", "know your customer", "identity verification", "customer due diligence"),
    "aml_statement": ("aml", "anti-money laundering", "sanctions", "financial crime", "money laundering"),
    "ai_terms": ("artificial intelligence", "machine learning", "ai terms", "model", "training data"),
    "government_request_policy": ("government request", "law enforcement", "legal process", "subpoena", "warrant"),
    "transparency_report": ("transparency report", "transparency", "requests received", "disclosure"),
    "status_page": ("status", "uptime", "service status", "incident history", "operational"),
    "other_public_source": (),
}

VERIFICATION_RESULTS = (
    "canonical_candidate",
    "likely_vendor_published",
    "possible_match",
    "duplicate_existing_source",
    "redirected_ambiguous",
    "gated_or_auth_required",
    "bot_protected",
    "source_type_mismatch",
    "unsafe_url",
    "fetch_failed",
)

RESULT_LABELS: dict[str, str] = {
    "canonical_candidate": "candidate:verified",
    "likely_vendor_published": "candidate:verified",
    "possible_match": "candidate:needs-review",
    "duplicate_existing_source": "candidate:duplicate",
    "redirected_ambiguous": "candidate:ambiguous",
    "gated_or_auth_required": "candidate:gated",
    "bot_protected": "candidate:gated",
    "source_type_mismatch": "candidate:ambiguous",
    "unsafe_url": "candidate:rejected",
    "fetch_failed": "candidate:fetch-failed",
}

CANDIDATE_LABELS = (
    "candidate:verified",
    "candidate:needs-review",
    "candidate:duplicate",
    "candidate:gated",
    "candidate:ambiguous",
    "candidate:rejected",
    "candidate:fetch-failed",
)

NO_REVIEW_RESULTS = {"canonical_candidate", "likely_vendor_published", "duplicate_existing_source"}

GATED_STATUSES = {"gated_or_login_required", "forbidden_unknown"}
FETCH_FAILED_STATUSES = {
    "unreachable",
    "not_found",
    "gone",
    "server_error",
    "client_error",
    "rate_limited",
    "soft_not_found",
}

SURFACE_RETRIEVAL_METHODS: dict[str, str] = {
    "rss": "rss_feed",
    "sitemap": "sitemap",
    "llms_txt": "llms_txt",
    "openapi": "json_api",
    "mcp": "mcp_server",
    "api": "json_api",
}


def preflight_skip(issue_labels: list[str]) -> str | None:
    """Authoritative live-label guard, applied on every trigger path.

    A held issue is never verified, commented, or labeled; dispatch cannot
    bypass the hold.
    """
    labels = [str(label).strip() for label in issue_labels]
    if HOLD_LABEL in labels:
        return SKIPPED_HOLD
    if not any(label.startswith(SUBMISSION_LABEL_PREFIX) for label in labels):
        return SKIPPED_NOT_SUBMISSION
    return None


def submission_semantic_match(source_type: str | None, text: str, content_type: str | None) -> dict[str, Any]:
    if content_type and "pdf" in content_type.lower():
        return {"status": "not_evaluated_pdf_sample", "matched_terms": []}
    keywords = SUBMISSION_SOURCE_TYPE_KEYWORDS.get(str(source_type or ""), ())
    if not keywords:
        return {"status": "not_evaluated_unknown_source_type", "matched_terms": []}
    if not text:
        return {"status": "not_evaluated_empty_body", "matched_terms": []}
    matched = [keyword for keyword in keywords if keyword in text]
    if len(matched) >= 2:
        status = "strong"
    elif len(matched) == 1:
        status = "weak"
    else:
        status = "mismatch"
    return {"status": status, "matched_terms": matched}


def infer_retrieval_method(
    content_type: str | None,
    final_url: str | None,
    surface_shorthand: str | None,
) -> str | None:
    shorthand = (surface_shorthand or "").strip().lower()
    url = (final_url or "").lower()
    lowered_type = (content_type or "").lower()
    if shorthand in SURFACE_RETRIEVAL_METHODS:
        if shorthand == "rss" and "atom" in lowered_type:
            return "atom_feed"
        return SURFACE_RETRIEVAL_METHODS[shorthand]
    if content_type is None and not url:
        return None
    if "pdf" in lowered_type:
        return "pdf_document"
    if "json" in lowered_type:
        return "json_api"
    if "atom" in lowered_type:
        return "atom_feed"
    if "rss" in lowered_type or (("xml" in lowered_type) and ("rss" in url or "feed" in url)):
        return "rss_feed"
    if "xml" in lowered_type and "sitemap" in url:
        return "sitemap"
    if url.rstrip("/").endswith("llms.txt"):
        return "llms_txt"
    if "csv" in lowered_type:
        return "csv_download"
    if "html" in lowered_type or "text" in lowered_type:
        return "html_page"
    return "other"


def vendor_domains(fields: dict[str, str], vendor_match: Any | None) -> list[str]:
    domains: list[str] = []
    submitted = (fields.get("vendor_domain") or "").strip().lower()
    submitted = re.sub(r"^https?://", "", submitted).strip("/")
    if submitted:
        domains.append(submitted)
    if vendor_match is not None:
        record = vendor_match.record
        for key in ("official_domains", "previous_domains"):
            for domain in record.get(key) or []:
                value = str(domain).strip().lower()
                if value and value not in domains:
                    domains.append(value)
    return domains


def host_on_domains(url: str, domains: list[str]) -> bool:
    host = host_for(url)
    return bool(host) and any(host_matches_domain(host, domain) for domain in domains)


def select_target_url(form_kind: str, fields: dict[str, str]) -> str | None:
    field = TARGET_URL_FIELDS.get(form_kind)
    if form_kind == NEW_VENDOR or field is None:
        domain = (fields.get("vendor_domain") or "").strip()
        domain = re.sub(r"^https?://", "", domain).strip("/")
        if not domain or " " in domain or "." not in domain:
            return None
        return f"https://{domain}/"
    value = fields.get(field, "")
    urls = extract_urls(value)
    if urls:
        return urls[0]
    if form_kind == "broken_source":
        replacement = extract_urls(fields.get("replacement_url", ""))
        if replacement:
            return replacement[0]
    return None


def declared_gated(fields: dict[str, str]) -> bool:
    # Match only the "No - gated or restricted" option. A bare "no" prefix
    # would also match the broken-source option "Not applicable - reporting
    # breakage only", which must proceed to fetch.
    value = (fields.get("public_access_confirmed") or "").strip().lower()
    return value.startswith("no -")


def find_duplicate(url: str, final_url: str | None, root: Path) -> dict[str, Any] | None:
    existing = existing_source_urls(root)
    for candidate in (url, final_url or ""):
        if not candidate:
            continue
        match = existing.get(normalize_url(candidate))
        if match:
            source = match["source"]
            return {
                "vendor_id": source.get("vendor_id"),
                "source_id": source.get("source_id"),
                "source_url": source.get("source_url"),
            }
    return None


def propose_canonical_confidence(
    *,
    redirected: bool,
    on_vendor_domain: bool,
    belief: str,
    semantic_status: str,
) -> str:
    belief_canonical = belief.strip().lower().startswith("this is the vendor's canonical")
    if not on_vendor_domain:
        return "ambiguous"
    if redirected:
        return "redirected_entrypoint"
    if belief_canonical or semantic_status == "strong":
        return "canonical"
    return "likely_canonical"


def verify_submission(
    issue_title: str,
    issue_body: str,
    issue_labels: list[str],
    *,
    issue_number: int,
    fetcher: Callable[[str], FetchResult] = fetch_url,
    root: Path = ROOT,
    observed_at: str,
) -> dict[str, Any]:
    skip = preflight_skip(issue_labels)
    if skip:
        return {"skipped": True, "skip_reason": skip, "issue_number": issue_number}

    checks: list[dict[str, str]] = []

    def check(name: str, outcome: str, detail: str = "") -> None:
        checks.append({"check": name, "outcome": outcome, "detail": detail})

    form_kind = detect_form_kind(issue_title, issue_labels)
    fields = (
        parse_submission_fields(form_kind, parse_issue_form(issue_body))
        if form_kind
        else {}
    )
    check("form_kind", form_kind or "unrecognized")

    vendor_input = fields.get("openva_vendor_id") or fields.get("vendor_name") or ""
    vendor = match_vendor(vendor_input, root) if vendor_input else None
    if vendor is not None:
        vendor_id_or_candidate = vendor.vendor_id
    else:
        candidate_slug = slugify(fields.get("vendor_name") or fields.get("vendor_domain") or "unknown")
        vendor_id_or_candidate = f"candidate-{candidate_slug}"
    check("vendor_match", "matched" if vendor else "candidate", vendor_id_or_candidate)

    source_type = (fields.get("source_type") or "").strip() or None
    surface_shorthand = (fields.get("machine_readable_surface") or "").strip() or None
    belief = fields.get("canonical_location_belief") or ""

    def report(
        result: str,
        reason: str,
        *,
        submitted_url: str | None,
        final_url: str | None = None,
        http_status: int | None = None,
        content_type: str | None = None,
        retrieval_method: str | None = None,
        canonical_confidence: str | None = None,
        duplicate_match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_source_id": f"submission-issue-{issue_number}",
            "issue_number": issue_number,
            "form_kind": form_kind,
            "vendor_id_or_candidate": vendor_id_or_candidate,
            "submitted_url": submitted_url,
            "final_url": final_url,
            "http_status": http_status,
            "content_type": content_type,
            "source_type_candidate": source_type,
            "retrieval_method_candidate": retrieval_method,
            "canonical_confidence_candidate": canonical_confidence,
            "duplicate_match": duplicate_match,
            "requires_review": result not in NO_REVIEW_RESULTS,
            "verification_result": result,
            "verification_reason": reason,
            "observed_at": observed_at,
            "checks": checks,
            "not_advice": True,
        }

    if form_kind is None:
        check("target_url", "unavailable", "unrecognized submission form")
        return report("fetch_failed", "unrecognized_submission_form", submitted_url=None)

    target_url = select_target_url(form_kind, fields)
    if not target_url:
        check("target_url", "unavailable", "no verifiable URL in submission")
        return report("fetch_failed", "no_verifiable_url", submitted_url=None)
    check("target_url", "selected", target_url)

    safety_failures = validate_url_safety(target_url)
    if safety_failures:
        check("url_safety", "failed", "; ".join(safety_failures))
        return report("unsafe_url", "url_safety_check_failed", submitted_url=target_url)
    check("url_safety", "passed")

    if declared_gated(fields):
        check("declared_gated", "gated", "submitter marked source as gated; not fetched")
        return report(
            "gated_or_auth_required",
            "declared_gated_by_submitter",
            submitted_url=target_url,
        )
    check("declared_gated", "not_declared")

    result = fetcher(target_url)
    check("fetch", "completed" if result.http_status is not None else "failed", result.error or "")

    if result.final_url and result.final_url != target_url:
        redirect_failures = validate_url_safety(result.final_url)
        if redirect_failures:
            check("redirect_target_safety", "failed", "; ".join(redirect_failures))
            return report(
                "unsafe_url",
                "redirect_target_failed_url_safety",
                submitted_url=target_url,
                final_url=result.final_url,
                http_status=result.http_status,
            )
        check("redirect_target_safety", "passed")

    text = normalize_text(result.body_sample, result.content_type)
    semantic = submission_semantic_match(source_type, text, result.content_type)
    check("source_type_consistency", semantic["status"])

    retrieval_method = infer_retrieval_method(result.content_type, result.final_url, surface_shorthand)

    pseudo_source = {"source_url": target_url, "source_type": source_type or ""}
    status = classify_status(pseudo_source, result, semantic)
    check("access_classification", status)

    common = {
        "submitted_url": target_url,
        "final_url": result.final_url,
        "http_status": result.http_status,
        "content_type": result.content_type,
        "retrieval_method": retrieval_method,
    }

    if status in FETCH_FAILED_STATUSES:
        return report("fetch_failed", status, **common)
    if status == "bot_protected":
        return report("bot_protected", status, **common)
    if status in GATED_STATUSES:
        return report("gated_or_auth_required", status, **common)

    duplicate = find_duplicate(target_url, result.final_url, root)
    check("duplicate", "duplicate" if duplicate else "none")
    if duplicate:
        return report(
            "duplicate_existing_source",
            "url_matches_existing_canonical_source",
            duplicate_match=duplicate,
            canonical_confidence="canonical",
            **common,
        )

    domains = vendor_domains(fields, vendor)
    on_domain = host_on_domains(result.final_url or target_url, domains)
    redirected = normalize_url(result.final_url or target_url) != normalize_url(target_url)
    check("domain_comparison", "on_vendor_domain" if on_domain else "off_vendor_domain")

    if semantic["status"] == "mismatch" and text:
        return report(
            "source_type_mismatch",
            "content_contradicts_submitted_source_type",
            canonical_confidence="ambiguous",
            **common,
        )

    if status == "homepage_or_generic_redirect":
        return report("redirected_ambiguous", status, canonical_confidence="ambiguous", **common)

    canonical_confidence = propose_canonical_confidence(
        redirected=redirected,
        on_vendor_domain=on_domain,
        belief=belief,
        semantic_status=semantic["status"],
    )

    if not on_domain:
        if redirected:
            return report(
                "redirected_ambiguous",
                "redirected_off_vendor_domain",
                canonical_confidence=canonical_confidence,
                **common,
            )
        return report(
            "possible_match",
            "url_not_on_claimed_vendor_domain",
            canonical_confidence=canonical_confidence,
            **common,
        )

    if status == "suspect_inferred_url" or semantic["status"] in {"weak", "not_evaluated_empty_body"}:
        return report(
            "possible_match",
            f"semantic_match_{semantic['status']}",
            canonical_confidence=canonical_confidence,
            **common,
        )

    if canonical_confidence == "canonical" and not redirected:
        return report(
            "canonical_candidate",
            "on_vendor_domain_with_consistent_content",
            canonical_confidence=canonical_confidence,
            **common,
        )
    return report(
        "likely_vendor_published",
        "on_vendor_domain",
        canonical_confidence=canonical_confidence,
        **common,
    )


def render_comment(report: dict[str, Any]) -> str:
    label = RESULT_LABELS[report["verification_result"]]
    lines = [
        COMMENT_MARKER,
        "## Submitted source verification",
        "",
        "Automated verification of a submitted source claim. This comment "
        "records observed facts only. It does not change catalog data, does "
        "not approve or score any vendor, and is not a legal or compliance "
        "conclusion.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Verification result | `{report['verification_result']}` |",
        f"| Triage label | `{label}` |",
        f"| Submitted URL | {report.get('submitted_url') or 'n/a'} |",
        f"| Final URL | {report.get('final_url') or 'n/a'} |",
        f"| HTTP status | {report.get('http_status') if report.get('http_status') is not None else 'n/a'} |",
        f"| Source type (claimed) | {report.get('source_type_candidate') or 'n/a'} |",
        f"| Retrieval method (candidate) | {report.get('retrieval_method_candidate') or 'n/a'} |",
        f"| Canonical confidence (candidate) | {report.get('canonical_confidence_candidate') or 'n/a'} |",
        f"| Duplicate of | {format_duplicate(report.get('duplicate_match'))} |",
        f"| Requires review | {str(report['requires_review']).lower()} |",
        f"| Observed at | {report['observed_at']} |",
        "",
        "<details><summary>Machine-readable verification report</summary>",
        "",
        "```yaml",
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True).rstrip(),
        "```",
        "",
        "</details>",
        "",
        "This submission remains a claim until a maintainer reviews it. "
        "Catalog data changes only through reviewed pull requests.",
    ]
    return "\n".join(lines) + "\n"


def format_duplicate(duplicate: dict[str, Any] | None) -> str:
    if not duplicate:
        return "none"
    return f"`{duplicate.get('vendor_id')}/{duplicate.get('source_id')}`"


def write_github_env(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def write_outputs(report: dict[str, Any], output_dir: Path, *, github_env: Path | None = None) -> None:
    if report.get("skipped"):
        # Skips must produce no report and no comment artifacts.
        if github_env:
            write_github_env(
                github_env,
                {
                    "OPENVA_SUBMISSION_SKIP": "true",
                    "OPENVA_SUBMISSION_SKIP_REASON": str(report.get("skip_reason")),
                },
            )
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / REPORT_FILENAME).write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (output_dir / COMMENT_FILENAME).write_text(render_comment(report), encoding="utf-8")
    if github_env:
        write_github_env(
            github_env,
            {
                "OPENVA_SUBMISSION_SKIP": "false",
                "OPENVA_SUBMISSION_VERIFICATION_RESULT": report["verification_result"],
                "OPENVA_SUBMISSION_VERIFICATION_LABEL": RESULT_LABELS[report["verification_result"]],
            },
        )


def disabled_fetcher(url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        http_status=None,
        content_type=None,
        content_length=None,
        etag=None,
        last_modified=None,
        body_sample=b"",
        error="network_check_disabled",
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-submission-verify")
    subparsers = parser.add_subparsers(dest="command", required=True)
    issue = subparsers.add_parser("issue", help="Verify one submission issue")
    issue.add_argument("--issue-body", type=Path, required=True)
    issue.add_argument("--issue-title", required=True)
    issue.add_argument("--issue-labels", default="", help="Comma-separated live issue labels")
    issue.add_argument("--issue-number", type=int, required=True)
    issue.add_argument("--output-dir", type=Path, required=True)
    issue.add_argument("--network-check", action="store_true")
    issue.add_argument("--github-env", type=Path, default=None)
    args = parser.parse_args()

    labels = [label.strip() for label in args.issue_labels.split(",") if label.strip()]
    report = verify_submission(
        args.issue_title,
        args.issue_body.read_text(encoding="utf-8"),
        labels,
        issue_number=args.issue_number,
        fetcher=fetch_url if args.network_check else disabled_fetcher,
        observed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    write_outputs(report, args.output_dir, github_env=args.github_env)
    if report.get("skipped"):
        print(f"skipped: {report.get('skip_reason')}")
    else:
        print(f"verification_result: {report['verification_result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
