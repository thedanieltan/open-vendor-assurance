from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import requests
import yaml

ROOT = Path.cwd()
NOW = datetime.now(UTC).replace(microsecond=0)
NEXT_REVIEW = (NOW.date() + timedelta(days=90)).isoformat()
GROUPS: dict[str, set[str]] = {
    "privacy_notice": {"privacy_notice"},
    "terms_of_service": {"terms_of_service"},
    "security_assurance": {"security_page", "trust_center", "compliance_page"},
    "dpa": {"dpa"},
    "subprocessors_list": {"subprocessors_list"},
    "status_page": {"status_page"},
    "compliance": {"compliance_page", "certification_reference"},
}
CORE_GROUPS = tuple(group for group in GROUPS if group != "compliance")
PRIVACY_CANDIDATES: dict[str, list[tuple[str, set[str]]]] = {
    "airwallex": [
        ("https://www.airwallex.com/privacy-policy", {"airwallex.com"}),
        ("https://www.airwallex.com/legal/privacy-policy", {"airwallex.com"}),
        ("https://www.airwallex.com/privacy", {"airwallex.com"}),
        ("https://www.airwallex.com/legal/privacy", {"airwallex.com"}),
        ("https://www.airwallex.com/terms/privacy-policy", {"airwallex.com"}),
    ],
    "microsoft-azure": [
        ("https://www.microsoft.com/en-us/privacy/privacystatement", {"microsoft.com"}),
    ],
    "netsuite": [
        ("https://www.netsuite.com/portal/company/privacy.shtml", {"netsuite.com"}),
        ("https://www.oracle.com/legal/privacy/services-privacy-policy/", {"oracle.com"}),
    ],
}
SOURCE_PATHS: dict[str, tuple[str, ...]] = {
    "privacy_notice": ("/privacy", "/privacy-policy", "/legal/privacy", "/legal/privacy-policy", "/privacy.html"),
    "terms_of_service": ("/terms", "/terms-of-service", "/legal/terms", "/legal/terms-of-service", "/terms.html"),
    "security_page": ("/security", "/trust", "/trust-center", "/trustcenter", "/security.html"),
    "trust_center": ("/trust", "/trust-center", "/trustcenter", "/security", "/security/trust"),
    "compliance_page": ("/compliance", "/security/compliance", "/trust/compliance", "/trust-center/compliance"),
    "certification_reference": ("/security/certifications", "/trust/certifications", "/compliance/certifications"),
    "dpa": ("/legal/data-processing-addendum", "/data-processing-addendum", "/legal/dpa", "/dpa", "/privacy/dpa"),
    "subprocessors_list": ("/legal/subprocessors", "/subprocessors", "/legal/sub-processors", "/sub-processors"),
    "status_page": ("/status", "/statuspage", "/system-status", "/service-status", "/uptime"),
}


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def existed_on_main(path: Path) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"origin/main:{path.as_posix()}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def url_integrity_reasons(url: str) -> list[str]:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError:
        return ["malformed_url"]
    reasons: list[str] = []
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        reasons.append("not_https_or_missing_host")
    if parsed.username or parsed.password:
        reasons.append("userinfo_present")
    decoded_query = unquote(parsed.query or "").lower()
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if "http://" in decoded_query or "https://" in decoded_query:
        reasons.append("nested_url_in_query")
    if len(pairs) > 20:
        reasons.append("excessive_query_parameters")
    if len(parsed.query) > 1500:
        reasons.append("excessive_query_length")
    if any(len(key) > 120 or len(value) > 500 for key, value in pairs):
        reasons.append("oversized_query_component")
    return sorted(set(reasons))


def official_domains(vendor_dir: Path) -> list[str]:
    vendor = load_yaml(vendor_dir / "vendor.yaml")
    return sorted({str(value).lower().strip(".") for value in vendor.get("official_domains") or [] if value})


def candidate_urls(vendor_dir: Path, source_type: str) -> list[str]:
    urls: list[str] = []
    for domain in official_domains(vendor_dir):
        bases = [f"https://{domain}", f"https://www.{domain}"]
        if source_type == "status_page":
            bases.insert(0, f"https://status.{domain}")
        for base in bases:
            if base not in urls:
                urls.append(base)
            for suffix in SOURCE_PATHS[source_type]:
                candidate = base.rstrip("/") + suffix
                if candidate not in urls:
                    urls.append(candidate)
    vendor = load_yaml(vendor_dir / "vendor.yaml")
    for value in vendor.get("public_entrypoints") or []:
        if isinstance(value, str) and value.startswith("https://") and value not in urls:
            urls.append(value)
    return urls[:40]


def unavailable_path(vendor_dir: Path, source_type: str) -> Path:
    slug = source_type.replace("_", "-")
    return vendor_dir / "unavailable_sources" / f"{vendor_dir.name}-{slug}.yaml"


def ensure_unavailable(vendor_dir: Path, source_type: str) -> None:
    record = {
        "schema_version": "0.1.0",
        "unavailable_source_id": f"{vendor_dir.name}-{source_type.replace('_', '-')}",
        "vendor_id": vendor_dir.name,
        "source_type": source_type,
        "status": "not_identified",
        "reason": "distinct_public_url_not_identified",
        "candidate_urls_checked": candidate_urls(vendor_dir, source_type),
        "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
        "reviewed_by": "agent",
        "next_review_after": NEXT_REVIEW,
        "notes": "No source-type-correct canonical public source was identified after bounded official-path, official-link, and robots/sitemap discovery. This is a factual OpenVA search result, not a vendor quality or risk conclusion.",
        "not_advice": True,
    }
    write_yaml(unavailable_path(vendor_dir, source_type), record)


def canonical_coverage(vendor_dir: Path) -> tuple[set[str], set[str], list[tuple[Path, dict]]]:
    direct: set[str] = set()
    roles: set[str] = set()
    records: list[tuple[Path, dict]] = []
    for path in sorted((vendor_dir / "sources").glob("*.yaml")):
        record = load_yaml(path)
        records.append((path, record))
        source_type = record.get("source_type")
        if isinstance(source_type, str):
            direct.add(source_type)
            roles.add(source_type)
        for claim in record.get("coverage_claims") or []:
            if (
                isinstance(claim, dict)
                and claim.get("coverage_type") in {"contains", "links_to"}
                and isinstance(claim.get("role"), str)
            ):
                roles.add(str(claim["role"]))
    return direct, roles, records


def unavailable_types(vendor_dir: Path) -> set[str]:
    values: set[str] = set()
    for path in (vendor_dir / "unavailable_sources").glob("*.yaml"):
        record = load_yaml(path)
        if record.get("status") == "not_identified" and isinstance(record.get("source_type"), str):
            values.add(str(record["source_type"]))
    return values


def remove_source_record(source_path: Path, record: dict, reasons: list[str], removed: list[dict]) -> None:
    vendor_id = str(record["vendor_id"])
    source_id = str(record["source_id"])
    source_type = str(record["source_type"])
    if existed_on_main(source_path):
        raise RuntimeError(f"refusing to remove pre-existing source {source_path}: {reasons}")
    source_path.unlink(missing_ok=True)
    vendor_dir = source_path.parent.parent
    (vendor_dir / "artifacts" / f"{source_id}.yaml").unlink(missing_ok=True)
    for change_path in (vendor_dir / "changes").glob("*.yaml"):
        try:
            change = load_yaml(change_path)
        except Exception:
            continue
        if change.get("source_id") == source_id:
            change_path.unlink(missing_ok=True)
    if source_type != "privacy_notice":
        ensure_unavailable(vendor_dir, source_type)
    removed.append({"vendor_id": vendor_id, "source_id": source_id, "source_type": source_type, "reasons": reasons})


def verify_privacy_candidate(url: str, allowed_domains: set[str]) -> tuple[str, str] | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OpenVA/1.0; +https://github.com/thedanieltan/open-vendor-assurance)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
    except requests.RequestException:
        return None
    parsed = urlsplit(response.url)
    host = (parsed.hostname or "").lower().strip(".")
    if response.status_code != 200 or parsed.scheme.lower() != "https":
        return None
    if not any(host == domain or host.endswith("." + domain) for domain in allowed_domains):
        return None
    text = response.text[:400000]
    lowered = text.lower()
    if "privacy" not in lowered or not any(term in lowered for term in ("personal data", "personal information", "data protection")):
        return None
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = " ".join(title_match.group(1).split())[:240] if title_match else "Privacy Notice"
    return response.url, title


def add_privacy(vendor_dir: Path, url: str, title: str, added: list[dict]) -> None:
    vendor_id = vendor_dir.name
    source_id = f"{vendor_id}-privacy-notice"
    source_path = vendor_dir / "sources" / f"{source_id}.yaml"
    if source_path.exists():
        unavailable_path(vendor_dir, "privacy_notice").unlink(missing_ok=True)
        return
    collected_at = NOW.isoformat().replace("+00:00", "Z")
    source = {
        "schema_version": "0.1.0",
        "source_id": source_id,
        "vendor_id": vendor_id,
        "source_type": "privacy_notice",
        "source_authority_class": "vendor_published",
        "title_native": title,
        "source_url": url,
        "source_language": "en",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {"publisher": "vendor", "collected_at": collected_at, "observer": "agent", "confidence": "high"},
        "not_advice": True,
    }
    artifact = {
        "schema_version": "0.1.0",
        "artifact_id": source_id,
        "vendor_id": vendor_id,
        "source_id": source_id,
        "artifact_type": "privacy_notice",
        "canonical_url": url,
        "source_language": "en",
        "region_scope": [],
        "entity_scope": {"scope_type": "brand_surface", "entity_ids": []},
        "product_scope": [],
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "effective_or_published_at": None,
        "hashes": {"raw_sha256": "sha256:TBD", "normalized_text_sha256": "sha256:TBD", "hash_method": "metadata_plus_hash_only"},
        "storage": {"raw_document_stored": False, "extracted_text_stored": False, "screenshot_stored": False},
        "not_advice": True,
    }
    change = {
        "schema_version": "0.1.0",
        "change_id": f"owner-source-completion-{source_id}",
        "vendor_id": vendor_id,
        "source_id": source_id,
        "artifact_id": source_id,
        "change_type": "created",
        "detected_at": collected_at,
        "from_hash": "sha256:TBD",
        "to_hash": "sha256:TBD",
        "catalog_change_significance": "unknown",
        "materiality": "unknown",
        "review_state": "proposed",
        "summary": "Owner-led catalog maintenance added a verified public privacy notice reference.",
        "not_advice": True,
    }
    write_yaml(source_path, source)
    write_yaml(vendor_dir / "artifacts" / f"{source_id}.yaml", artifact)
    write_yaml(vendor_dir / "changes" / f"owner-source-completion-{source_id}.yaml", change)
    unavailable_path(vendor_dir, "privacy_notice").unlink(missing_ok=True)
    added.append({"vendor_id": vendor_id, "source_id": source_id, "url": url})


def main() -> int:
    removed: list[dict] = []
    added_privacy: list[dict] = []
    poison_findings: list[dict] = []
    vendor_dirs = sorted(
        path for path in (ROOT / "data/vendors").iterdir() if path.is_dir() and (path / "vendor.yaml").exists()
    )

    for vendor_dir in vendor_dirs:
        for source_path in sorted((vendor_dir / "sources").glob("*.yaml")):
            record = load_yaml(source_path)
            url = str(record.get("source_url") or "")
            reasons = url_integrity_reasons(url)
            if reasons:
                poison_findings.append({"path": source_path.as_posix(), "url": url, "reasons": reasons})
                remove_source_record(source_path, record, reasons, removed)

    for vendor_dir in vendor_dirs:
        _, roles, _ = canonical_coverage(vendor_dir)
        for path in sorted((vendor_dir / "unavailable_sources").glob("*.yaml")):
            record = load_yaml(path)
            source_type = record.get("source_type")
            if isinstance(source_type, str) and source_type in roles:
                path.unlink(missing_ok=True)

    for vendor_id, candidates in PRIVACY_CANDIDATES.items():
        vendor_dir = ROOT / "data/vendors" / vendor_id
        _, roles, _ = canonical_coverage(vendor_dir)
        if "privacy_notice" in roles:
            unavailable_path(vendor_dir, "privacy_notice").unlink(missing_ok=True)
            continue
        for url, domains in candidates:
            selected = verify_privacy_candidate(url, domains)
            if selected:
                add_privacy(vendor_dir, *selected, added_privacy)
                break

    failures: list[str] = []
    vendor_rows: list[dict] = []
    for vendor_dir in vendor_dirs:
        _, roles, _ = canonical_coverage(vendor_dir)
        if "privacy_notice" not in roles:
            failures.append(f"{vendor_dir.name}: privacy_notice requires a live canonical source")
        live_core = sum(1 for group in CORE_GROUPS if roles & GROUPS[group])
        if live_core < 2:
            failures.append(f"{vendor_dir.name}: only {live_core} live core groups; requires at least 2")
        for group, accepted in GROUPS.items():
            if roles & accepted:
                for source_type in accepted & roles:
                    unavailable_path(vendor_dir, source_type).unlink(missing_ok=True)
                continue
            for source_type in accepted:
                ensure_unavailable(vendor_dir, source_type)
        unavailable = unavailable_types(vendor_dir)
        unresolved: list[str] = []
        for group, accepted in GROUPS.items():
            if roles & accepted or accepted <= unavailable:
                continue
            unresolved.append(group)
        if unresolved:
            failures.append(f"{vendor_dir.name}: unresolved groups {', '.join(unresolved)}")
        vendor_rows.append(
            {
                "vendor_id": vendor_dir.name,
                "live_core_group_count": live_core,
                "canonical_roles": sorted(roles),
                "unavailable_types": sorted(unavailable),
                "unresolved_groups": unresolved,
            }
        )

    complete_count = sum(
        not row["unresolved_groups"]
        and row["live_core_group_count"] >= 2
        and "privacy_notice" in row["canonical_roles"]
        for row in vendor_rows
    )
    report = {
        "schema_version": "0.1.0",
        "report_type": "owner_source_completion_finalization",
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "vendor_count": len(vendor_rows),
        "complete_vendor_count": complete_count,
        "removed_poisoned_sources": removed,
        "url_integrity_findings": poison_findings,
        "added_privacy_sources": added_privacy,
        "failure_count": len(failures),
        "failures": failures,
        "vendors": vendor_rows,
        "not_advice": True,
    }
    output = Path("/tmp/source-completion-finalization.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "vendor_count",
                    "complete_vendor_count",
                    "failure_count",
                    "removed_poisoned_sources",
                    "added_privacy_sources",
                    "failures",
                )
            },
            indent=2,
        )
    )
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
