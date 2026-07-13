from __future__ import annotations

import argparse
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import yaml

from tools.openva.candidate_promotion_actions import (
    apply_candidate_promotions,
    filter_reviewed_candidate_plan,
    normalize_source_url_for_comparison,
)
from tools.openva.catalog_lifecycle import change_event
from tools.openva.catalog_source_completion import EXPECTED_GROUPS, build_report, vendor_completion
from tools.openva.indexes import ROOT
from tools.openva.safe_fetch import build_safe_fetcher
from tools.openva.sitemap_discovery import discover_sitemap_candidates, load_bounds
from tools.openva.source_authority import is_on_official_domain
from tools.openva.source_discovery import (
    canonical_source_types_for_vendor,
    discover_for_vendor,
    not_due_unavailable_source_types,
    safe_discovery_fetcher,
    unavailable_record,
    verify_sitemap_locators,
    write_discovery_outputs,
)

GROUP_TYPES = {key: tuple(sorted(value)) for key, value in EXPECTED_GROUPS.items()}
TYPE_PRIORITY = {
    "dpa": 0,
    "subprocessors_list": 1,
    "privacy_notice": 2,
    "trust_center": 3,
    "security_page": 4,
    "compliance_page": 5,
    "certification_reference": 6,
}
TYPE_TERMS = {
    "dpa": ("dpa", "data-processing", "data_processing", "data processing"),
    "subprocessors_list": ("subprocessor", "sub-processor", "sub processor", "third-party-processor"),
    "privacy_notice": ("privacy",),
    "security_page": ("security", "trust"),
    "trust_center": ("trust", "security", "compliance"),
    "compliance_page": ("compliance", "soc", "iso", "certification"),
    "certification_reference": ("certification", "certificate", "soc", "iso", "audit"),
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def locator_relevant(url: str, source_types: set[str]) -> bool:
    low = url.lower().replace("_", "-")
    return any(term in low for source_type in source_types for term in TYPE_TERMS[source_type])


def official_link_locators(vendor: dict[str, Any], source_types: set[str]) -> tuple[list[str], list[str]]:
    domains = [str(item) for item in vendor.get("official_domains") or [] if item]
    starts = [str(item) for item in vendor.get("public_entrypoints") or [] if item]
    for domain in domains:
        starts.extend((f"https://{domain}", f"https://www.{domain}"))
    starts = list(dict.fromkeys(starts))
    fetcher = safe_discovery_fetcher(vendor, fetch_timeout=6.0)
    found: set[str] = set()
    checked: list[str] = []
    for start in starts:
        checked.append(start)
        result = fetcher(start)
        if result.http_status != 200:
            continue
        final_url = result.final_url or start
        if locator_relevant(final_url, source_types) and is_on_official_domain(final_url, domains):
            found.add(final_url)
        content_type = str(result.content_type or "").lower()
        if "html" not in content_type:
            continue
        parser = LinkParser()
        try:
            parser.feed(result.body_sample.decode("utf-8", "replace"))
        except Exception:
            continue
        for href in parser.hrefs:
            try:
                absolute = urljoin(final_url, href)
                parsed = urlparse(absolute)
            except ValueError:
                continue
            if parsed.scheme not in {"http", "https"}:
                continue
            if not is_on_official_domain(absolute, domains):
                continue
            if locator_relevant(absolute, source_types):
                found.add(absolute)
    return sorted(found), checked


def sitemap_locators(vendor: dict[str, Any], source_types: set[str], run_id: str, discovered_at: str) -> tuple[list[str], list[str]]:
    domains = [str(item) for item in vendor.get("official_domains") or [] if item]
    bounds = load_bounds()
    found: set[str] = set()
    checked: list[str] = []
    for primary in domains:
        ordered = [primary, *[domain for domain in domains if domain != primary]]
        fetcher = build_safe_fetcher(
            ordered,
            max_redirects=bounds.max_redirects,
            timeout_seconds=min(bounds.max_request_seconds, 8.0),
            max_compressed_bytes=bounds.max_compressed_bytes,
            max_decompressed_bytes=bounds.max_decompressed_bytes,
        )
        try:
            outcome = discover_sitemap_candidates(
                ordered,
                fetcher.fetch,
                bounds=bounds,
                discovery_run_id=run_id,
                discovered_at=discovered_at,
                vendor_id=str(vendor["vendor_id"]),
            )
        except Exception as exc:
            checked.append(f"sitemap-error:{primary}:{type(exc).__name__}")
            continue
        checked.extend(str(item.get("url") or "") for item in outcome.rejected if item.get("url"))
        for item in outcome.candidates:
            url = str(item.get("url") or "")
            if url and locator_relevant(url, source_types):
                found.add(url)
    return sorted(found), checked


def candidate_score(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
    evidence = candidate.get("evidence") or {}
    return (
        2 if candidate.get("confidence") == "likely" else 1,
        2 if evidence.get("semantic_status") == "strong" else 1,
        -len(str(candidate.get("canonical_candidate_url") or candidate.get("candidate_url") or "")),
        str(candidate.get("candidate_url") or ""),
    )


def canonicalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(candidate)
    canonical = str(candidate.get("canonical_candidate_url") or "")
    if canonical:
        candidate["candidate_url"] = canonical
    return candidate


def merge_duplicate_url_roles(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        url = normalize_source_url_for_comparison(candidate.get("candidate_url"))
        by_url.setdefault(url, []).append(candidate)
    merged: list[dict[str, Any]] = []
    for url in sorted(by_url):
        records = by_url[url]
        records.sort(key=lambda row: (TYPE_PRIORITY.get(str(row.get("source_type_candidate")), 99), str(row.get("candidate_source_id"))))
        primary = dict(records[0])
        claims = list(primary.get("coverage_claims") or [])
        primary_type = str(primary.get("source_type_candidate"))
        for record in records[1:]:
            role = str(record.get("source_type_candidate") or "")
            if not role or role == primary_type or any(claim.get("role") == role for claim in claims if isinstance(claim, dict)):
                continue
            claims.append(
                {
                    "role": role,
                    "coverage_type": "contains",
                    "evidence": "The same official public page returned HTTP 200 and strong source-type-specific semantic evidence for this role during bounded source-completion discovery.",
                }
            )
        if claims:
            primary["coverage_claims"] = claims
        merged.append(primary)
    return merged


def discover_vendor(vendor_id: str, group: str) -> dict[str, Any]:
    vendor_path = ROOT / "data" / "vendors" / vendor_id / "vendor.yaml"
    vendor = load_yaml(vendor_path)
    requested_types = set(GROUP_TYPES[group])
    existing = canonical_source_types_for_vendor(vendor_id, ROOT)
    unavailable_existing = not_due_unavailable_source_types(vendor_id, ROOT)
    types_to_check = requested_types - existing - unavailable_existing
    if not types_to_check:
        return {"vendor_id": vendor_id, "group": group, "candidates": [], "unavailable_sources": [], "observations": [], "errors": []}

    errors: list[str] = []
    try:
        narrow = discover_for_vendor(
            vendor,
            root=ROOT,
            source_types=tuple(sorted(types_to_check)),
            max_urls_per_type=20,
            fetch_timeout=6.0,
        )
    except Exception as exc:
        narrow = {"candidates": [], "unavailable_sources": [], "observations": [], "discovery_events": []}
        errors.append(f"official_path_discovery:{type(exc).__name__}:{exc}")

    candidates = [canonicalize_candidate(item) for item in narrow.get("candidates") or []]
    checked_urls: dict[str, list[str]] = {source_type: [] for source_type in types_to_check}
    for observation in narrow.get("observations") or []:
        source_type = str(observation.get("source_type") or "")
        url = str(observation.get("candidate_url") or "")
        if source_type in checked_urls and url:
            checked_urls[source_type].append(url)

    strong_types = {
        str(item.get("source_type_candidate"))
        for item in candidates
        if item.get("confidence") == "likely"
    }
    still_missing = types_to_check - strong_types
    locator_checks: list[str] = []
    if still_missing:
        discovered_at = now_iso()
        run_id = f"owner-source-completion-1-{vendor_id}-{group}-{discovered_at}"
        try:
            linked, checked = official_link_locators(vendor, still_missing)
            locator_checks.extend(checked)
        except Exception as exc:
            linked = []
            errors.append(f"official_link_discovery:{type(exc).__name__}:{exc}")
        try:
            sitemap, checked = sitemap_locators(vendor, still_missing, run_id, discovered_at)
            locator_checks.extend(checked)
        except Exception as exc:
            sitemap = []
            errors.append(f"sitemap_discovery:{type(exc).__name__}:{exc}")
        locators = list(dict.fromkeys([*linked, *sitemap]))
        if locators:
            try:
                verified = verify_sitemap_locators(
                    vendor,
                    locators,
                    fetcher=safe_discovery_fetcher(vendor, fetch_timeout=6.0),
                    source_types=tuple(sorted(still_missing)),
                    discovered_at=discovered_at,
                    discovery_run_id=run_id,
                    max_locators=load_bounds().max_candidate_urls,
                )
                candidates.extend(canonicalize_candidate(item) for item in verified.get("candidates") or [])
                for observation in verified.get("observations") or []:
                    source_type = str(observation.get("source_type") or "")
                    url = str(observation.get("candidate_url") or "")
                    if source_type in checked_urls and url:
                        checked_urls[source_type].append(url)
                narrow.setdefault("observations", []).extend(verified.get("observations") or [])
            except Exception as exc:
                errors.append(f"locator_verification:{type(exc).__name__}:{exc}")

    best_by_type: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        source_type = str(candidate.get("source_type_candidate") or "")
        if source_type not in types_to_check or candidate.get("confidence") != "likely":
            continue
        current = best_by_type.get(source_type)
        if current is None or candidate_score(candidate) > candidate_score(current):
            best_by_type[source_type] = candidate
    selected = merge_duplicate_url_roles(list(best_by_type.values()))
    covered = {
        str(candidate.get("source_type_candidate"))
        for candidate in selected
    }
    for candidate in selected:
        covered.update(
            str(claim.get("role"))
            for claim in candidate.get("coverage_claims") or []
            if isinstance(claim, dict) and claim.get("role")
        )

    reviewed_at = now_iso()
    next_review = (date.today() + timedelta(days=90)).isoformat()
    unavailable = []
    for source_type in sorted(types_to_check - covered):
        evidence_urls = list(dict.fromkeys([*checked_urls.get(source_type, []), *locator_checks]))
        record = unavailable_record(vendor_id, source_type, evidence_urls, reviewed_at, next_review)
        record["notes"] = "No source-type-correct canonical public source was identified after bounded official-path, official-link, and robots/sitemap discovery. This is a factual OpenVA search result, not a vendor quality or risk conclusion."
        unavailable.append(record)

    return {
        "vendor_id": vendor_id,
        "group": group,
        "candidates": selected,
        "unavailable_sources": unavailable,
        "observations": narrow.get("observations") or [],
        "errors": errors,
    }


def discover_group(group: str, output: Path) -> None:
    report = build_report(ROOT, today=date.today())
    vendor_ids = report["unresolved_by_group"][group]
    workers = min(12, max(1, len(vendor_ids)))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(discover_vendor, vendor_id, group): vendor_id for vendor_id in vendor_ids}
        for future in as_completed(futures):
            vendor_id = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"vendor_id": vendor_id, "group": group, "candidates": [], "unavailable_sources": [], "observations": [], "errors": [f"unhandled:{type(exc).__name__}:{exc}"]})
    results.sort(key=lambda row: row["vendor_id"])
    payload = {
        "schema_version": "0.1.0",
        "report_type": "owner_source_completion_discovery_group",
        "group": group,
        "source_types": list(GROUP_TYPES[group]),
        "generated_at": now_iso(),
        "summary": {
            "vendors_checked": len(results),
            "candidates": sum(len(row["candidates"]) for row in results),
            "unavailable_records": sum(len(row["unavailable_sources"]) for row in results),
            "vendors_with_errors": sum(bool(row["errors"]) for row in results),
        },
        "vendors": results,
        "not_advice": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))


def add_duplicate_claims(skipped: list[dict[str, Any]]) -> int:
    changes = 0
    for item in skipped:
        reasons = set(item.get("reason_codes") or [])
        if "duplicate_canonical_source_url" not in reasons:
            continue
        vendor_id = str(item.get("vendor_id") or "")
        candidate_id = str(item.get("candidate_source_id") or "")
        candidate_path = ROOT / "data" / "vendors" / vendor_id / "candidate_sources" / f"{candidate_id}.yaml"
        if not candidate_path.exists():
            continue
        candidate = load_yaml(candidate_path)
        role = str(candidate.get("source_type_candidate") or "")
        candidate_url = normalize_source_url_for_comparison(candidate.get("candidate_url"))
        for source_path in sorted((ROOT / "data" / "vendors" / vendor_id / "sources").glob("*.yaml")):
            source = load_yaml(source_path)
            if normalize_source_url_for_comparison(source.get("source_url")) != candidate_url:
                continue
            claims = list(source.get("coverage_claims") or [])
            if any(isinstance(claim, dict) and claim.get("role") == role for claim in claims):
                break
            claims.append(
                {
                    "role": role,
                    "coverage_type": "contains",
                    "evidence": "The existing official public source URL independently returned HTTP 200 and strong source-type-specific semantic evidence for this additional role during source-completion discovery.",
                }
            )
            source["coverage_claims"] = claims
            write_yaml(source_path, source)
            event_path = ROOT / "data" / "vendors" / vendor_id / "changes" / f"owner-source-completion-claim-{source['source_id']}-{role.replace('_', '-')}.yaml"
            if not event_path.exists():
                write_yaml(
                    event_path,
                    change_event(
                        change_id=f"owner-source-completion-claim-{source['source_id']}-{role.replace('_', '-')}",
                        vendor_id=vendor_id,
                        source_id=str(source["source_id"]),
                        artifact_id=str(source["source_id"]),
                        change_type="updated",
                        detected_at=now_iso(),
                        summary="Owner-led source completion added an evidence-backed coverage role to an existing canonical public source.",
                    ),
                )
            changes += 1
            break
    return changes


def aggregate(reports_dir: Path, output_dir: Path) -> None:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(reports_dir.glob("*.json"))]
    candidates: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for report in reports:
        for vendor in report.get("vendors") or []:
            candidates.extend(vendor.get("candidates") or [])
            unavailable.extend(vendor.get("unavailable_sources") or [])
            if vendor.get("errors"):
                errors.append({"vendor_id": vendor.get("vendor_id"), "group": vendor.get("group"), "errors": vendor.get("errors")})

    created_candidates: list[Path] = []
    for candidate in candidates:
        vendor_id = str(candidate["vendor_id"])
        path = ROOT / "data" / "vendors" / vendor_id / "candidate_sources" / f"{candidate['candidate_source_id']}.yaml"
        write_discovery_outputs({"vendor_id": vendor_id, "candidates": [candidate], "unavailable_sources": []}, root=ROOT)
        created_candidates.append(path)
    for record in unavailable:
        write_discovery_outputs({"vendor_id": str(record["vendor_id"]), "candidates": [], "unavailable_sources": [record]}, root=ROOT)

    actions = [
        {
            "action": "promote_candidate_source_for_review",
            "reason": "Owner-led source completion candidate has public HTTP 200 evidence and strong source-type-specific terms.",
            "vendor_id": str(candidate["vendor_id"]),
            "source_type": str(candidate["source_type_candidate"]),
            "candidate_source_id": str(candidate["candidate_source_id"]),
            "candidate_url": str(candidate["candidate_url"]),
            "path": str((ROOT / "data" / "vendors" / str(candidate["vendor_id"]) / "candidate_sources" / f"{candidate['candidate_source_id']}.yaml").relative_to(ROOT)),
            "evidence": {
                "confidence": candidate.get("confidence"),
                "http_status": (candidate.get("evidence") or {}).get("http_status"),
                "matched_terms": (candidate.get("evidence") or {}).get("matched_terms") or [],
                "page_title": (candidate.get("evidence") or {}).get("page_title"),
            },
            "requires_human_review": True,
            "writes_canonical_sources": False,
            "non_advisory": True,
            "coverage_claims": candidate.get("coverage_claims") or [],
        }
        for candidate in candidates
    ]
    plan = {
        "schema_version": "0.1.0",
        "report_type": "promotion_plan",
        "generated_at": now_iso(),
        "summary": {"action_count": len(actions)},
        "actions": actions,
        "not_advice": True,
    }
    filtered, viability = filter_reviewed_candidate_plan(plan, root=ROOT, max_actions=None)
    apply_report = apply_candidate_promotions(filtered, root=ROOT)
    claim_updates = add_duplicate_claims(apply_report.get("skipped") or [])

    for path in created_candidates:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    # Any group still unresolved after promotion receives fresh per-type unavailable
    # evidence, using the URLs checked in the discovery reports. This is a bounded
    # search result, never an assertion that the vendor does not publish the source.
    checked_by_key: dict[tuple[str, str], list[str]] = {}
    for report in reports:
        for vendor in report.get("vendors") or []:
            for observation in vendor.get("observations") or []:
                key = (str(vendor.get("vendor_id")), str(observation.get("source_type") or ""))
                url = str(observation.get("candidate_url") or "")
                if url:
                    checked_by_key.setdefault(key, []).append(url)
    fallback_unavailable = 0
    completion = build_report(ROOT, today=date.today())
    next_review = (date.today() + timedelta(days=90)).isoformat()
    for row in completion["vendors"]:
        vendor_id = str(row["vendor_id"])
        vendor_dir = ROOT / "data" / "vendors" / vendor_id
        for group in row["unresolved_groups"]:
            for source_type in sorted(EXPECTED_GROUPS[group]):
                current = vendor_completion(vendor_dir, today=date.today())
                if group not in current["unresolved_groups"]:
                    break
                record = unavailable_record(
                    vendor_id,
                    source_type,
                    list(dict.fromkeys(checked_by_key.get((vendor_id, source_type), []))),
                    now_iso(),
                    next_review,
                )
                record["notes"] = "No source-type-correct canonical public source was identified after bounded official-path, official-link, and robots/sitemap discovery. This is a factual OpenVA search result, not a vendor quality or risk conclusion."
                write_discovery_outputs({"vendor_id": vendor_id, "candidates": [], "unavailable_sources": [record]}, root=ROOT)
                fallback_unavailable += 1

    final_report = build_report(ROOT, today=date.today())
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "source-completion-report.json").write_text(json.dumps(final_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    operational = {
        "schema_version": "0.1.0",
        "report_type": "owner_source_completion_operational_summary",
        "generated_at": now_iso(),
        "discovery_groups": [report.get("group") for report in reports],
        "candidates_selected": len(candidates),
        "viable_candidates": viability["summary"]["viable_action_count"],
        "canonical_sources_written": apply_report["summary"]["canonical_sources_written"],
        "coverage_claims_added_to_existing_sources": claim_updates,
        "discovery_unavailable_records": len(unavailable),
        "fallback_unavailable_records": fallback_unavailable,
        "discovery_error_rows": errors,
        "completion_summary": final_report["summary"],
        "not_advice": True,
    }
    (output_dir / "operational-summary.json").write_text(json.dumps(operational, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(operational, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    discover = sub.add_parser("discover-group")
    discover.add_argument("--group", required=True, choices=sorted(GROUP_TYPES))
    discover.add_argument("--output", type=Path, required=True)
    combine = sub.add_parser("aggregate")
    combine.add_argument("--reports-dir", type=Path, required=True)
    combine.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "discover-group":
        discover_group(args.group, args.output)
    else:
        aggregate(args.reports_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
