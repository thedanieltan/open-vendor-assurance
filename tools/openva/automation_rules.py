from __future__ import annotations

import argparse
import json
import re
import socket
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yaml

from tools.openva.indexes import check_generated_current, records_for
from tools.openva.pack import verify_pack_integrity
from tools.openva.paths import normalize_repo_path, relative_repo_path
from tools.openva.source_verification import (
    FetchResult,
    safe_fetcher_for_domains,
    safe_fetcher_for_source_path,
    verify_source,
)
from tools.openva.validate import (
    SCHEMA_MAP,
    load_json,
    load_yaml,
    validate_access_rights,
    validate_adapter_record,
    validate_cross_references,
    validate_quality_gates,
    validate_schema,
)

ROOT = Path(__file__).resolve().parents[2]
COMMENT_MARKER_PREFIX = "<!-- openva-weighted-review:"

REGULATED_CATEGORIES = {"financial_services", "healthcare", "government"}
PUBLIC_AUTHORITY_CLASSES = {"public_registry", "public_authority"}
VENDOR_PROMOTION_AUTHORITY_CLASSES = {"public_registry", "public_authority", "vendor_published"}
SOURCE_DOWNLOAD_CONTENT_TYPES = ("application/pdf", "application/octet-stream", "application/zip")
BOT_HEADER_NAMES = ("cf-ray", "x-sucuri-id", "x-akamai", "x-distil")
AUTH_STATUSES = {401, 403, 407}
BLOCKING_SOURCE_STATUSES = {"bot_protected", "gated_or_login_required", "unreachable", "forbidden_unknown"}
ADVISORY_CONTEXT_KEYS = {"summary_en", "summary_native", "notes", "description"}
ID_OR_URL_SUFFIXES = ("_id", "_ids", "_url", "_urls")


@dataclass
class ValidatorResult:
    validator: str
    score: int
    warnings: list[str]
    escalations: list[str]
    failures: list[str]
    changed_files: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "validator": self.validator,
            "score": self.score,
            "max_score": 1,
            "warnings": self.warnings,
            "escalations": self.escalations,
            "failures": self.failures,
            "changed_files": self.changed_files,
            "details": self.details,
            "advisory_only": True,
        }


def result(
    validator: str,
    *,
    warnings: list[str] | None = None,
    escalations: list[str] | None = None,
    failures: list[str] | None = None,
    changed_files: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> ValidatorResult:
    warnings = warnings or []
    escalations = escalations or []
    failures = failures or []
    return ValidatorResult(
        validator=validator,
        score=0 if failures or escalations else 1,
        warnings=warnings,
        escalations=escalations,
        failures=failures,
        changed_files=changed_files or [],
        details=details or {},
    )


def normalize_changed_files(paths: list[str] | None) -> list[str]:
    if not paths:
        return []
    return sorted({normalize_repo_path(path) for path in paths if normalize_repo_path(path)})


def changed_files_from_args(args: argparse.Namespace) -> list[str]:
    paths: list[str] = []
    if getattr(args, "changed_file", None):
        paths.extend(args.changed_file)
    if getattr(args, "changed_files", None):
        file_path = Path(args.changed_files)
        if file_path.exists():
            paths.extend(line.strip() for line in file_path.read_text(encoding="utf-8").splitlines())
    return normalize_changed_files(paths)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{relative_repo_path(path, ROOT)}: expected YAML mapping")
    return data


def load_json_mapping(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{relative_repo_path(path, ROOT)}: expected JSON object")
    return data


def load_mapping(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return load_json_mapping(path)
    return load_yaml_mapping(path)


def record_kind_for_path(path: str) -> str | None:
    normalized = normalize_repo_path(path)
    if normalized.endswith("/vendor.yaml"):
        return "vendor"
    parts = normalized.split("/")
    mapping = {
        "sources": "source",
        "artifacts": "artifact",
        "observations": "observation",
        "changes": "change",
        "legal_entities": "legal_entity",
        "entity_mentions": "entity_mention",
        "candidate_sources": "candidate_source",
        "unavailable_sources": "unavailable_source",
    }
    for folder, kind in mapping.items():
        if folder in parts and normalized.endswith((".yaml", ".yml")):
            return kind
    if normalized == "openva-pack.json":
        return "pack"
    return None


def existing_file_paths(changed_files: list[str]) -> list[Path]:
    return [ROOT / path for path in changed_files if (ROOT / path).is_file()]


def schema_properties(kind: str) -> set[str]:
    schema_path = SCHEMA_MAP.get(kind)
    if not schema_path:
        return set()
    schema = load_json(schema_path)
    return set((schema.get("properties") or {}).keys())


def check_unknown_fields(changed_files: list[str]) -> list[str]:
    schema_changed = any(path.startswith("schemas/") for path in changed_files)
    if schema_changed:
        return []
    failures: list[str] = []
    for rel_path in changed_files:
        kind = record_kind_for_path(rel_path)
        if not kind or kind == "pack":
            continue
        path = ROOT / rel_path
        if not path.exists():
            continue
        try:
            record = load_mapping(path)
        except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
            failures.append(f"{rel_path}: cannot inspect fields: {exc}")
            continue
        unknown = sorted(set(record.keys()) - schema_properties(kind))
        for field in unknown:
            if field == "status" and kind == "vendor":
                continue
            failures.append(f"{rel_path}: field {field} is not defined in {SCHEMA_MAP[kind].relative_to(ROOT)}")
    return failures


def adapter_record_paths(changed_files: list[str]) -> list[Path]:
    paths: list[Path] = []
    for rel_path in changed_files:
        normalized = normalize_repo_path(rel_path)
        if not normalized.endswith((".json", ".yaml", ".yml")):
            continue
        if "adapter" not in normalized and "normalized-record" not in normalized:
            continue
        path = ROOT / normalized
        if path.exists() and path.is_file():
            paths.append(path)
    return paths


def validate_changed_adapter_records(changed_files: list[str]) -> tuple[list[str], int]:
    failures: list[str] = []
    checked = 0
    for path in adapter_record_paths(changed_files):
        try:
            payload = load_mapping(path)
        except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
            failures.append(f"{relative_repo_path(path, ROOT)}: adapter record parse failed: {exc}")
            continue
        if {"record_class", "canonical", "advisory_boundary"} <= set(payload.keys()):
            checked += 1
            failures.extend(validate_adapter_record(payload, label=relative_repo_path(path, ROOT)))

    # Explicitly exercise the adapter validation helper even when a PR has no adapter output files.
    checked += 1
    failures.extend(
        validate_adapter_record(
            {"record_class": "canonical", "canonical": True, "advisory_boundary": "non_advisory"},
            label="adapter-normalized-record-smoke",
        )
    )
    return failures, checked


def schema_conformance(changed_files: list[str]) -> ValidatorResult:
    failures: list[str] = []
    for kind in SCHEMA_MAP:
        failures.extend(validate_schema(kind))
    failures.extend(validate_cross_references())
    failures.extend(validate_quality_gates())
    failures.extend(verify_pack_integrity())
    failures.extend(check_generated_current())
    failures.extend(check_unknown_fields(changed_files))
    adapter_failures, adapter_records_checked = validate_changed_adapter_records(changed_files)
    failures.extend(adapter_failures)

    return result(
        "schema-conformance-agent",
        failures=failures,
        changed_files=changed_files,
        details={"adapter_records_checked": adapter_records_checked},
    )


def load_domain_blocklist() -> dict[str, str]:
    path = ROOT / "config/domain-blocklist.yaml"
    if not path.exists():
        return {}
    data = load_yaml(path) or {}
    blocked: dict[str, str] = {}
    for domain_class, domains in (data.get("blocked_domain_classes") or {}).items():
        for domain in domains or []:
            blocked[str(domain).lower().removeprefix("www.")] = str(domain_class)
    return blocked


def host_matches_domain(host: str, domain: str) -> bool:
    host = host.lower().removeprefix("www.")
    domain = domain.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def blocked_domain_reason(url_or_domain: str, blocklist: dict[str, str]) -> str | None:
    host = urlparse(url_or_domain).hostname or url_or_domain
    host = host.lower().strip().rstrip(".").removeprefix("www.")
    for domain, domain_class in blocklist.items():
        if host_matches_domain(host, domain):
            return domain_class
    return None


def changed_source_like_records(changed_files: list[str]) -> list[tuple[str, dict[str, Any], Path]]:
    records: list[tuple[str, dict[str, Any], Path]] = []
    for rel_path in changed_files:
        kind = record_kind_for_path(rel_path)
        if kind not in {"source", "artifact"}:
            continue
        path = ROOT / rel_path
        if not path.exists():
            continue
        try:
            item = load_mapping(path)
        except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError):
            continue
        records.append((kind, item, path))
    return records


def is_document_download(content_type: str | None) -> bool:
    if not content_type:
        return False
    lower = content_type.lower()
    return any(content_type_hint in lower for content_type_hint in SOURCE_DOWNLOAD_CONTENT_TYPES)


def retry_fetch(url: str, fetcher: Callable[[str], FetchResult], *, retry_429: bool) -> FetchResult:
    first = fetcher(url)
    if retry_429 and first.http_status == 429:
        time.sleep(60)
        return fetcher(url)
    return first


def source_accessibility(
    changed_files: list[str],
    *,
    fetcher: Callable[[str], FetchResult] | None = None,
    retry_429: bool = False,
) -> ValidatorResult:
    warnings: list[str] = []
    escalations: list[str] = []
    checked = 0
    blocklist = load_domain_blocklist()

    for kind, item, path in changed_source_like_records(changed_files):
        rel_path = relative_repo_path(path, ROOT)
        url_field = "source_url" if kind == "source" else "canonical_url"
        url = str(item.get(url_field) or "")
        if not url:
            escalations.append(f"{rel_path}: missing {url_field}")
            continue

        blocked = blocked_domain_reason(url, blocklist)
        if blocked:
            escalations.append(f"{rel_path}: {url_field} host is blocklisted as {blocked}")
            continue

        checked += 1
        source_for_check = {
            "source_url": url,
            "source_type": item.get("source_type") or item.get("artifact_type"),
        }
        # A PR-controlled source_url is fetched over the SSRF-safe boundary bound
        # to the changed record's own vendor authority (fail-closed when it cannot
        # be resolved); an explicitly injected fetcher (tests) is honoured verbatim.
        record_fetcher = fetcher if fetcher is not None else safe_fetcher_for_source_path(path, ROOT)
        fetched = retry_fetch(url, record_fetcher, retry_429=retry_429)
        status = verify_source(source_for_check, path, fetcher=lambda _url: fetched)["verification_status"]

        if fetched.http_status == 429:
            warnings.append(f"{rel_path}: {url_field} returned 429 after retry; advisory warning")
            continue
        if len(redirect_hops(url, fetched.final_url)) > 3:
            escalations.append(f"{rel_path}: {url_field} redirects more than 3 hops")
        if fetched.http_status in AUTH_STATUSES:
            escalations.append(f"{rel_path}: {url_field} returned gated status {fetched.http_status}")
        if status in BLOCKING_SOURCE_STATUSES:
            escalations.append(f"{rel_path}: {url_field} requires review: {status}")
        if is_document_download(fetched.content_type):
            escalations.append(f"{rel_path}: {url_field} content-type suggests document download: {fetched.content_type}")
        if fetched.http_status and 200 <= fetched.http_status < 400 and status in {"ok", "redirected"}:
            continue
        if fetched.http_status is None:
            escalations.append(f"{rel_path}: {url_field} unreachable: {fetched.error or 'unknown'}")

    return result(
        "source-accessibility-agent",
        warnings=warnings,
        escalations=dedupe(escalations),
        changed_files=changed_files,
        details={"urls_checked": checked, "soft_network": True},
    )


def redirect_hops(requested_url: str, final_url: str | None) -> list[str]:
    if not final_url or requested_url.rstrip("/") == final_url.rstrip("/"):
        return []
    return [requested_url, final_url]


def load_prohibited_config() -> dict[str, Any]:
    path = ROOT / "config/prohibited-claims.yaml"
    return load_yaml(path) or {}


def term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9-])" + re.escape(term.lower()) + r"(?![a-z0-9-])")


def prohibited_terms() -> list[str]:
    config = load_prohibited_config()
    return [str(term).lower() for term in config.get("prohibited_terms", [])]


def blocked_field_name_terms() -> list[str]:
    config = load_prohibited_config()
    return [str(term).lower() for term in config.get("blocked_field_name_terms", [])]


def implication_phrases() -> list[str]:
    config = load_prohibited_config()
    return [str(term).lower() for term in config.get("implication_phrases", [])]


def is_exempt_field(field_path: str) -> bool:
    leaf = field_path.split(".")[-1]
    return leaf.endswith(ID_OR_URL_SUFFIXES) or leaf in {"source_url", "canonical_url", "manifest_path"}


def is_policy_negation_context(text: str) -> bool:
    lower = text.lower()
    negators = (
        "must not",
        "does not",
        "do not",
        "not ",
        "non-advisory",
        "prohibited",
        "example of what not to write",
        "invalid",
        "negative fixture",
    )
    return any(negator in lower for negator in negators)


def is_doc_path(rel_path: str) -> bool:
    return rel_path.startswith("docs/") or rel_path in {"DISCLAIMER.md", "GOVERNANCE.md", "SECURITY.md"}


def scan_text_for_terms(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in prohibited_terms() if term_pattern(term).search(lower)]


def scan_structured_value(
    value: Any,
    *,
    rel_path: str,
    field_path: str,
    findings: list[str],
    warnings: list[str],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{field_path}.{key}" if field_path else str(key)
            if should_scan_field_name(rel_path) and any(term in str(key).lower() for term in blocked_field_name_terms()):
                findings.append(f"{rel_path}: field name {key_path} contains prohibited advisory wording")
            scan_structured_value(child, rel_path=rel_path, field_path=key_path, findings=findings, warnings=warnings)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            scan_structured_value(
                child,
                rel_path=rel_path,
                field_path=f"{field_path}[{index}]",
                findings=findings,
                warnings=warnings,
            )
        return
    if not isinstance(value, str) or is_exempt_field(field_path):
        return
    matched = scan_text_for_terms(value)
    if not matched:
        return
    leaf = field_path.split(".")[-1]
    message = f"{rel_path}: {field_path}: prohibited advisory wording detected: {', '.join(matched)}"
    if leaf in {"title_native", "title_en"}:
        warnings.append(f"{message} (quoted source title context)")
        return
    if is_doc_path(rel_path) and is_policy_negation_context(value):
        warnings.append(f"{message} (policy negation context)")
        return
    if "invalid" in rel_path or "negative" in rel_path or "calibration" in rel_path:
        warnings.append(f"{message} (fixture context)")
        return
    findings.append(message)


def should_scan_field_name(rel_path: str) -> bool:
    return rel_path.startswith(("data/", "indexes/", "dist/", "adapters/")) or "adapter" in rel_path


def scan_plain_doc(rel_path: str, text: str) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    warnings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        matched = scan_text_for_terms(line)
        if not matched:
            continue
        message = f"{rel_path}:{line_no}: prohibited advisory wording detected: {', '.join(matched)}"
        if is_policy_negation_context(line):
            warnings.append(f"{message} (policy negation context)")
        else:
            findings.append(message)
    return findings, warnings


def advisory_wording(changed_files: list[str]) -> ValidatorResult:
    findings: list[str] = []
    warnings: list[str] = []
    scanned = 0
    target_files = changed_files or default_wording_scan_files()

    for rel_path in target_files:
        path = ROOT / rel_path
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() in {".yaml", ".yml", ".json"}:
            try:
                payload = load_mapping(path)
            except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
                findings.append(f"{rel_path}: cannot parse for advisory wording: {exc}")
                continue
            scanned += 1
            scan_structured_value(payload, rel_path=rel_path, field_path="", findings=findings, warnings=warnings)
        elif path.suffix.lower() == ".md":
            scanned += 1
            doc_findings, doc_warnings = scan_plain_doc(rel_path, path.read_text(encoding="utf-8"))
            findings.extend(doc_findings)
            warnings.extend(doc_warnings)

    for rel_path in target_files:
        path = ROOT / rel_path
        if not path.exists() or not path.is_file() or path.suffix.lower() not in {".yaml", ".yml", ".json"}:
            continue
        try:
            payload = load_mapping(path)
        except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError):
            continue
        for summary_path, summary in iter_summary_strings(payload):
            lower = summary.lower()
            for phrase in implication_phrases():
                if phrase in lower:
                    message = f"{rel_path}: {summary_path}: implication language detected: {phrase}"
                    if "invalid" in rel_path or "negative" in rel_path or "calibration" in rel_path:
                        warnings.append(f"{message} (fixture context)")
                    else:
                        findings.append(message)

    return result(
        "advisory-wording-agent",
        warnings=dedupe(warnings),
        escalations=dedupe(findings),
        changed_files=changed_files,
        details={"files_scanned": scanned},
    )


def iter_summary_strings(payload: Any, prefix: str = "") -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in ADVISORY_CONTEXT_KEYS and isinstance(value, str):
                items.append((path, value))
            items.extend(iter_summary_strings(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            items.extend(iter_summary_strings(value, f"{prefix}[{index}]"))
    return items


def default_wording_scan_files() -> list[str]:
    roots = ["data", "examples", "indexes", "dist", "docs", "adapters"]
    paths: list[str] = []
    for root_name in roots:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".json", ".md"}:
                paths.append(relative_repo_path(path, ROOT))
    return paths


def source_ids() -> set[str]:
    return {str(record["source_id"]) for record in records_for("source")}


def vendor_ids() -> set[str]:
    return {str(record["vendor_id"]) for record in records_for("vendor")}


def provenance_completeness(changed_files: list[str]) -> ValidatorResult:
    escalations: list[str] = []
    existing_sources = source_ids()
    existing_vendors = vendor_ids()
    checked = 0

    for rel_path in changed_files:
        kind = record_kind_for_path(rel_path)
        if not kind:
            continue
        path = ROOT / rel_path
        if not path.exists():
            continue
        try:
            record = load_mapping(path)
        except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
            escalations.append(f"{rel_path}: cannot parse for provenance: {exc}")
            continue
        checked += 1
        if kind == "source":
            if record.get("vendor_id") not in existing_vendors:
                escalations.append(f"{rel_path}: vendor_id does not resolve")
            provenance = record.get("provenance") or {}
            if not provenance.get("collected_at"):
                escalations.append(f"{rel_path}: provenance.collected_at is required")
            if not provenance.get("publisher"):
                escalations.append(f"{rel_path}: provenance.publisher is required")
        if kind == "legal_entity" and record.get("catalog_status") == "canonical":
            if not record.get("verification_source_ids"):
                escalations.append(f"{rel_path}: canonical legal entity missing verification_source_ids")
        if kind == "entity_mention":
            resolution = record.get("resolution") or {}
            if resolution.get("status") == "matched_to_entity":
                required = {"matched_entity_id", "match_method", "matched_by", "match_confidence", "match_source_ids", "matched_at"}
                missing = sorted(required - set(resolution))
                if missing:
                    escalations.append(f"{rel_path}: matched entity mention missing match provenance {missing}")
        for field_path, values in iter_source_id_lists(record):
            for source_id in values:
                if source_id not in existing_sources:
                    escalations.append(f"{rel_path}: {field_path} references unknown source_id {source_id}")

    return result(
        "provenance-completeness-agent",
        escalations=dedupe(escalations),
        changed_files=changed_files,
        details={"records_checked": checked},
    )


def iter_source_id_lists(payload: Any, prefix: str = "") -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in {"source_ids", "verification_source_ids", "match_source_ids"} and isinstance(value, list):
                found.append((path, [str(item) for item in value]))
            elif key in {"source_id", "appears_in_source_id"} and isinstance(value, str):
                found.append((path, [value]))
            found.extend(iter_source_id_lists(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(iter_source_id_lists(value, f"{prefix}[{index}]"))
    return found


def load_category_tags() -> set[str]:
    path = ROOT / "config/category-taxonomy.yaml"
    data = load_yaml(path) or {}
    return set((data.get("vendor_categories") or {}).keys())


def regulated_terms() -> set[str]:
    path = ROOT / "config/controlled-vocabulary.yaml"
    if not path.exists():
        return set()
    config = load_yaml(path) or {}
    return {str(term).lower() for term in config.get("regulated_legal_terms", [])}


def contains_regulated_term(value: str) -> bool:
    words = re.findall(r"[a-z]+", value.lower())
    return any(term in words for term in regulated_terms())


def public_url_status(url: str, fetcher: Callable[[str], FetchResult]) -> tuple[str, int | None]:
    fetched = fetcher(url)
    if fetched.http_status in AUTH_STATUSES:
        return "auth_required", fetched.http_status
    if fetched.http_status == 403:
        return "bot_protected", fetched.http_status
    if fetched.http_status is None:
        return "unreachable", None
    if 200 <= fetched.http_status < 400:
        return "reachable", fetched.http_status
    return "unreachable", fetched.http_status


def domain_has_public_dns(domain: str) -> bool:
    try:
        socket.getaddrinfo(domain, None)
        return True
    except socket.gaierror:
        return False


def new_vendor_rules(
    changed_files: list[str],
    *,
    fetcher: Callable[[str], FetchResult] | None = None,
    check_dns: bool = True,
) -> ValidatorResult:
    warnings: list[str] = []
    escalations: list[str] = []
    checked = 0
    vendors = records_for("vendor")
    vendor_paths = {record.get("_openva_path"): record for record in vendors}
    ids = Counter(str(record.get("vendor_id")) for record in vendors)
    domains_by_vendor: dict[str, str] = {}
    for vendor in vendors:
        for domain in vendor.get("official_domains", []) or []:
            domains_by_vendor[str(domain).lower()] = str(vendor["vendor_id"])
    allowed_categories = load_category_tags()
    blocklist = load_domain_blocklist()

    for rel_path in changed_files:
        if record_kind_for_path(rel_path) != "vendor":
            continue
        path = ROOT / rel_path
        if not path.exists():
            continue
        vendor = vendor_paths.get(rel_path) or load_mapping(path)
        checked += 1
        vendor_id = str(vendor.get("vendor_id") or "")
        if ids[vendor_id] > 1:
            escalations.append(f"{rel_path}: vendor_id {vendor_id} is not globally unique")
        domains = [str(domain).lower() for domain in vendor.get("official_domains", []) or []]
        if not domains:
            escalations.append(f"{rel_path}: official_domains must contain at least one domain")
        for domain in domains:
            owner = domains_by_vendor.get(domain)
            if owner and owner != vendor_id:
                escalations.append(f"{rel_path}: official_domain {domain} conflicts with vendor {owner}")
            blocked = blocked_domain_reason(domain, blocklist)
            if blocked:
                escalations.append(f"{rel_path}: official_domain {domain} is blocklisted as {blocked}")
            if check_dns and not domain_has_public_dns(domain):
                warnings.append(f"{rel_path}: official_domain {domain} did not resolve during soft WHOIS/DNS check")
        categories = set(vendor.get("vendor_categories", []) or [])
        if not categories & allowed_categories:
            escalations.append(f"{rel_path}: vendor_categories must include a controlled vocabulary value")
        regulated = sorted(categories & REGULATED_CATEGORIES)
        if regulated:
            escalations.append(f"{rel_path}: regulated vendor_categories require review: {regulated}")
        if (vendor.get("source_policy") or {}).get("public_sources_only") is not True:
            escalations.append(f"{rel_path}: source_policy.public_sources_only must be true")
        legal_name = str(vendor.get("legal_name") or "")
        if contains_regulated_term(legal_name):
            escalations.append(f"{rel_path}: legal_name contains jurisdiction-sensitive regulated term")
        entrypoints = vendor.get("public_entrypoints", []) or []
        if not entrypoints:
            escalations.append(f"{rel_path}: at least one public_entrypoint is required")
        # SSRF-safe fetch bound to this vendor's own official domains (fail-closed
        # if none); an injected fetcher (tests) is honoured verbatim.
        vendor_fetcher = fetcher if fetcher is not None else safe_fetcher_for_domains(domains)
        reachable = False
        for entrypoint in entrypoints:
            status, http_status = public_url_status(str(entrypoint), vendor_fetcher)
            if status == "reachable" and http_status in {200, 301, 302} | set(range(200, 400)):
                reachable = True
            if http_status == 403 or status == "bot_protected":
                escalations.append(f"{rel_path}: public_entrypoint {entrypoint} returned 403 or bot protection")
        if entrypoints and not reachable:
            warnings.append(f"{rel_path}: no public_entrypoint returned HTTP 200 or public redirect during soft check")

    return result(
        "new-vendor-rules",
        warnings=dedupe(warnings),
        escalations=dedupe(escalations),
        changed_files=changed_files,
        details={"vendor_records_checked": checked},
    )


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def entity_resolution_rules(changed_files: list[str]) -> ValidatorResult:
    escalations: list[str] = []
    suggestions: list[dict[str, Any]] = []
    legal_entities = [record for record in records_for("legal_entity") if record.get("catalog_status") == "canonical"]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for entity in legal_entities:
        by_name.setdefault(normalize_name(str(entity.get("legal_name") or "")), []).append(entity)
    sources = source_ids()
    checked = 0

    for rel_path in changed_files:
        if record_kind_for_path(rel_path) != "entity_mention":
            continue
        path = ROOT / rel_path
        if not path.exists():
            continue
        mention = load_mapping(path)
        checked += 1
        observed_name = str(mention.get("observed_name") or "")
        matches = by_name.get(normalize_name(observed_name), [])
        if contains_regulated_term(observed_name):
            escalations.append(f"{rel_path}: observed_name contains regulated term")
        if not matches:
            escalations.append(f"{rel_path}: observed_name matches no canonical entity exactly")
            continue
        if len(matches) > 1:
            escalations.append(f"{rel_path}: observed_name matches multiple canonical entities")
            continue
        match = matches[0]
        if match.get("vendor_id") != mention.get("vendor_id"):
            escalations.append(f"{rel_path}: cross-vendor entity reference requires review")
            continue
        if mention.get("appears_in_source_id") not in sources:
            escalations.append(f"{rel_path}: appears_in_source_id does not resolve")
            continue
        if mention.get("assertion_source") != "vendor_published":
            escalations.append(f"{rel_path}: assertion_source must be vendor_published")
            continue
        verification_ids = match.get("verification_source_ids") or []
        suggestions.append(
            {
                "mention_id": mention.get("mention_id"),
                "matched_entity_id": match.get("entity_id"),
                "resolution": {
                    "status": "matched_to_entity",
                    "matched_entity_id": match.get("entity_id"),
                    "match_method": "legal_name_exact",
                    "matched_by": "agent",
                    "match_confidence": "high",
                    "matched_at": mention.get("observed_at"),
                    "match_source_ids": verification_ids[:1],
                },
            }
        )

    return result(
        "entity-resolution-rules",
        escalations=dedupe(escalations),
        changed_files=changed_files,
        details={"mentions_checked": checked, "suggested_matches": suggestions},
    )


def legal_entity_promotion_rules(
    changed_files: list[str],
    *,
    fetcher: Callable[[str], FetchResult] | None = None,
) -> ValidatorResult:
    escalations: list[str] = []
    warnings: list[str] = []
    checked = 0
    vendors = {record["vendor_id"]: record for record in records_for("vendor")}
    sources = {record["source_id"]: record for record in records_for("source")}

    for rel_path in changed_files:
        if record_kind_for_path(rel_path) != "legal_entity":
            continue
        path = ROOT / rel_path
        if not path.exists():
            continue
        entity = load_mapping(path)
        if entity.get("catalog_status") != "stub":
            continue
        checked += 1
        if not entity.get("legal_name"):
            escalations.append(f"{rel_path}: legal_name is required")
        if not re.match(r"^[A-Z]{2}$", str(entity.get("jurisdiction") or "")):
            escalations.append(f"{rel_path}: jurisdiction must be ISO 3166-1 alpha-2")
        vendor = vendors.get(entity.get("vendor_id"))
        if not vendor:
            escalations.append(f"{rel_path}: vendor_id does not resolve")
        verification_sources = [sources.get(source_id) for source_id in entity.get("verification_source_ids", [])]
        authoritative = [
            source for source in verification_sources
            if source and source.get("source_authority_class") in PUBLIC_AUTHORITY_CLASSES
        ]
        if not authoritative:
            escalations.append(f"{rel_path}: public registry or public authority verification source required")
        # SSRF-safe fetch bound to the resolved vendor's official domains
        # (fail-closed if the vendor is unresolved or has none).
        vendor_fetcher = fetcher if fetcher is not None else safe_fetcher_for_domains(
            (vendor or {}).get("official_domains") or []
        )
        for source in authoritative[:1]:
            status, http_status = public_url_status(str(source.get("source_url") or ""), vendor_fetcher)
            if status != "reachable" or http_status != 200:
                escalations.append(f"{rel_path}: verification source {source.get('source_id')} is not HTTP 200")
        for event in entity.get("lifecycle_events", []) or []:
            if event.get("event_type") in {"dissolved", "merged"} and not event.get("successor_entity_ids"):
                escalations.append(f"{rel_path}: {event.get('event_type')} event requires successor_entity_ids")
        registration = entity.get("registration_number")
        if entity.get("jurisdiction") == "SG" and registration and not is_probable_sg_uen(str(registration)):
            escalations.append(f"{rel_path}: registration_number does not match SG UEN length pattern")
        if vendor and edit_distance_ratio(str(entity.get("legal_name") or ""), str(vendor.get("display_name") or "")) > 0.4:
            escalations.append(f"{rel_path}: legal_name differs significantly from vendor display_name")
        if entity.get("parent_entity_id"):
            warnings.append(f"{rel_path}: parent entity jurisdiction explanation requires policy-aware review if different")

    return result(
        "legal-entity-promotion-rules",
        warnings=dedupe(warnings),
        escalations=dedupe(escalations),
        changed_files=changed_files,
        details={"stub_entities_checked": checked},
    )


def is_probable_sg_uen(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    return len(compact) in {9, 10} and compact[-1].isalnum()


def edit_distance_ratio(left: str, right: str) -> float:
    left_norm = re.sub(r"[^a-z0-9]+", "", left.lower())
    right_norm = re.sub(r"[^a-z0-9]+", "", right.lower())
    if not left_norm and not right_norm:
        return 0.0
    if not left_norm or not right_norm:
        return 1.0
    previous = list(range(len(right_norm) + 1))
    for i, left_char in enumerate(left_norm, start=1):
        current = [i]
        for j, right_char in enumerate(right_norm, start=1):
            current.append(
                min(
                    current[j - 1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (0 if left_char == right_char else 1),
                )
            )
        previous = current
    return previous[-1] / max(len(left_norm), len(right_norm))


def weighted_review(result_paths: list[Path]) -> dict[str, Any]:
    results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths if path.exists()]
    total = sum(int(item.get("score", 0)) for item in results)
    warnings = [warning for item in results for warning in item.get("warnings", [])]
    escalations = [escalation for item in results for escalation in item.get("escalations", [])]
    failures = [failure for item in results for failure in item.get("failures", [])]
    label = "openva:weighted-pass"
    if escalations or failures or total < 4:
        label = "openva:needs-human-review"
    elif warnings:
        label = "openva:weighted-warning"
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "total_score": total,
        "max_score": 4,
        "label": label,
        "advisory_only": True,
        "warnings": warnings,
        "escalations": escalations,
        "failures": failures,
        "validators": results,
    }


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def write_output(payload: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--changed-files", help="File containing changed repository paths, one per line")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-escalation", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-automation-rules")
    subparsers = parser.add_subparsers(dest="command", required=True)

    commands = [
        "schema-conformance",
        "source-accessibility",
        "advisory-wording",
        "provenance-completeness",
        "new-vendor-rules",
        "entity-resolution-rules",
        "legal-entity-promotion-rules",
    ]
    for command in commands:
        subparser = subparsers.add_parser(command)
        add_common_args(subparser)
    source_parser = subparsers.choices["source-accessibility"]
    source_parser.add_argument("--retry-429", action="store_true")
    vendor_parser = subparsers.choices["new-vendor-rules"]
    vendor_parser.add_argument("--skip-dns-check", action="store_true")

    weighted = subparsers.add_parser("weighted-review")
    weighted.add_argument("result_paths", nargs="*", type=Path)
    weighted.add_argument("--output", type=Path)

    args = parser.parse_args()

    if args.command == "weighted-review":
        payload = weighted_review(args.result_paths)
        write_output(payload, args.output)
        return 0

    changed_files = changed_files_from_args(args)
    validators = {
        "schema-conformance": lambda: schema_conformance(changed_files),
        "source-accessibility": lambda: source_accessibility(changed_files, retry_429=args.retry_429),
        "advisory-wording": lambda: advisory_wording(changed_files),
        "provenance-completeness": lambda: provenance_completeness(changed_files),
        "new-vendor-rules": lambda: new_vendor_rules(changed_files, check_dns=not args.skip_dns_check),
        "entity-resolution-rules": lambda: entity_resolution_rules(changed_files),
        "legal-entity-promotion-rules": lambda: legal_entity_promotion_rules(changed_files),
    }
    validator_result = validators[args.command]().to_dict()
    write_output(validator_result, args.output)
    if args.fail_on_escalation and (validator_result["escalations"] or validator_result["failures"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
