from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import yaml

from tools.openva.candidate_promotion_actions import artifact_from_source, source_from_candidate
from tools.openva.catalog_lifecycle import change_event
from tools.openva.catalog_source_completion import build_report
from tools.openva.indexes import ROOT
from tools.openva.safe_verify import build_safe_verify_fetcher
from tools.openva.sitemap_discovery import discover_sitemap_candidates, load_bounds
from tools.openva.source_authority import is_on_official_domain
from tools.openva.source_discovery import candidate_source_id, safe_discovery_fetcher, unavailable_record
from tools.openva.source_verification import (
    classify_status,
    looks_like_soft_not_found,
    normalize_text,
    semantic_match,
    title_from_sample,
)

GROUP_TYPES = {
    "terms_of_service": ("terms_of_service",),
    "status_page": ("status_page",),
    "privacy_notice": ("privacy_notice",),
    "security_assurance": ("trust_center", "security_page", "compliance_page"),
}

PATHS = {
    "terms_of_service": (
        "/terms", "/terms-of-service", "/terms-of-use", "/legal/terms",
        "/legal/terms-of-service", "/legal/terms-of-use", "/terms-and-conditions",
        "/legal/terms-and-conditions", "/service-terms", "/legal/service-terms",
        "/user-agreement", "/legal/user-agreement", "/terms.html",
    ),
    "status_page": ("/status", "/statuspage", "/system-status", "/service-status", "/uptime"),
    "privacy_notice": ("/privacy", "/privacy-policy", "/legal/privacy", "/legal/privacy-policy", "/privacy.html"),
    "trust_center": ("/trust", "/trust-center", "/trustcenter", "/security/trust", "/security/compliance"),
    "security_page": ("/security", "/security.html", "/trust", "/trust-center"),
    "compliance_page": ("/compliance", "/security/compliance", "/trust/compliance", "/trust-center/compliance"),
}

TERMS = {
    "terms_of_service": ("terms", "terms of service", "terms of use", "terms and conditions", "service terms", "user agreement", "legal terms"),
    "status_page": ("status", "service status", "system status", "uptime", "operational", "incident"),
    "privacy_notice": ("privacy", "privacy policy", "privacy notice"),
    "trust_center": ("trust", "trust center", "trust centre"),
    "security_page": ("security", "secure", "trust"),
    "compliance_page": ("compliance", "certification", "soc", "iso", "audit", "trust"),
}

EDITORIAL = {
    "blog", "blogs", "article", "articles", "news", "press", "webinar", "webinars",
    "event", "events", "academy", "learn", "podcast", "case-study", "case-studies",
    "customer-stories", "integrations", "marketplace",
}

STATUS_HOST_HINTS = ("statuspage.io", "status.io", "betteruptime.com", "incident.io", "instatus.com", "atlassian.net")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self.current_href = next((value for key, value in attrs if key.lower() == "href" and value), None)
        self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.current_href:
            self.links.append((self.current_href, " ".join(self.current_text).strip()))
            self.current_href = None
            self.current_text = []


def official_domains(vendor: dict[str, Any]) -> list[str]:
    return [str(value).strip().lower().removeprefix("www.") for value in vendor.get("official_domains") or [] if value]


def base_urls(vendor: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in vendor.get("public_entrypoints") or []:
        parsed = urlparse(str(value))
        if parsed.scheme and parsed.netloc:
            urls.append(f"{parsed.scheme}://{parsed.netloc}")
    for domain in official_domains(vendor):
        urls.extend((f"https://{domain}", f"https://www.{domain}"))
    return list(dict.fromkeys(url.rstrip("/") for url in urls))


def relevant(group: str, url: str, anchor: str = "") -> bool:
    text = f"{urlparse(url).hostname or ''} {urlparse(url).path} {anchor}".lower().replace("_", " ").replace("-", " ")
    return any(term in text for source_type in GROUP_TYPES[group] for term in TERMS[source_type])


def purpose_ok(source_type: str, requested_url: str, final_url: str, title: str | None, anchor: str) -> tuple[bool, list[str]]:
    requested = urlparse(requested_url)
    final = urlparse(final_url or requested_url)
    segments = [part.lower() for part in requested.path.split("/") if part] + [part.lower() for part in final.path.split("/") if part]
    host = (final.hostname or "").lower()
    text = " ".join([host, " ".join(segments), title or "", anchor]).lower().replace("_", " ").replace("-", " ")
    reasons: list[str] = []
    if set(segments) & EDITORIAL:
        reasons.append("editorial_path")
    if "@" in requested.path or "@" in final.path or set(segments) & {"community", "forum", "forums"}:
        reasons.append("user_generated_path")
    specialized = any(token in host.split(".")[0] for token in ("legal", "status", "trust", "security", "privacy", "compliance"))
    if not segments and not specialized:
        reasons.append("generic_homepage")
    if not any(term in text for term in TERMS[source_type]):
        reasons.append("missing_page_purpose")
    return not reasons, reasons


def fetcher_for(vendor: dict[str, Any], url: str, *, linked_from_official: bool):
    domains = official_domains(vendor)
    if is_on_official_domain(url, domains):
        return safe_discovery_fetcher(vendor, fetch_timeout=8.0)
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if linked_from_official and host and any(hint in host for hint in STATUS_HOST_HINTS):
        bounds = load_bounds()
        return build_safe_verify_fetcher(
            [host],
            max_redirects=bounds.max_redirects,
            timeout_seconds=min(8.0, bounds.max_request_seconds),
        )
    return None


def candidate_urls(vendor: dict[str, Any], group: str) -> list[dict[str, Any]]:
    domains = official_domains(vendor)
    official_fetch = safe_discovery_fetcher(vendor, fetch_timeout=8.0)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(url: str, method: str, anchor: str = "", linked: bool = False) -> None:
        if not url.startswith(("http://", "https://")) or url in seen:
            return
        seen.add(url)
        candidates.append({"url": url, "method": method, "anchor": anchor, "linked_from_official": linked})

    for base in base_urls(vendor):
        for source_type in GROUP_TYPES[group]:
            for path in PATHS[source_type]:
                add(f"{base}{path}", "known_official_path")
        if group == "status_page":
            domain = (urlparse(base).hostname or "").lower().removeprefix("www.")
            if domain:
                add(f"https://status.{domain}", "known_status_subdomain")
        if group == "security_assurance":
            domain = (urlparse(base).hostname or "").lower().removeprefix("www.")
            if domain:
                add(f"https://trust.{domain}", "known_trust_subdomain")
                add(f"https://security.{domain}", "known_security_subdomain")

    crawl_starts = list(dict.fromkeys([
        *base_urls(vendor),
        *[f"{base}/legal" for base in base_urls(vendor)],
        *[f"{base}/policies" for base in base_urls(vendor)],
    ]))
    linked_pages: list[str] = []
    for start in crawl_starts[:12]:
        result = official_fetch(start)
        if result.http_status != 200 or "html" not in str(result.content_type or "").lower():
            continue
        parser = AnchorParser()
        try:
            parser.feed(result.body_sample.decode("utf-8", "replace"))
        except Exception:
            continue
        for href, anchor in parser.links:
            absolute = urljoin(result.final_url or start, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            on_official = is_on_official_domain(absolute, domains)
            if relevant(group, absolute, anchor):
                if on_official or group == "status_page":
                    add(absolute, "official_page_link", anchor, linked=True)
            elif on_official and group == "terms_of_service" and any(token in parsed.path.lower() for token in ("legal", "policy", "policies")):
                linked_pages.append(absolute)

    for page in list(dict.fromkeys(linked_pages))[:10]:
        result = official_fetch(page)
        if result.http_status != 200 or "html" not in str(result.content_type or "").lower():
            continue
        parser = AnchorParser()
        try:
            parser.feed(result.body_sample.decode("utf-8", "replace"))
        except Exception:
            continue
        for href, anchor in parser.links:
            absolute = urljoin(result.final_url or page, href)
            if is_on_official_domain(absolute, domains) and relevant(group, absolute, anchor):
                add(absolute, "official_legal_page_link", anchor, linked=True)

    # Sitemaps are the final official-domain lookup pass. Only purpose-shaped URLs
    # are admitted to verification; the sitemap result itself never becomes a source.
    if len(candidates) < 35 and domains:
        bounds = load_bounds()
        for primary in domains[:2]:
            ordered = [primary, *[domain for domain in domains if domain != primary]]
            try:
                from tools.openva.safe_fetch import build_safe_fetcher
                sitemap_fetcher = build_safe_fetcher(
                    ordered,
                    max_redirects=bounds.max_redirects,
                    timeout_seconds=min(8.0, bounds.max_request_seconds),
                    max_compressed_bytes=bounds.max_compressed_bytes,
                    max_decompressed_bytes=bounds.max_decompressed_bytes,
                )
                outcome = discover_sitemap_candidates(
                    ordered,
                    sitemap_fetcher.fetch,
                    bounds=bounds,
                    discovery_run_id=f"expanded-completion-{vendor['vendor_id']}-{group}",
                    discovered_at=now_iso(),
                    vendor_id=str(vendor["vendor_id"]),
                )
                for item in outcome.candidates:
                    url = str(item.get("url") or "")
                    if relevant(group, url):
                        add(url, "official_sitemap_locator")
            except Exception:
                continue
    return candidates[:80]


def classify_source_type(group: str, item: dict[str, Any], result) -> list[str]:
    if group != "security_assurance":
        return list(GROUP_TYPES[group])
    text = f"{item['url']} {result.final_url or ''} {item.get('anchor') or ''} {title_from_sample(result.body_sample, result.content_type) or ''}".lower()
    ordered: list[str] = []
    if "trust" in text:
        ordered.append("trust_center")
    if "security" in text:
        ordered.append("security_page")
    if any(term in text for term in ("compliance", "soc", "iso", "certification")):
        ordered.append("compliance_page")
    ordered.extend(source_type for source_type in GROUP_TYPES[group] if source_type not in ordered)
    return ordered


def verify_candidate(vendor: dict[str, Any], group: str, item: dict[str, Any]) -> dict[str, Any] | None:
    fetch = fetcher_for(vendor, item["url"], linked_from_official=bool(item.get("linked_from_official")))
    if fetch is None:
        return None
    result = fetch(item["url"])
    if result.http_status != 200 or looks_like_soft_not_found(result):
        return None
    title = title_from_sample(result.body_sample, result.content_type)
    normalized = normalize_text(result.body_sample, result.content_type)
    best: dict[str, Any] | None = None
    for source_type in classify_source_type(group, item, result):
        semantic = semantic_match(source_type, normalized, result.content_type)
        status = classify_status({"source_url": item["url"], "source_type": source_type}, result, semantic)
        purpose, purpose_reasons = purpose_ok(source_type, item["url"], result.final_url or item["url"], title, str(item.get("anchor") or ""))
        if semantic.get("status") != "strong" or status not in {"ok", "redirected"} or not purpose:
            continue
        final_url = result.final_url or item["url"]
        same_official = is_on_official_domain(final_url, official_domains(vendor))
        if not same_official and not (group == "status_page" and item.get("linked_from_official")):
            continue
        score = {
            "official_page_link": 60,
            "official_legal_page_link": 65,
            "known_official_path": 55,
            "known_status_subdomain": 58,
            "known_trust_subdomain": 58,
            "known_security_subdomain": 58,
            "official_sitemap_locator": 45,
        }.get(str(item.get("method")), 0)
        score += 10 if same_official else 0
        score += len(semantic.get("matched_terms") or [])
        record = {
            "vendor_id": str(vendor["vendor_id"]),
            "group": group,
            "source_type": source_type,
            "source_url": final_url,
            "requested_url": item["url"],
            "discovery_method": item.get("method"),
            "anchor_text": item.get("anchor"),
            "score": score,
            "title": title,
            "http_status": result.http_status,
            "content_type": result.content_type,
            "verification_status": status,
            "semantic_status": semantic.get("status"),
            "matched_terms": semantic.get("matched_terms") or [],
            "raw_sample_sha256": "sha256:" + hashlib.sha256(result.body_sample).hexdigest(),
            "normalized_text_sample_sha256": "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "purpose_reasons": purpose_reasons,
            "official_link_evidence": bool(item.get("linked_from_official")),
        }
        if best is None or (record["score"], -len(record["source_url"])) > (best["score"], -len(best["source_url"])):
            best = record
    return best


def discover_vendor(vendor_id: str, group: str) -> dict[str, Any]:
    vendor = load_yaml(ROOT / "data" / "vendors" / vendor_id / "vendor.yaml")
    checked = candidate_urls(vendor, group)
    verified: list[dict[str, Any]] = []
    for item in checked:
        try:
            result = verify_candidate(vendor, group, item)
        except Exception:
            result = None
        if result:
            verified.append(result)
    verified.sort(key=lambda row: (-int(row["score"]), len(str(row["source_url"])), str(row["source_url"])))
    selected = verified[0] if verified else None
    return {
        "vendor_id": vendor_id,
        "group": group,
        "selected": selected,
        "qualified_candidate_count": len(verified),
        "alternatives": verified[1:10],
        "checked_urls": [str(item["url"]) for item in checked],
        "not_advice": True,
    }


def discover(group: str, shard_index: int, shard_count: int, output: Path) -> None:
    report = build_report(ROOT, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    all_ids = list(report["unresolved_by_group"][group])
    vendor_ids = [vendor_id for index, vendor_id in enumerate(all_ids) if index % shard_count == shard_index]
    workers = min(8, max(1, len(vendor_ids)))
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(discover_vendor, vendor_id, group): vendor_id for vendor_id in vendor_ids}
        for future in as_completed(futures):
            vendor_id = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append({"vendor_id": vendor_id, "group": group, "selected": None, "qualified_candidate_count": 0, "alternatives": [], "checked_urls": [], "error": f"{type(exc).__name__}:{exc}", "not_advice": True})
    rows.sort(key=lambda row: row["vendor_id"])
    payload = {
        "schema_version": "0.1.0",
        "report_type": "expanded_source_completion_discovery_shard",
        "group": group,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "summary": {
            "vendors_checked": len(rows),
            "selected_candidates": sum(row.get("selected") is not None for row in rows),
            "unresolved_vendors": sum(row.get("selected") is None for row in rows),
            "error_count": sum(bool(row.get("error")) for row in rows),
        },
        "vendors": rows,
        "not_advice": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))


def retrieval_method(content_type: str | None) -> str:
    return "pdf_document" if "pdf" in str(content_type or "").lower() else "html_page"


def materialize_candidate(selected: dict[str, Any], observed_at: str) -> dict[str, Any]:
    vendor_id = str(selected["vendor_id"])
    source_type = str(selected["source_type"])
    candidate = {
        "schema_version": "0.1.0",
        "candidate_source_id": candidate_source_id(vendor_id, source_type, str(selected["source_url"])),
        "vendor_id": vendor_id,
        "source_type_candidate": source_type,
        "candidate_url": str(selected["source_url"]),
        "requires_review": True,
        "confidence": "likely",
        "not_advice": True,
        "evidence": {
            "page_title": selected.get("title"),
            "matched_terms": selected.get("matched_terms") or [],
            "final_url": selected.get("source_url"),
            "http_status": 200,
            "content_type": selected.get("content_type"),
            "semantic_status": "strong",
            "verification_status": selected.get("verification_status"),
            "soft_404_detected": False,
        },
    }
    source = source_from_candidate(candidate)
    source["provenance"]["collected_at"] = observed_at
    artifact = artifact_from_source(source)
    base = ROOT / "data" / "vendors" / vendor_id
    source_path = base / "sources" / f"{source['source_id']}.yaml"
    artifact_path = base / "artifacts" / f"{source['source_id']}.yaml"
    change_path = base / "changes" / f"owner-source-completion-{source['source_id']}.yaml"
    write_yaml(source_path, source)
    write_yaml(artifact_path, artifact)
    write_yaml(
        change_path,
        change_event(
            change_id=f"owner-source-completion-{source['source_id']}",
            vendor_id=vendor_id,
            source_id=str(source["source_id"]),
            artifact_id=str(artifact["artifact_id"]),
            change_type="created",
            detected_at=observed_at,
            summary="Owner-led catalog completion added a verified source-type-correct official public source.",
        ),
    )
    (base / "unavailable_sources" / f"{vendor_id}-{source_type.replace('_', '-')}.yaml").unlink(missing_ok=True)
    return {
        "source_id": source["source_id"],
        "vendor_id": vendor_id,
        "source_url": source["source_url"],
        "observed_at": observed_at,
        "observation_id": f"{source['source_id']}-2026-07-14-owner-source-completion",
        "final_url": source["source_url"],
        "http_status": 200,
        "source_health_status": "reachable",
        "change_class": "first_observation",
        "retrieval_method": retrieval_method(selected.get("content_type")),
        "raw_sample_sha256": selected["raw_sample_sha256"],
        "normalized_text_sample_sha256": selected["normalized_text_sample_sha256"],
        "review_signal": {"reason": "first_observation", "required": False},
        "carried_forward": False,
    }


def aggregate(reports_dir: Path, output_dir: Path) -> None:
    rows: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(payload.get("vendors") or [])
    rows.sort(key=lambda row: (str(row.get("group")), str(row.get("vendor_id"))))
    observed_at = now_iso()
    observations: list[dict[str, Any]] = []
    materialized: list[dict[str, Any]] = []
    status_unavailable: list[dict[str, Any]] = []
    next_review = (date(2026, 7, 14) + timedelta(days=90)).isoformat()

    for row in rows:
        selected = row.get("selected")
        vendor_id = str(row["vendor_id"])
        group = str(row["group"])
        if selected:
            observation = materialize_candidate(selected, observed_at)
            observations.append(observation)
            materialized.append({
                "vendor_id": vendor_id,
                "group": group,
                "source_id": observation["source_id"],
                "source_type": selected["source_type"],
                "source_url": selected["source_url"],
                "discovery_method": selected["discovery_method"],
            })
        elif group == "status_page":
            record = unavailable_record(vendor_id, "status_page", list(row.get("checked_urls") or []), observed_at, next_review)
            record["notes"] = "No source-type-correct public status page was identified after bounded official-path, official-link, status-subdomain, and sitemap discovery. This is a search result, not a vendor quality, availability, or risk conclusion."
            path = ROOT / "data" / "vendors" / vendor_id / "unavailable_sources" / f"{record['unavailable_source_id']}.yaml"
            write_yaml(path, record)
            status_unavailable.append({"vendor_id": vendor_id, "path": str(path.relative_to(ROOT))})

    latest_path = ROOT / "maintenance" / "source-observations" / "latest-observations.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    added_ids = {row["source_id"] for row in observations}
    carried = [row for row in latest.get("sources") or [] if row.get("source_id") not in added_ids]
    for row in carried:
        row["carried_forward"] = True
    combined = sorted([*carried, *observations], key=lambda row: (str(row.get("vendor_id") or ""), str(row.get("source_id") or "")))
    latest["generated_at"] = observed_at
    latest["sources"] = combined
    latest["summary"] = {
        "source_count": len(combined),
        "observed_this_run": len(observations),
        "carried_forward": len(carried),
    }
    latest_path.write_text(json.dumps(latest, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    completion = build_report(ROOT, today=date(2026, 7, 14), generated_at=observed_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "expanded-completion-report.json").write_text(json.dumps(completion, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "schema_version": "0.1.0",
        "report_type": "expanded_source_completion_materialization",
        "generated_at": observed_at,
        "materialized_source_count": len(materialized),
        "status_unavailable_record_count": len(status_unavailable),
        "materialized": materialized,
        "status_unavailable": status_unavailable,
        "completion_summary": completion["summary"],
        "mandatory_residuals": {
            group: completion["unresolved_by_group"][group]
            for group in ("privacy_notice", "terms_of_service", "security_assurance")
        },
        "not_advice": True,
    }
    (output_dir / "expanded-completion-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "materialized_source_count": len(materialized),
        "status_unavailable_record_count": len(status_unavailable),
        "completion_summary": completion["summary"],
        "mandatory_residual_counts": {key: len(value) for key, value in summary["mandatory_residuals"].items()},
    }, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    discovery = sub.add_parser("discover")
    discovery.add_argument("--group", required=True, choices=sorted(GROUP_TYPES))
    discovery.add_argument("--shard-index", type=int, required=True)
    discovery.add_argument("--shard-count", type=int, required=True)
    discovery.add_argument("--output", type=Path, required=True)
    combine = sub.add_parser("aggregate")
    combine.add_argument("--reports-dir", type=Path, required=True)
    combine.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "discover":
        discover(args.group, args.shard_index, args.shard_count, args.output)
    else:
        aggregate(args.reports_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
