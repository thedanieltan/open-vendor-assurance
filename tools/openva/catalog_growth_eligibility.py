from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from tools.openva.advisory_wording import prohibited_terms_in_text
from tools.openva.automerge_lanes import load_policy
from tools.openva.source_discovery import DEFAULT_SOURCE_TYPES
from tools.openva.source_verification import ROOT, display_path
from tools.openva.strict_growth_redirects import (
    REDIRECT_CANONICALIZED,
    REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED,
    REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED,
    REDIRECT_SEMANTIC_MISMATCH,
    materialize_redirect_for_strict_growth,
    redirect_decision,
)

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "catalog_growth_eligibility_report"
STRICT_PROMOTE_READY = "strict_promote_ready"
REVIEW_REQUIRED = "review_required"
REJECT_EXISTING_VENDOR = "reject_existing_vendor"
REJECT_DUPLICATE = "reject_duplicate"
REJECT_NO_PUBLIC_SOURCE = "reject_no_public_source"
REJECT_ACCESS_AMBIGUOUS = "reject_access_ambiguous"
REJECT_WEAK_SEMANTIC_MATCH = "reject_weak_semantic_match"
REJECT_SOURCE_HEALTH_FAILURE = "reject_source_health_failure"
REJECT_IDENTITY_UNCLEAR = "reject_identity_unclear"
STRICT_SOURCE_TYPES = set(DEFAULT_SOURCE_TYPES)
ACCESS_AMBIGUOUS = {"bot_protected", "forbidden_unknown", "gated_or_login_required", "rate_limited", "unreachable"}
HEALTH_FAILURE = {"not_found", "gone", "server_error", "client_error", "homepage_or_generic_redirect", "possible_mismatch", "suspect_inferred_url", "soft_not_found", "soft_404_detected"}
SOURCE_PREFLIGHT_RISK = ACCESS_AMBIGUOUS | HEALTH_FAILURE
CSV_FIELDS = ["candidate_vendor_id", "display_name_candidate", "official_domain_candidate", "coverage_lane", "cohort_id", "classification", "reason_codes", "source_candidate_count", "strict_source_count", "promotable_now"]
DEFAULT_SOURCE_TYPE_PRIORITY = ["dpa", "privacy_notice", "subprocessors_list", "security_page"]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def normalize_domain(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "://" in raw:
        raw = urlparse(raw).netloc
    return raw.split("/", 1)[0].removeprefix("www.")


def normalize_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def current_vendor_identity(root: Path = ROOT) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    domains: set[str] = set()
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        ids.add(str(vendor.get("vendor_id") or path.parent.name))
        # WP36: fold in previous_domains so a renamed vendor's old domain still
        # counts as a collision against a new candidate.
        for key in ("official_domains", "public_entrypoints", "previous_domains"):
            for value in vendor.get(key, []) or []:
                if normalize_domain(value):
                    domains.add(normalize_domain(value))
    return ids, domains


def known_vendor_names(root: Path = ROOT) -> set[str]:
    """Normalized display names and aliases, for WP36 candidate name-collision
    checks (catches renames/prior brands a vendor_id/domain check would miss)."""
    names: set[str] = set()
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        if normalize_name(vendor.get("display_name")):
            names.add(normalize_name(vendor.get("display_name")))
        for alias in vendor.get("display_aliases", []) or []:
            if normalize_name(alias):
                names.add(normalize_name(alias))
    return names


def duplicate_values(rows: list[dict[str, Any]], field: str, normalizer=str) -> set[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = normalizer(row.get(field, ""))
        if value:
            counts[value] += 1
    return {value for value, count in counts.items() if count > 1}


def sources_by_vendor(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vendor in report.get("vendors", []) or []:
        vendor_id = str(vendor.get("vendor_id") or "")
        for candidate in vendor.get("candidates", []) or []:
            if vendor_id and isinstance(candidate, dict):
                result[vendor_id].append(candidate)
    return dict(result)


def observation_statuses(report: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for vendor in report.get("vendors", []) or []:
        vendor_id = str(vendor.get("vendor_id") or "")
        for observation in vendor.get("observations", []) or []:
            status = str(observation.get("semantic_status") or "")
            if vendor_id and status:
                result[vendor_id].add(status)
    return dict(result)


def identity_reasons(row: dict[str, Any], dup_ids: set[str], dup_domains: set[str], known_ids: set[str], known_domains: set[str]) -> list[str]:
    reasons: list[str] = []
    vendor_id = str(row.get("candidate_vendor_id") or "").strip()
    domain = normalize_domain(row.get("official_domain_candidate"))
    if not vendor_id:
        reasons.append("candidate_vendor_id_missing")
    if not str(row.get("display_name_candidate") or "").strip():
        reasons.append("display_name_candidate_missing")
    if not domain:
        reasons.append("official_domain_candidate_missing")
    if row.get("requires_review") is not True:
        reasons.append("requires_review_not_true")
    if row.get("writes_canonical_vendors") is not False:
        reasons.append("writes_canonical_vendors_not_false")
    if row.get("non_advisory") is not True:
        reasons.append("non_advisory_not_true")
    if vendor_id in dup_ids:
        reasons.append("duplicate_candidate_vendor_id")
    if domain in dup_domains:
        reasons.append("duplicate_candidate_domain")
    if vendor_id in known_ids or domain in known_domains:
        reasons.append("candidate_already_in_catalog")
    return reasons


def source_reasons(vendor: dict[str, Any], source: dict[str, Any]) -> list[str]:
    evidence = source.get("evidence", {}) or {}
    reasons: list[str] = []
    verification_status = str(evidence.get("verification_status") or source.get("verification_status") or "")
    if verification_status in SOURCE_PREFLIGHT_RISK:
        reasons.append(f"source_preflight_risk:{verification_status}")
    if evidence.get("soft_404_detected") is True or source.get("soft_404_detected") is True:
        reasons.append("source_preflight_risk:soft_404_detected")
    if source.get("source_type_candidate") not in STRICT_SOURCE_TYPES:
        reasons.append("source_type_not_supported")
    if source.get("confidence") != "likely":
        reasons.append("confidence_not_likely")
    if evidence.get("http_status") != 200:
        reasons.append("http_status_not_200")
    if not evidence.get("matched_terms"):
        reasons.append("matched_terms_missing")
    if not evidence.get("final_url"):
        reasons.append("final_url_missing")
    redirect = redirect_decision(vendor, source)
    if redirect["reason"] in {
        REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED,
        REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED,
        REDIRECT_SEMANTIC_MISMATCH,
    }:
        reasons.append(str(redirect["reason"]))
    if source.get("requires_review") is not True:
        reasons.append("requires_review_not_true")
    if source.get("not_advice") is not True:
        reasons.append("not_advice_not_true")
    for field in (source.get("title"), source.get("description"), evidence.get("page_title")):
        for term in prohibited_terms_in_text(field):
            reasons.append(f"strict_growth_advisory_wording_detected:{term}")
    return reasons


def source_rejection(source: dict[str, Any], reasons: list[str], classification: str) -> dict[str, Any]:
    preflight_reasons = sorted(reason for reason in reasons if reason.startswith("source_preflight_risk:"))
    return {
        "candidate_source_id": source.get("candidate_source_id"),
        "vendor_id": source.get("vendor_id"),
        "source_type_candidate": source.get("source_type_candidate"),
        "candidate_url": source.get("candidate_url"),
        "classification": classification,
        "reason_codes": preflight_reasons or sorted(reasons),
    }


def strict_action(vendor: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    materialized_source, redirect = materialize_redirect_for_strict_growth(vendor, source)
    reason_codes = [REDIRECT_CANONICALIZED] if redirect["reason"] == REDIRECT_CANONICALIZED else []
    return {
        "action": "strict_catalog_growth_promotion_candidate",
        "vendor": {key: vendor.get(key) for key in ["candidate_vendor_id", "display_name_candidate", "official_domain_candidate", "coverage_lane", "cohort_id", "vendor_category_candidates", "headquarters_country_candidate"]},
        "source": {key: materialized_source.get(key) for key in ["candidate_source_id", "vendor_id", "source_type_candidate", "candidate_url", "confidence", "evidence"]},
        "redirect": {
            "candidate_url": redirect["candidate_url"],
            "final_url": redirect["final_url"],
            "redirect_status": redirect["redirect_status"],
            "decision": redirect["decision"],
            "reason": redirect["reason"],
        },
        "reason_codes": reason_codes,
        "posture": {"network_fetch_performed": False, "writes_repository_state": False, "writes_canonical_sources": False, "strict_machine_candidate": True, "non_advisory": True},
    }


def classify(vendor: dict[str, Any], sources: list[dict[str, Any]], statuses: set[str], id_reasons: list[str]) -> tuple[str, list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    if "candidate_already_in_catalog" in id_reasons:
        return REJECT_EXISTING_VENDOR, id_reasons, [], []
    if any(reason.startswith("duplicate_candidate") for reason in id_reasons):
        return REJECT_DUPLICATE, id_reasons, [], []
    if id_reasons:
        return REJECT_IDENTITY_UNCLEAR, id_reasons, [], []
    if statuses & ACCESS_AMBIGUOUS:
        return REJECT_ACCESS_AMBIGUOUS, sorted(statuses & ACCESS_AMBIGUOUS), [], []
    if statuses & HEALTH_FAILURE:
        return REJECT_SOURCE_HEALTH_FAILURE, sorted(statuses & HEALTH_FAILURE), [], []
    if not sources:
        return REJECT_NO_PUBLIC_SOURCE, ["no_source_candidates_for_vendor"], [], []
    source_reason_rows = [(source, source_reasons(vendor, source)) for source in sources]
    strict_sources = [source for source, reasons in source_reason_rows if not reasons]
    source_health_rejections = [
        source_rejection(source, reasons, REJECT_SOURCE_HEALTH_FAILURE)
        for source, reasons in source_reason_rows
        if any(reason.startswith("source_preflight_risk:") for reason in reasons)
    ]
    if strict_sources:
        extra_reasons = sorted(
            {
                reason
                for _source, reasons in source_reason_rows
                for reason in reasons
                if reason.startswith("strict_growth_") or reason.startswith("redirect_")
            }
        )
        return STRICT_PROMOTE_READY, ["strict_source_candidate_evidence_present", *extra_reasons], strict_sources, source_health_rejections
    reasons = sorted({reason for _source, source_reasons_ in source_reason_rows for reason in source_reasons_})
    if any(reason.startswith("source_preflight_risk:") for reason in reasons):
        return REJECT_SOURCE_HEALTH_FAILURE, reasons, [], source_health_rejections
    if {"http_status_not_200", "final_url_missing"} & set(reasons):
        return REJECT_SOURCE_HEALTH_FAILURE, reasons, [], []
    if {"confidence_not_likely", "matched_terms_missing"} & set(reasons):
        return REJECT_WEAK_SEMANTIC_MATCH, reasons, [], []
    return REVIEW_REQUIRED, reasons or ["source_candidate_requires_review"], [], []


def source_priority(policy: dict[str, Any]) -> list[str]:
    configured = policy.get("strict_growth", {}).get("source_type_priority", DEFAULT_SOURCE_TYPE_PRIORITY)
    priority = [str(source_type) for source_type in configured if str(source_type)]
    for source_type in DEFAULT_SOURCE_TYPE_PRIORITY:
        if source_type not in priority:
            priority.append(source_type)
    return priority


def sort_strict_sources(sources: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    priority_index = {source_type: index for index, source_type in enumerate(source_priority(policy))}
    fallback = len(priority_index)
    return sorted(
        sources,
        key=lambda source: (
            priority_index.get(str(source.get("source_type_candidate") or ""), fallback),
            str(source.get("source_type_candidate") or ""),
            str(source.get("candidate_source_id") or ""),
            str(source.get("candidate_url") or ""),
        ),
    )


def cap_strict_sources(
    strict_sources: list[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    max_sources = int(policy.get("strict_growth", {}).get("max_sources_per_new_vendor", 2))
    ordered = sort_strict_sources(strict_sources, policy)
    selected = ordered[:max_sources]
    deferred = ordered[max_sources:]
    reasons = ["strict_growth_vendor_source_cap_exceeded"] if deferred else []
    deferred_rows = [
        {
            "candidate_source_id": source.get("candidate_source_id"),
            "source_type_candidate": source.get("source_type_candidate"),
            "candidate_url": source.get("candidate_url"),
            "reason_codes": ["strict_growth_vendor_source_cap_exceeded"],
        }
        for source in deferred
    ]
    return selected, deferred_rows, reasons


def build_catalog_growth_eligibility(
    vendor_report: dict[str, Any],
    source_report: dict[str, Any],
    root: Path = ROOT,
    generated_at: str | None = None,
    head_sha: str | None = None,
    base_sha: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if vendor_report.get("report_type") != "vendor_candidate_discovery_report":
        raise ValueError("expected vendor_candidate_discovery_report")
    if source_report.get("report_type") != "source_discovery_report":
        raise ValueError("expected source_discovery_report")
    candidates = [row for row in vendor_report.get("vendor_candidates", []) or [] if isinstance(row, dict)]
    dup_ids = duplicate_values(candidates, "candidate_vendor_id", lambda value: str(value or ""))
    dup_domains = duplicate_values(candidates, "official_domain_candidate", normalize_domain)
    known_ids, known_domains = current_vendor_identity(root)
    policy = policy or load_policy()
    source_map = sources_by_vendor(source_report)
    status_map = observation_statuses(source_report)
    items: list[dict[str, Any]] = []
    strict_promotions: list[dict[str, Any]] = []
    for vendor in candidates:
        vendor_id = str(vendor.get("candidate_vendor_id") or "")
        vendor_sources = source_map.get(vendor_id, [])
        classification, reasons, strict_sources, source_health_rejections = classify(vendor, vendor_sources, status_map.get(vendor_id, set()), identity_reasons(vendor, dup_ids, dup_domains, known_ids, known_domains))
        deferred_strict_sources: list[dict[str, Any]] = []
        if classification == STRICT_PROMOTE_READY:
            strict_sources, deferred_strict_sources, cap_reasons = cap_strict_sources(strict_sources, policy)
            reasons = [*reasons, *[reason for reason in cap_reasons if reason not in reasons]]
        strict_promotions.extend(strict_action(vendor, source) for source in strict_sources)
        item = {"candidate_vendor_id": vendor_id, "display_name_candidate": vendor.get("display_name_candidate"), "official_domain_candidate": vendor.get("official_domain_candidate"), "coverage_lane": vendor.get("coverage_lane"), "cohort_id": vendor.get("cohort_id"), "classification": classification, "reason_codes": reasons, "source_candidate_count": len(vendor_sources), "strict_source_count": len(strict_sources), "promotable_now": classification == STRICT_PROMOTE_READY}
        if deferred_strict_sources:
            item["deferred_strict_sources"] = deferred_strict_sources
        if source_health_rejections:
            item["source_health_rejections"] = source_health_rejections
        items.append(item)
    counts = Counter(item["classification"] for item in items)
    redirect_counts = Counter(
        str(action.get("redirect", {}).get("reason") or "not_redirected")
        for action in strict_promotions
        if action.get("redirect", {}).get("redirect_status") in {"canonicalized", "cross_authority_review_required", "unresolved"}
    )
    rejected_redirect_reasons = Counter(
        reason
        for item in items
        for reason in item.get("reason_codes", [])
        if str(reason).startswith("redirect_")
    )
    report = {"schema_version": SCHEMA_VERSION, "generated_at": generated_at or now_iso(), "report_type": REPORT_TYPE, "posture": {"network_fetch_performed": False, "writes_repository_state": False, "writes_canonical_vendors": False, "writes_canonical_sources": False, "opens_pull_requests": False, "non_advisory": True}, "summary": {"candidate_count": len(items), "strict_promote_ready_count": counts.get(STRICT_PROMOTE_READY, 0), "review_required_count": counts.get(REVIEW_REQUIRED, 0), "rejected_or_deferred_count": len(items) - counts.get(STRICT_PROMOTE_READY, 0) - counts.get(REVIEW_REQUIRED, 0), "classification_counts": dict(sorted(counts.items())), "strict_promotion_action_count": len(strict_promotions), "redirect_count": sum(redirect_counts.values()) + sum(rejected_redirect_reasons.values()), "redirect_canonicalized_count": redirect_counts.get(REDIRECT_CANONICALIZED, 0), "redirect_deferred_count": sum(rejected_redirect_reasons.values()), "cross_authority_redirect_count": rejected_redirect_reasons.get(REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED, 0), "generic_redirect_rejected_count": rejected_redirect_reasons.get(REDIRECT_GENERIC_OR_HOMEPAGE_REJECTED, 0), "unresolved_redirect_count": rejected_redirect_reasons.get(REDIRECT_CROSS_AUTHORITY_REVIEW_REQUIRED, 0)}, "items": sorted(items, key=lambda item: (item["classification"], item["candidate_vendor_id"])), "strict_promotions": strict_promotions}
    if head_sha:
        report["head_sha"] = head_sha
    if base_sha:
        report["base_sha"] = base_sha
    return report


def write_outputs(report: dict[str, Any], output_json: Path, output_strict: Path, output_review_csv: Path, output_rejected_csv: Path, output_md: Path) -> None:
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_strict.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "generated_at": report["generated_at"], "report_type": "catalog_growth_strict_promotions", "posture": report["posture"], "summary": {"action_count": len(report["strict_promotions"])}, "actions": report["strict_promotions"]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for path, rows in ((output_review_csv, [item for item in report["items"] if item["classification"] == REVIEW_REQUIRED]), (output_rejected_csv, [item for item in report["items"] if item["classification"] not in {STRICT_PROMOTE_READY, REVIEW_REQUIRED}])):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                csv_row = dict(row)
                csv_row["reason_codes"] = ";".join(csv_row.get("reason_codes", []))
                writer.writerow(csv_row)
    lines = ["# Catalog Growth Eligibility Summary", "", "This report classifies Lane B discovery outputs without mutating canonical records.", "", "## Summary", "", f"- Candidate vendors: `{report['summary']['candidate_count']}`", f"- Strict promote ready: `{report['summary']['strict_promote_ready_count']}`", f"- Review required: `{report['summary']['review_required_count']}`", f"- Rejected or deferred: `{report['summary']['rejected_or_deferred_count']}`", f"- Redirects detected: `{report['summary'].get('redirect_count', 0)}`", f"- Redirects canonicalized: `{report['summary'].get('redirect_canonicalized_count', 0)}`", f"- Redirects deferred: `{report['summary'].get('redirect_deferred_count', 0)}`", f"- Cross-authority redirects: `{report['summary'].get('cross_authority_redirect_count', 0)}`", f"- Generic redirects rejected: `{report['summary'].get('generic_redirect_rejected_count', 0)}`", f"- Unresolved redirects: `{report['summary'].get('unresolved_redirect_count', 0)}`", "", "## Classification Counts", ""]
    lines.extend(f"- `{name}`: `{count}`" for name, count in report["summary"]["classification_counts"].items())
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-growth-eligibility")
    parser.add_argument("command", choices={"classify"})
    parser.add_argument("--vendor-candidates", type=Path, required=True)
    parser.add_argument("--source-discovery", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=ROOT / "catalog-growth-eligibility-report.json")
    parser.add_argument("--output-strict", type=Path, default=ROOT / "catalog-growth-strict-promotions.json")
    parser.add_argument("--output-review-csv", type=Path, default=ROOT / "catalog-growth-review-required.csv")
    parser.add_argument("--output-rejected-csv", type=Path, default=ROOT / "catalog-growth-rejected.csv")
    parser.add_argument("--output-md", type=Path, default=ROOT / "catalog-growth-eligibility-summary.md")
    parser.add_argument("--head-sha")
    parser.add_argument("--base-sha")
    args = parser.parse_args()
    report = build_catalog_growth_eligibility(
        load_json(args.vendor_candidates),
        load_json(args.source_discovery),
        head_sha=args.head_sha,
        base_sha=args.base_sha,
    )
    write_outputs(report, args.output_json, args.output_strict, args.output_review_csv, args.output_rejected_csv, args.output_md)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
