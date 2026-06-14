"""WP40A human-submission bridge.

Turns a verified human new-vendor submission into one normalised candidate
record on the *same* lifecycle the autonomous lanes use. There is no second
catalog-mutation architecture for human submissions: the bridge produces a
``candidate_record`` (origin ``human_submission``) whose eligibility is decided
by the shared evaluator, then the existing machine-provisional and quorum
machinery materialises and promotes it.

Unlike the homepage-only new-vendor probe, the bridge verifies *every* supplied
assurance URL individually:

1. the submitted official domain is verified as the identity anchor;
2. every URL in the "Known public assurance source URLs" field is parsed and
   url-safety validated before any fetch;
3. declared-gated submissions are recorded as access-state facts and never
   fetched;
4. each source records HTTP status, redirect chain, final URL, source-type and
   retrieval-method classification, duplicate detection, and a per-source
   evidence digest;
5. the minimum useful source-role threshold decides eligibility.

An invalid source is rejected or deferred individually; one bad source does not
invalidate the vendor when enough valid sources remain.

The verifier is pure: the fetcher is injected and ``observed_at`` is supplied,
so identical inputs always produce byte-identical candidate records. It never
authenticates, never bypasses bot protection, and never fetches a declared-gated
URL.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from tools.openva import candidate_record as cr
from tools.openva.contribution_intake import (
    extract_urls,
    match_vendor,
    normalize_url,
    parse_issue_form,
    slugify,
    vendor_records,
)
from tools.openva.indexes import ROOT
from tools.openva.source_verification import FetchResult, classify_status, fetch_url, normalize_text
from tools.openva.submission_fields import NEW_VENDOR, detect_form_kind, parse_submission_fields
from tools.openva.submission_verify import (
    FETCH_FAILED_STATUSES,
    GATED_STATUSES,
    SUBMISSION_SOURCE_TYPE_KEYWORDS,
    declared_gated,
    find_duplicate,
    host_on_domains,
    infer_retrieval_method,
    preflight_skip,
    submission_semantic_match,
    vendor_domains,
)
from tools.openva.url_safety import validate_url_safety

DISCOVERY_COMPONENT = "submission-bridge"


def match_vendor_by_domain(domain: str, root: Path):
    """Find an existing vendor whose official/previous domains include ``domain``.

    Name matching alone misses a rename or a domain-only collision, so the
    bridge also checks domains before treating a submission as a new vendor.
    """
    needle = (domain or "").strip().lower().rstrip(".")
    if not needle:
        return None
    for vendor in vendor_records(root):
        for key in ("official_domains", "previous_domains"):
            for value in vendor.record.get(key) or []:
                if str(value).strip().lower().rstrip(".") == needle:
                    return vendor
    return None

# Per-source access_state derived from the shared status classifier.
_FETCH_FAILED = set(FETCH_FAILED_STATUSES)
_GATED = set(GATED_STATUSES)


def _per_source_evidence_digest(
    *, candidate_url: str, final_url: str | None, http_status: int | None, content_type: str | None
) -> str:
    return cr.compute_evidence_digest(
        [
            {
                "candidate_url": candidate_url,
                "final_url": final_url,
                "http_status": http_status,
                "content_type": content_type,
            }
        ]
    )


def verify_source_url(
    url: str,
    *,
    declared_source_type: str | None,
    vendor_domain_list: list[str],
    fetcher: Callable[[str], FetchResult],
    root: Path,
    observed_at: str,
    declared_gated_submission: bool,
    surface_shorthand: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify one supplied assurance URL.

    Returns ``(source_candidate, evidence_record)``. The source_candidate
    carries the access state, classification, duplicate match, and the
    evaluator-only signals (``source_type_conflict``, ``authority_proven``)
    that ``evaluate_eligibility`` consumes and the committed builder strips.
    """
    source_type = (declared_source_type or "other_public_source").strip() or "other_public_source"

    def assemble(
        *,
        access_state: str,
        source_role: str,
        final_url: str | None = None,
        http_status: int | None = None,
        content_type: str | None = None,
        retrieval_method: str | None = None,
        on_vendor_domain: bool | None = None,
        duplicate_of: str | None = None,
        verification_result: str,
        reasons: list[str],
        source_type_conflict: bool = False,
        authority_proven: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        redirect_chain: list[str] = []
        if final_url and normalize_url(final_url) != normalize_url(url):
            redirect_chain = [url, final_url]
        digest = _per_source_evidence_digest(
            candidate_url=url, final_url=final_url, http_status=http_status, content_type=content_type
        )
        source_candidate = {
            "candidate_url": url,
            "final_url": final_url,
            "redirect_chain": redirect_chain,
            "http_status": http_status,
            "content_type": content_type,
            "source_type_candidate": source_type,
            "retrieval_method_candidate": retrieval_method,
            "access_state": access_state,
            "source_role": source_role,
            "on_vendor_domain": on_vendor_domain,
            "duplicate_of": duplicate_of,
            "evidence_digest": digest,
            "verification_result": verification_result,
            "reasons": reasons,
            # evaluator-only signals (stripped before commit)
            "source_type_conflict": source_type_conflict,
            "authority_proven": authority_proven,
        }
        evidence_record = {
            "candidate_url": url,
            "final_url": final_url,
            "http_status": http_status,
            "content_type": content_type,
            "redirect_chain": redirect_chain,
            "source_type_candidate": source_type,
            "retrieval_method_candidate": retrieval_method,
            "verification_result": verification_result,
            "evidence_digest": digest,
            "observed_at": observed_at,
        }
        return source_candidate, evidence_record

    # 1. url safety before any fetch
    if validate_url_safety(url):
        return assemble(
            access_state="unsafe_url",
            source_role="rejected",
            verification_result="unsafe_url",
            reasons=["url_safety_check_failed"],
        )

    # 2. declared-gated submissions are never fetched
    if declared_gated_submission:
        return assemble(
            access_state="declared_gated",
            source_role="rejected",
            verification_result="declared_gated",
            reasons=["declared_gated_by_submitter_not_fetched"],
        )

    result = fetcher(url)

    # redirect target safety
    if result.final_url and normalize_url(result.final_url) != normalize_url(url):
        if validate_url_safety(result.final_url):
            return assemble(
                access_state="unsafe_url",
                source_role="rejected",
                final_url=result.final_url,
                http_status=result.http_status,
                verification_result="unsafe_url",
                reasons=["redirect_target_failed_url_safety"],
            )

    text = normalize_text(result.body_sample, result.content_type)
    semantic = submission_semantic_match(source_type, text, result.content_type)
    retrieval_method = infer_retrieval_method(result.content_type, result.final_url, surface_shorthand)
    status = classify_status({"source_url": url, "source_type": source_type}, result, semantic)
    final_url = result.final_url
    http_status = result.http_status
    content_type = result.content_type
    on_domain = host_on_domains(final_url or url, vendor_domain_list)

    common = dict(
        final_url=final_url,
        http_status=http_status,
        content_type=content_type,
        retrieval_method=retrieval_method,
        on_vendor_domain=on_domain,
    )

    if status in _FETCH_FAILED:
        return assemble(access_state="fetch_failed", source_role="rejected",
                        verification_result=status, reasons=[status], **common)
    if status == "bot_protected":
        return assemble(access_state="bot_protected", source_role="rejected",
                        verification_result="bot_protected", reasons=["bot_protected_not_bypassed"], **common)
    if status in _GATED:
        return assemble(access_state="gated_or_auth_required", source_role="rejected",
                        verification_result=status, reasons=[status], **common)

    duplicate = find_duplicate(url, final_url, root)
    if duplicate:
        return assemble(
            access_state="public_reachable",
            source_role="rejected",
            duplicate_of=f"{duplicate.get('vendor_id')}/{duplicate.get('source_id')}",
            verification_result="duplicate_existing_source",
            reasons=["url_matches_existing_canonical_source"],
            **common,
        )

    # content contradicts the declared source type
    if semantic["status"] == "mismatch" and text:
        return assemble(
            access_state="public_reachable",
            source_role="rejected",
            verification_result="source_type_mismatch",
            reasons=["content_contradicts_submitted_source_type"],
            source_type_conflict=True,
            **common,
        )

    if status == "homepage_or_generic_redirect":
        return assemble(
            access_state="public_reachable",
            source_role="rejected",
            verification_result="redirected_ambiguous",
            reasons=["resolves_to_homepage_or_generic_page"],
            **common,
        )

    # public and reachable; classify role and authority
    strong = semantic["status"] == "strong"
    role = "primary_assurance" if (on_domain and strong) else "supporting_assurance"
    if not on_domain:
        role = "supporting_assurance"
    verification_result = "canonical_candidate" if (on_domain and strong) else "likely_vendor_published"
    return assemble(
        access_state="public_reachable",
        source_role=role,
        verification_result=verification_result,
        reasons=[f"semantic_{semantic['status']}"],
        authority_proven=on_domain,
        **common,
    )


def _strip_evaluator_keys(source_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for source in source_candidates:
        cleaned.append({k: v for k, v in source.items() if k not in {"source_type_conflict", "authority_proven"}})
    return cleaned


def build_new_vendor_candidate(
    issue_title: str,
    issue_body: str,
    issue_labels: list[str],
    *,
    issue_number: int,
    fetcher: Callable[[str], FetchResult] = fetch_url,
    root: Path = ROOT,
    observed_at: str,
) -> dict[str, Any]:
    """Bridge a verified human new-vendor submission into a candidate record.

    Returns either a skip marker (held / non-submission / wrong form) or a
    schema-valid unified candidate record with its eligibility decided.
    """
    skip = preflight_skip(issue_labels)
    if skip:
        return {"skipped": True, "skip_reason": skip, "issue_number": issue_number}

    form_kind = detect_form_kind(issue_title, issue_labels)
    if form_kind != NEW_VENDOR:
        return {"skipped": True, "skip_reason": "skipped_not_new_vendor", "issue_number": issue_number}

    fields = parse_submission_fields(form_kind, parse_issue_form(issue_body))
    vendor_name = (fields.get("vendor_name") or "").strip()
    raw_domain = (fields.get("vendor_domain") or "").strip()
    official_domain = re.sub(r"^https?://", "", raw_domain).strip("/").lower()

    vendor_id_candidate = slugify(vendor_name or official_domain or "unknown") or "unknown"

    # identity collision / duplicate detection against the live catalog, by
    # name and by official/previous domain.
    existing = (
        match_vendor(vendor_name, root)
        or match_vendor(official_domain, root)
        or match_vendor_by_domain(official_domain, root)
    )
    matches_existing = existing.vendor_id if existing is not None else None

    identity = {
        "vendor_id_candidate": vendor_id_candidate,
        "vendor_name": vendor_name or None,
        "official_domain": official_domain or "unknown.invalid",
        "legal_name": (fields.get("vendor_legal_name") or "").strip() or None,
        "headquarters_country": (fields.get("headquarters_country") or "").strip() or None,
        "matches_existing_vendor_id": matches_existing,
    }
    # The official domain is the identity anchor: it must be a safe public host.
    domain_url = f"https://{official_domain}/" if official_domain and "." in official_domain else ""
    official_domain_unsafe = not domain_url or bool(validate_url_safety(domain_url))

    domains = vendor_domains(fields, existing)
    surface_shorthand = (fields.get("machine_readable_surface") or "").strip() or None
    gated = declared_gated(fields)

    source_candidates: list[dict[str, Any]] = []
    evidence_references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in extract_urls(fields.get("known_public_sources", "")):
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        source_candidate, evidence = verify_source_url(
            url,
            declared_source_type=None,
            vendor_domain_list=domains or ([official_domain] if official_domain else []),
            fetcher=fetcher,
            root=root,
            observed_at=observed_at,
            declared_gated_submission=gated,
            surface_shorthand=surface_shorthand,
        )
        source_candidates.append(source_candidate)
        evidence_references.append(evidence)

    state, reasons = cr.evaluate_eligibility(
        {**identity, "official_domain_unsafe": official_domain_unsafe},
        source_candidates,
        is_new_vendor=True,
        identity_collision=False,
    )

    record = cr.build_candidate(
        candidate_origin="human_submission",
        origin_reference=f"issue-{issue_number}",
        vendor_identity_candidate=identity,
        source_candidates=_strip_evaluator_keys(source_candidates),
        evidence_references=evidence_references,
        discovery_component=DISCOVERY_COMPONENT,
        created_at=observed_at,
        eligibility_state=state,
        decision_reasons=reasons,
    )
    return record


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-submission-bridge")
    parser.add_argument("--issue-body", type=Path, required=True)
    parser.add_argument("--issue-title", required=True)
    parser.add_argument("--issue-labels", default="")
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--network-check", action="store_true")
    args = parser.parse_args(argv)

    labels = [label.strip() for label in args.issue_labels.split(",") if label.strip()]
    record = build_new_vendor_candidate(
        args.issue_title,
        args.issue_body.read_text(encoding="utf-8"),
        labels,
        issue_number=args.issue_number,
        fetcher=fetch_url if args.network_check else disabled_fetcher,
        observed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if record.get("skipped"):
        print(f"skipped: {record.get('skip_reason')}")
    else:
        print(f"candidate {record['candidate_id']} -> {record['eligibility_state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
