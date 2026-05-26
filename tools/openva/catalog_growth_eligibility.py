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

from tools.openva.source_discovery import DEFAULT_SOURCE_TYPES
from tools.openva.source_verification import ROOT, display_path

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
CSV_FIELDS = ["candidate_vendor_id", "display_name_candidate", "official_domain_candidate", "coverage_lane", "cohort_id", "classification", "reason_codes", "source_candidate_count", "strict_source_count", "promotable_now"]


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


def current_vendor_identity(root: Path = ROOT) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    domains: set[str] = set()
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        ids.add(str(vendor.get("vendor_id") or path.parent.name))
        for domain in vendor.get("official_domains", []) or []:
            if normalize_domain(domain):
                domains.add(normalize_domain(domain))
        for entrypoint in vendor.get("public_entrypoints", []) or []:
            if normalize_domain(entrypoint):
                domains.add(normalize_domain(entrypoint))
    return ids, domains


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


def source_reasons(source: dict[str, Any]) -> list[str]:
    evidence = source.get("evidence", {}) or {}
    reasons: list[str] = []
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
    if source.get("requires_review") is not True:
        reasons.append("requires_review_not_true")
    if source.get("not_advice") is not True:
        reasons.append("not_advice_not_true")
    return reasons


def strict_action(vendor: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "strict_catalog_growth_promotion_candidate",
        "vendor": {key: vendor.get(key) for key in ["candidate_vendor_id", "display_name_candidate", "official_domain_candidate", "coverage_lane", "cohort_id", "vendor_category_candidates", "headquarters_country_candidate"]},
        "source": {key: source.get(key) for key in ["candidate_source_id", "vendor_id", "source_type_candidate", "candidate_url", "confidence", "evidence"]},
        "posture": {"network_fetch_performed": False, "writes_repository_state": False, "writes_canonical_sources": False, "strict_machine_candidate": True, "non_advisory": True},
    }


def classify(vendor: dict[str, Any], sources: list[dict[str, Any]], statuses: set[str], id_reasons: list[str]) -> tuple[str, list[str], list[dict[str, Any]]]:
    if "candidate_already_in_catalog" in id_reasons:
        return REJECT_EXISTING_VENDOR, id_reasons, []
    if any(reason.startswith("duplicate_candidate") for reason in id_reasons):
        return REJECT_DUPLICATE, id_reasons, []
    if id_reasons:
        return REJECT_IDENTITY_UNCLEAR, id_reasons, []
    if statuses & ACCESS_AMBIGUOUS:
        return REJECT_ACCESS_AMBIGUOUS, sorted(statuses & ACCESS_AMBIGUOUS), []
    if statuses & HEALTH_FAILURE:
        return REJECT_SOURCE_HEALTH_FAILURE, sorted(statuses & HEALTH_FAILURE), []
    if not sources:
        return REJECT_NO_PUBLIC_SOURCE, ["no_source_candidates_for_vendor"], []
    strict_sources = [source for source in sources if not source_reasons(source)]
    if strict_sources:
        return STRICT_PROMOTE_READY, ["strict_source_candidate_evidence_present"], strict_sources
    reasons = sorted({reason for source in sources for reason in source_reasons(source)})
    if {"http_status_not_200", "final_url_missing"} & set(reasons):
        return REJECT_SOURCE_HEALTH_FAILURE, reasons, []
    if {"confidence_not_likely", "matched_terms_missing"} & set(reasons):
        return REJECT_WEAK_SEMANTIC_MATCH, reasons, []
    return REVIEW_REQUIRED, reasons or ["source_candidate_requires_review"], []


def build_catalog_growth_eligibility(vendor_report: dict[str, Any], source_report: dict[str, Any], root: Path = ROOT, generated_at: str | None = None) -> dict[str, Any]:
    if vendor_report.get("report_type") != "vendor_candidate_discovery_report":
        raise ValueError("expected vendor_candidate_discovery_report")
    if source_report.get("report_type") != "source_discovery_report":
        raise ValueError("expected source_discovery_report")
    candidates = [row for row in vendor_report.get("vendor_candidates", []) or [] if isinstance(row, dict)]
    dup_ids = duplicate_values(candidates, "candidate_vendor_id", lambda value: str(value or ""))
    dup_domains = duplicate_values(candidates, "official_domain_candidate", normalize_domain)
    known_ids, known_domains = current_vendor_identity(root)
    source_map = sources_by_vendor(source_report)
    status_map = observation_statuses(source_report)
    items: list[dict[str, Any]] = []
    strict_promotions: list[dict[str, Any]] = []
    for vendor in candidates:
        vendor_id = str(vendor.get("candidate_vendor_id") or "")
        vendor_sources = source_map.get(vendor_id, [])
        classification, reasons, strict_sources = classify(vendor, vendor_sources, status_map.get(vendor_id, set()), identity_reasons(vendor, dup_ids, dup_domains, known_ids, known_domains))
        strict_promotions.extend(strict_action(vendor, source) for source in strict_sources)
        items.append({"candidate_vendor_id": vendor_id, "display_name_candidate": vendor.get("display_name_candidate"), "official_domain_candidate": vendor.get("official_domain_candidate"), "coverage_lane": vendor.get("coverage_lane"), "cohort_id": vendor.get("cohort_id"), "classification": classification, "reason_codes": reasons, "source_candidate_count": len(vendor_sources), "strict_source_count": len(strict_sources), "promotable_now": classification == STRICT_PROMOTE_READY})
    counts = Counter(item["classification"] for item in items)
    return {"schema_version": SCHEMA_VERSION, "generated_at": generated_at or now_iso(), "report_type": REPORT_TYPE, "posture": {"network_fetch_performed": False, "writes_repository_state": False, "writes_canonical_vendors": False, "writes_canonical_sources": False, "opens_pull_requests": False, "non_advisory": True}, "summary": {"candidate_count": len(items), "strict_promote_ready_count": counts.get(STRICT_PROMOTE_READY, 0), "review_required_count": counts.get(REVIEW_REQUIRED, 0), "rejected_or_deferred_count": len(items) - counts.get(STRICT_PROMOTE_READY, 0) - counts.get(REVIEW_REQUIRED, 0), "classification_counts": dict(sorted(counts.items())), "strict_promotion_action_count": len(strict_promotions)}, "items": sorted(items, key=lambda item: (item["classification"], item["candidate_vendor_id"])), "strict_promotions": strict_promotions}


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
    lines = ["# Catalog Growth Eligibility Summary", "", "This report classifies Lane B discovery outputs without mutating canonical records.", "", "## Summary", "", f"- Candidate vendors: `{report['summary']['candidate_count']}`", f"- Strict promote ready: `{report['summary']['strict_promote_ready_count']}`", f"- Review required: `{report['summary']['review_required_count']}`", f"- Rejected or deferred: `{report['summary']['rejected_or_deferred_count']}`", "", "## Classification Counts", ""]
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
    args = parser.parse_args()
    report = build_catalog_growth_eligibility(load_json(args.vendor_candidates), load_json(args.source_discovery))
    write_outputs(report, args.output_json, args.output_strict, args.output_review_csv, args.output_rejected_csv, args.output_md)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
