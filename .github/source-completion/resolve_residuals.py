from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
import yaml

ROOT = Path.cwd()
NOW = datetime.now(UTC).replace(microsecond=0)
COLLECTED_AT = NOW.isoformat().replace("+00:00", "Z")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OpenVA/1.0; +https://github.com/thedanieltan/open-vendor-assurance)",
    "Accept": "text/html,application/xhtml+xml",
}

RESOLUTIONS = [
    {
        "vendor_id": "emarsys",
        "source_id": "emarsys-status-page",
        "source_type": "status_page",
        "url": "https://trust.emarsys.com/",
        "title": "SAP Engagement Cloud Status",
        "allowed_domains": {"emarsys.com"},
        "keywords": {"status", "statushub"},
    },
    {
        "vendor_id": "hetzner",
        "source_id": "hetzner-status-page",
        "source_type": "status_page",
        "url": "https://status.hetzner.com/",
        "title": "Hetzner Status",
        "allowed_domains": {"hetzner.com"},
        "keywords": {"hetzner status", "status reports", "affected systems"},
    },
    {
        "vendor_id": "insider",
        "source_id": "insider-terms-of-service",
        "source_type": "terms_of_service",
        "url": "https://insiderone.com/terms-of-use/",
        "title": "Insider One Terms of Use",
        "allowed_domains": {"insiderone.com", "useinsider.com"},
        "keywords": {"terms of use", "website terms", "legal"},
    },
    {
        "vendor_id": "insider",
        "source_id": "insider-security-page",
        "source_type": "security_page",
        "url": "https://insiderone.com/security/",
        "title": "Insider One Security Center",
        "allowed_domains": {"insiderone.com", "useinsider.com"},
        "keywords": {"security", "security center", "compliance"},
    },
]


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def verify(url: str, allowed_domains: set[str], keywords: set[str]) -> tuple[str, str]:
    response = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    parsed = urlsplit(response.url)
    host = (parsed.hostname or "").lower().strip(".")
    if response.status_code != 200:
        raise RuntimeError(f"{url}: expected HTTP 200, got {response.status_code}")
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"{url}: final URL is not HTTPS: {response.url}")
    if not any(host == domain or host.endswith("." + domain) for domain in allowed_domains):
        raise RuntimeError(f"{url}: final host outside approved authority: {host}")
    text = " ".join(response.text.split())
    lowered = text.lower()
    if not any(keyword in lowered for keyword in keywords):
        raise RuntimeError(f"{url}: expected page-purpose terms not found")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
    title = " ".join(title_match.group(1).split())[:240] if title_match else ""
    return response.url, title


def artifact_record(vendor_id: str, source_id: str, source_type: str, url: str, product: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "artifact_id": source_id,
        "vendor_id": vendor_id,
        "source_id": source_id,
        "artifact_type": source_type,
        "canonical_url": url,
        "source_language": "en",
        "region_scope": ["global"],
        "product_scope": [product],
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "effective_or_published_at": None,
        "hashes": {
            "raw_sha256": "sha256:TBD",
            "normalized_text_sha256": "sha256:TBD",
            "hash_method": "metadata_plus_hash_only",
        },
        "storage": {
            "raw_document_stored": False,
            "extracted_text_stored": False,
            "screenshot_stored": False,
        },
        "not_advice": True,
    }


def source_record(vendor_id: str, source_id: str, source_type: str, url: str, title: str) -> dict:
    summary = f"Public {title} metadata reference."
    return {
        "schema_version": "0.1.0",
        "source_id": source_id,
        "vendor_id": vendor_id,
        "source_type": source_type,
        "source_authority_class": "vendor_published",
        "title_native": title,
        "title_en": title,
        "summary_native": summary,
        "summary_en": summary,
        "source_url": url,
        "source_language": "en",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "vendor",
            "collected_at": COLLECTED_AT,
            "observer": "agent",
            "confidence": "high",
        },
        "not_advice": True,
    }


def change_record(vendor_id: str, source_id: str, change_type: str, summary: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "change_id": f"owner-source-completion-{source_id}-{change_type}",
        "vendor_id": vendor_id,
        "source_id": source_id,
        "artifact_id": source_id,
        "change_type": change_type,
        "detected_at": COLLECTED_AT,
        "from_hash": "sha256:TBD",
        "to_hash": "sha256:TBD",
        "catalog_change_significance": "unknown",
        "materiality": "unknown",
        "review_state": "proposed",
        "summary": summary,
        "not_advice": True,
    }


def add_source(item: dict) -> None:
    vendor_id = item["vendor_id"]
    vendor_dir = ROOT / "data/vendors" / vendor_id
    vendor = load_yaml(vendor_dir / "vendor.yaml")
    final_url, fetched_title = verify(item["url"], item["allowed_domains"], item["keywords"])
    title = item["title"] or fetched_title
    source_id = item["source_id"]
    source_type = item["source_type"]
    source_path = vendor_dir / "sources" / f"{source_id}.yaml"
    existed = source_path.exists()
    write_yaml(source_path, source_record(vendor_id, source_id, source_type, final_url, title))
    write_yaml(
        vendor_dir / "artifacts" / f"{source_id}.yaml",
        artifact_record(vendor_id, source_id, source_type, final_url, str(vendor.get("display_name") or vendor_id)),
    )
    event_type = "updated" if existed else "created"
    write_yaml(
        vendor_dir / "changes" / f"owner-source-completion-{source_id}-{event_type}.yaml",
        change_record(
            vendor_id,
            source_id,
            event_type,
            f"Owner-led catalog maintenance {'updated' if existed else 'added'} a verified public {source_type.replace('_', ' ')} reference.",
        ),
    )
    unavailable = vendor_dir / "unavailable_sources" / f"{vendor_id}-{source_type.replace('_', '-')}.yaml"
    unavailable.unlink(missing_ok=True)
    print(f"resolved {vendor_id} {source_type}: {final_url}")


def add_parent_authority(vendor_id: str, domain: str, note: str) -> None:
    vendor_path = ROOT / "data/vendors" / vendor_id / "vendor.yaml"
    vendor = load_yaml(vendor_path)
    domains = [str(value) for value in vendor.get("official_domains") or [] if value]
    if domain not in domains:
        domains.append(domain)
    vendor["official_domains"] = domains
    current_note = str(vendor.get("notes") or "").strip()
    if note not in current_note:
        vendor["notes"] = (current_note + " " + note).strip()
    write_yaml(vendor_path, vendor)
    print(f"registered parent authority for {vendor_id}: {domain}")


def correct_insider_identity() -> None:
    vendor_dir = ROOT / "data/vendors/insider"
    vendor_path = vendor_dir / "vendor.yaml"
    vendor = load_yaml(vendor_path)
    vendor["display_name"] = "Insider One"
    vendor.pop("headquarters_country", None)
    vendor["official_domains"] = ["insiderone.com", "useinsider.com"]
    vendor["public_entrypoints"] = ["https://insiderone.com"]
    vendor["notes"] = (
        "Canonical identity corrected to the Insider One customer-engagement platform. "
        "The former useinsider.com authority redirects to insiderone.com. Metadata-only; not advisory."
    )
    write_yaml(vendor_path, vendor)

    privacy_url, _ = verify(
        "https://insiderone.com/privacy-policy/",
        {"insiderone.com", "useinsider.com"},
        {"privacy policy", "personal data", "personal information"},
    )
    source_id = "insider-privacy-notice"
    source_path = vendor_dir / "sources" / f"{source_id}.yaml"
    source = load_yaml(source_path)
    source.update(
        {
            "source_url": privacy_url,
            "title_native": "Insider One Privacy Policy",
            "title_en": "Insider One Privacy Policy",
            "summary_native": "Public Insider One privacy policy metadata reference.",
            "summary_en": "Public Insider One privacy policy metadata reference.",
            "provenance": {
                "publisher": "vendor",
                "collected_at": COLLECTED_AT,
                "observer": "agent",
                "confidence": "high",
            },
        }
    )
    write_yaml(source_path, source)
    artifact_path = vendor_dir / "artifacts" / f"{source_id}.yaml"
    artifact = load_yaml(artifact_path)
    artifact["canonical_url"] = privacy_url
    artifact["product_scope"] = ["Insider One"]
    artifact["region_scope"] = ["global"]
    write_yaml(artifact_path, artifact)
    write_yaml(
        vendor_dir / "changes" / "owner-source-completion-insider-privacy-notice-updated.yaml",
        change_record(
            "insider",
            source_id,
            "updated",
            "Corrected the canonical privacy authority from the unrelated insider.com publisher domain to the Insider One customer-engagement platform.",
        ),
    )
    print(f"corrected insider identity and privacy authority: {privacy_url}")


def main() -> int:
    add_parent_authority(
        "microsoft-azure",
        "microsoft.com",
        "Microsoft's corporate privacy domain is an official publisher authority for the Azure product surface.",
    )
    add_parent_authority(
        "netsuite",
        "oracle.com",
        "Oracle's corporate privacy domain is an official parent-company authority for the NetSuite product surface.",
    )
    correct_insider_identity()
    for item in RESOLUTIONS:
        add_source(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
