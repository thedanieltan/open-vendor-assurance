from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yaml

from tools.openva.source_verification import FetchResult, fetch_url, verify_source
from tools.openva.url_safety import validate_url_safety

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
COMMENT_MARKER = "<!-- openva-contribution-intake-agent -->"

REQUEST_TYPE_LABEL = "What needs to change?"
VENDOR_LABEL = "Vendor name or OpenVA vendor ID"
SUBMITTER_ROLE_LABEL = "Submitter role"
PUBLIC_SOURCES_LABEL = "Public source URL(s)"
CONTEXT_LABEL = "What should OpenVA look at?"

LOW_RISK_SOURCE_TYPES = {
    "dpa",
    "subprocessors_list",
    "privacy_notice",
    "trust_center",
    "security_page",
}

HUMAN_REVIEW_SOURCE_TYPES = {
    "aml_statement",
    "certification_reference",
    "compliance_page",
    "government_request_policy",
    "kyc_statement",
    "terms_of_service",
    "transparency_report",
    "other_public_source",
}

SOURCE_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("subprocessors_list", ("subprocessor", "sub-processors", "sub-processor", "processors")),
    ("dpa", ("dpa", "data-processing", "data_processing", "data processing", "addendum")),
    ("privacy_notice", ("privacy", "privacy-policy", "privacy-notice")),
    ("security_page", ("security", "vulnerability", "encryption")),
    ("trust_center", ("trust", "trust-center", "trustcenter")),
    ("ai_terms", ("ai", "artificial-intelligence")),
    ("government_request_policy", ("government-request", "law-enforcement")),
    ("transparency_report", ("transparency",)),
    ("compliance_page", ("compliance", "soc", "iso", "audit")),
    ("certification_reference", ("certification", "certificate", "certifications")),
    ("kyc_statement", ("kyc", "know-your-customer")),
    ("aml_statement", ("aml", "anti-money-laundering")),
    ("terms_of_service", ("terms", "tos", "legal")),
)

ADVISORY_RE = re.compile(
    r"\b(compliant|safe|approved|adequate|recommended|suitable|low risk|high risk|"
    r"risk score|certified by openva|verified by openva|meets requirements|"
    r"satisfies obligations)\b",
    re.IGNORECASE,
)

GATED_RE = re.compile(
    r"\b(login|log in|captcha|nda|customer portal|private portal|sales approval|"
    r"support ticket|credentials?|anti-bot bypass|form submission)\b",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://[^\s<>)\]]+")


@dataclass(frozen=True)
class VendorMatch:
    vendor_id: str
    record: dict[str, Any]
    path: Path


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "source"


def normalize_url(url: str) -> str:
    clean = url.strip().rstrip(".,);]")
    parsed = urlparse(clean)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or ""
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{scheme}://{host}{port}{path}{query}{fragment}"


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for url in extract_all_urls(text):
        if url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def extract_all_urls(text: str) -> list[str]:
    return [normalize_url(match) for match in URL_RE.findall(text or "")]


def parse_issue_form(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if current is None:
            return
        value = "\n".join(lines).strip()
        if value == "_No response_":
            value = ""
        sections[current] = value

    for line in body.splitlines():
        match = re.match(r"^###\s+(.+?)\s*$", line)
        if match:
            flush()
            current = match.group(1).strip()
            lines = []
            continue
        if current is not None:
            lines.append(line)
    flush()
    return sections


def vendor_records(root: Path = ROOT) -> list[VendorMatch]:
    matches: list[VendorMatch] = []
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        record = load_yaml(path)
        vendor_id = str(record.get("vendor_id") or path.parent.name)
        matches.append(VendorMatch(vendor_id=vendor_id, record=record, path=path))
    return matches


def match_vendor(vendor_input: str, root: Path = ROOT) -> VendorMatch | None:
    needle = vendor_input.strip().lower()
    if not needle:
        return None
    normalized = slugify(needle)
    for vendor in vendor_records(root):
        names = {
            vendor.vendor_id.lower(),
            str(vendor.record.get("display_name") or "").lower(),
            str(vendor.record.get("legal_name") or "").lower(),
        }
        if needle in names or normalized == vendor.vendor_id.lower():
            return vendor
    return None


def source_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/sources/*.yaml"))


def existing_source_urls(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    urls: dict[str, dict[str, Any]] = {}
    for path in source_paths(root):
        source = load_yaml(path)
        url = normalize_url(str(source.get("source_url") or ""))
        if url:
            urls[url] = {"path": path.as_posix(), "source": source}
    return urls


def load_official_publisher_exceptions(root: Path = ROOT) -> list[dict[str, str]]:
    path = root / "config" / "official-publisher-exceptions.yaml"
    if not path.exists():
        return []
    data = load_yaml(path)
    exceptions = data.get("exceptions", [])
    if not isinstance(exceptions, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in exceptions:
        if isinstance(item, str):
            normalized.append({"domain": item})
        elif isinstance(item, dict):
            normalized.append({str(key): str(value) for key, value in item.items()})
    return normalized


def host_for(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def host_matches_domain(host: str, domain: str) -> bool:
    domain = domain.lower().rstrip(".")
    return host == domain or host.endswith(f".{domain}")


def is_authoritative_url(url: str, vendor: VendorMatch, root: Path = ROOT) -> bool:
    host = host_for(url)
    for domain in vendor.record.get("official_domains", []) or []:
        if host_matches_domain(host, str(domain)):
            return True
    for exception in load_official_publisher_exceptions(root):
        vendor_id = exception.get("vendor_id")
        if vendor_id and vendor_id != vendor.vendor_id:
            continue
        domain = (
            exception.get("domain")
            or exception.get("source_domain")
            or exception.get("host")
            or exception.get("hostname")
        )
        if domain and host_matches_domain(host, domain):
            return True
    return False


def classify_source_type(url: str, context: str = "") -> str | None:
    parsed = urlparse(url)
    haystack = " ".join(
        part.lower()
        for part in (
            parsed.hostname or "",
            parsed.path.replace("-", " ").replace("_", " "),
            parsed.query.replace("-", " ").replace("_", " "),
            context,
        )
    )
    for source_type, patterns in SOURCE_TYPE_PATTERNS:
        if any(pattern in haystack for pattern in patterns):
            return source_type
    return None


def source_title(display_name: str, source_type: str) -> str:
    labels = {
        "dpa": "Data Processing Agreement",
        "subprocessors_list": "Subprocessors",
        "privacy_notice": "Privacy Notice",
        "trust_center": "Trust Center",
        "security_page": "Security Page",
        "ai_terms": "AI Terms",
    }
    return f"{display_name} {labels.get(source_type, source_type.replace('_', ' ').title())}"


def access_class_for(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return "public_pdf"
    return "public_web"


def build_source_entry(vendor: VendorMatch, url: str, source_type: str) -> dict[str, Any]:
    vendor_id = vendor.vendor_id
    source_id = f"{vendor_id}-{source_type.replace('_', '-')}"
    title = source_title(str(vendor.record.get("display_name") or vendor_id), source_type)
    summary = f"Public {title} metadata reference."
    return {
        "source_id": source_id,
        "source_type": source_type,
        "source_authority_class": "vendor_published",
        "title_native": title,
        "title_en": title,
        "source_url": url,
        "source_language": "en",
        "access_class": access_class_for(url),
        "summary_native": summary,
        "summary_en": summary,
        "confidence": "medium",
        "artifact": {
            "artifact_id": source_id,
            "artifact_type": source_type,
        },
    }


def vendor_manifest_entry(vendor: VendorMatch, sources: list[dict[str, Any]]) -> dict[str, Any]:
    record = vendor.record
    entry: dict[str, Any] = {
        "vendor_id": vendor.vendor_id,
        "display_name": record["display_name"],
        "legal_name": record.get("legal_name"),
        "headquarters_country": record["headquarters_country"],
        "regions_served": record["regions_served"],
        "official_domains": record["official_domains"],
        "public_entrypoints": record["public_entrypoints"],
        "vendor_categories": record["vendor_categories"],
        "status": record.get("status", "active"),
        "notes": record.get("notes"),
        "sources": sources,
    }
    for field in ("entity_family", "entity_surface", "related_vendor_ids", "source_authority_language"):
        if field in record:
            entry[field] = record[field]
    return entry


def request_is_new_vendor(request_type: str) -> bool:
    return "add a new vendor" in request_type.lower()


def request_is_auto_add_or_correct(request_type: str) -> bool:
    lowered = request_type.lower()
    return any(
        phrase in lowered
        for phrase in (
            "add a public source",
            "correct an existing source url",
            "correct source title",
            "correct vendor metadata",
        )
    )


def network_check_source(
    source: dict[str, Any],
    fetcher: Callable[[str], FetchResult],
    root: Path,
) -> dict[str, Any]:
    verification = verify_source(source, Path("issue-intake"), fetcher=fetcher, root=root)
    status = str(verification["verification_status"])
    ok = status in {"ok", "redirected"}
    return {
        "ok": ok,
        "verification_status": status,
        "http_status": verification.get("http_status"),
        "final_url": verification.get("final_url"),
        "semantic_match": verification.get("semantic_match"),
    }


def intake_decision(
    issue_body: str,
    *,
    issue_number: int,
    root: Path = ROOT,
    network_check: bool = False,
    fetcher: Callable[[str], FetchResult] = fetch_url,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sections = parse_issue_form(issue_body)
    request_type = sections.get(REQUEST_TYPE_LABEL, "").strip()
    vendor_input = sections.get(VENDOR_LABEL, "").strip()
    submitter_role = sections.get(SUBMITTER_ROLE_LABEL, "").strip()
    public_sources_text = sections.get(PUBLIC_SOURCES_LABEL, "")
    context = sections.get(CONTEXT_LABEL, "").strip()
    all_urls = extract_all_urls(public_sources_text)
    urls = extract_urls(public_sources_text)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_type": "contribution_intake_agent",
        "generated_at": generated_at,
        "issue_number": issue_number,
        "intake": {
            "request_type": request_type,
            "vendor_input": vendor_input,
            "submitter_role": submitter_role,
            "urls": urls,
            "context": context,
        },
        "posture": {
            "auto_triage": True,
            "auto_pr_allowed_for_low_risk_existing_vendor_sources": True,
            "auto_merge": False,
            "does_not_bypass_access_controls": True,
            "does_not_remove_sources_from_fetch_failures": True,
        },
        "checks": [],
        "proposed_sources": [],
        "decision": "needs_human_review",
        "reasons": [],
    }

    reasons: list[str] = report["reasons"]
    checks: list[dict[str, Any]] = report["checks"]

    if not request_type:
        reasons.append("missing_request_type")
    if not vendor_input:
        reasons.append("missing_vendor")
    if not urls:
        reasons.append("missing_public_url")
    if len(all_urls) != len(set(all_urls)):
        reasons.append("duplicate_url_in_issue")
    if ADVISORY_RE.search(context):
        reasons.append("advisory_language_needs_human_review")
    if GATED_RE.search(context):
        reasons.append("gated_or_access_control_language_needs_human_review")
    if request_is_new_vendor(request_type):
        reasons.append("new_vendor_identity_requires_human_review")
    if request_type and not request_is_auto_add_or_correct(request_type):
        reasons.append("request_type_requires_human_review")

    vendor = match_vendor(vendor_input, root=root)
    if not vendor and vendor_input:
        reasons.append("unknown_vendor_requires_human_review")

    duplicate_urls = existing_source_urls(root)
    proposed_sources: list[dict[str, Any]] = []
    source_operations: set[str] = set()

    if vendor:
        report["vendor"] = {
            "vendor_id": vendor.vendor_id,
            "display_name": vendor.record.get("display_name"),
        }
        for url in urls:
            url_checks: dict[str, Any] = {"url": url, "passed": True, "messages": []}
            safety_failures = validate_url_safety(url)
            if safety_failures:
                url_checks["passed"] = False
                url_checks["messages"].extend(safety_failures)
                reasons.append("unsafe_url")

            if normalize_url(url) in duplicate_urls:
                url_checks["passed"] = False
                url_checks["messages"].append("duplicate canonical source URL already exists")
                reasons.append("duplicate_canonical_source_url")

            if not is_authoritative_url(url, vendor, root=root):
                url_checks["passed"] = False
                url_checks["messages"].append("source host is not vendor-controlled or excepted")
                reasons.append("source_authority_needs_human_review")

            source_type = classify_source_type(url, context)
            if source_type is None:
                url_checks["passed"] = False
                url_checks["messages"].append("source type could not be classified safely")
                reasons.append("source_type_needs_human_review")
            elif source_type not in LOW_RISK_SOURCE_TYPES:
                url_checks["passed"] = False
                url_checks["messages"].append(f"{source_type} requires human review")
                reasons.append("source_type_requires_human_review")

            if source_type:
                source = build_source_entry(vendor, url, source_type)
                source_path = root / "data" / "vendors" / vendor.vendor_id / "sources" / f"{source['source_id']}.yaml"
                artifact_path = (
                    root
                    / "data"
                    / "vendors"
                    / vendor.vendor_id
                    / "artifacts"
                    / f"{source['artifact']['artifact_id']}.yaml"
                )
                operation = "refresh" if source_path.exists() and artifact_path.exists() else "create"
                source_operations.add(operation)
                if operation == "refresh" and "correct" not in request_type.lower():
                    url_checks["passed"] = False
                    url_checks["messages"].append("existing source type update requires correction request")
                    reasons.append("existing_source_update_requires_human_review")
                if network_check and url_checks["passed"]:
                    verification = network_check_source(source, fetcher, root)
                    url_checks["network_verification"] = verification
                    if not verification["ok"]:
                        url_checks["passed"] = False
                        status = verification["verification_status"]
                        url_checks["messages"].append(f"network verification requires review: {status}")
                        if status in {"bot_protected", "gated_or_login_required", "forbidden_unknown", "rate_limited"}:
                            reasons.append("automated_observation_blocked_not_source_removal")
                        else:
                            reasons.append("network_verification_needs_human_review")
                proposed_sources.append(source)

            checks.append(url_checks)

    if len(source_operations) > 1:
        reasons.append("mixed_create_and_refresh_requires_human_review")

    report["proposed_sources"] = proposed_sources
    unique_reasons = sorted(set(reasons))
    report["reasons"] = unique_reasons

    if not unique_reasons and vendor and proposed_sources:
        operation = next(iter(source_operations or {"create"}))
        manifest_path = Path("catalog-batches") / "intake" / f"issue-{issue_number}-{vendor.vendor_id}.yaml"
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "batch_id": f"intake-issue-{issue_number}-{vendor.vendor_id}",
            "operation": operation,
            "collected_at": generated_at,
            "observer": "agent",
            "vendors": [vendor_manifest_entry(vendor, proposed_sources)],
        }
        report["decision"] = "open_catalog_pr"
        report["manifest_path"] = manifest_path.as_posix()
        report["manifest"] = manifest
        report["pr"] = {
            "branch": f"agent-intake-issue-{issue_number}-{vendor.vendor_id}",
            "title": f"Catalog: intake issue #{issue_number} update {vendor.vendor_id} public source metadata",
        }
    else:
        report["decision"] = "needs_human_review"
    return report


def render_comment(report: dict[str, Any]) -> str:
    lines = [
        COMMENT_MARKER,
        "",
        "## OpenVA contribution intake",
        "",
        f"Decision: `{report['decision']}`",
        "",
        "Automated checks:",
    ]
    for check in report.get("checks", []):
        status = "passed" if check.get("passed") else "needs review"
        lines.append(f"- `{check['url']}`: {status}")
        for message in check.get("messages", []):
            lines.append(f"  - {message}")
        verification = check.get("network_verification")
        if verification:
            lines.append(
                "  - "
                f"network: `{verification['verification_status']}` "
                f"(http={verification.get('http_status') or '-'})"
            )

    if report.get("reasons"):
        lines.extend(["", "Review reasons:"])
        lines.extend(f"- `{reason}`" for reason in report["reasons"])

    lines.extend(
        [
            "",
            "Boundary notes:",
            "- Contributors are not expected to classify OpenVA metadata.",
            "- Agent classification is non-canonical until a reviewed `Catalog:` PR is merged.",
            "- Automated 403/CAPTCHA/WAF results do not remove or deprecate catalog sources.",
            "- OpenVA does not bypass login, CAPTCHA, form gates, private portals, or access controls.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_pr_body(report: dict[str, Any]) -> str:
    vendor = report.get("vendor", {})
    sources = report.get("proposed_sources", [])
    lines = [
        "## Summary",
        "",
        f"Agent-prepared catalog proposal from issue #{report['issue_number']}.",
        "",
        "## Vendor",
        "",
        f"- `{vendor.get('vendor_id')}`",
        "",
        "## Source URLs",
        "",
    ]
    lines.extend(f"- {source['source_url']} (`{source['source_type']}`)" for source in sources)
    lines.extend(
        [
            "",
            "## Automated checks",
            "",
            "- Source URL safety checks passed.",
            "- Source host is vendor-controlled or covered by an approved exception.",
            "- Source type fits existing OpenVA schema.",
            "- No contributor metadata classification was treated as canonical.",
            "- No raw documents, screenshots, or extracted full text were committed.",
            "- No auto-merge is enabled.",
            "",
            "## Observation-safe posture",
            "",
            "A later automated 403, CAPTCHA, WAF block, timeout, or bot-protection response must be treated as an observation result, not as source removal or deprecation. Hashes remain `sha256:TBD` unless approved observation tooling produces them.",
            "",
            "## Human review checklist",
            "",
            "- [ ] Confirm every URL is public and authoritative.",
            "- [ ] Confirm no access-control bypass, login, form submission, NDA, or private portal material was used.",
            "- [ ] Confirm source and artifact classification is accurate.",
            "- [ ] Confirm no advisory wording was introduced.",
            "- [ ] Confirm validation and tests pass.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_github_env(path: Path, report: dict[str, Any]) -> None:
    should_open = report["decision"] == "open_catalog_pr"
    lines = [f"OPENVA_INTAKE_SHOULD_OPEN_PR={'true' if should_open else 'false'}"]
    if should_open:
        lines.extend(
            [
                f"OPENVA_INTAKE_MANIFEST_PATH={report['manifest_path']}",
                f"OPENVA_INTAKE_PR_BRANCH={report['pr']['branch']}",
                f"OPENVA_INTAKE_PR_TITLE={report['pr']['title']}",
            ]
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def write_outputs(report: dict[str, Any], output_dir: Path, *, github_env: Path | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "intake-report.json").write_text(
        json.dumps({key: value for key, value in report.items() if key != "manifest"}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "intake-comment.md").write_text(render_comment(report), encoding="utf-8")
    (output_dir / "pr-body.md").write_text(render_pr_body(report), encoding="utf-8")
    if report["decision"] == "open_catalog_pr":
        write_yaml(ROOT / report["manifest_path"], report["manifest"])
    if github_env:
        write_github_env(github_env, report)


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-contribution-intake")
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue = subparsers.add_parser("issue")
    issue.add_argument("--issue-body", type=Path, required=True)
    issue.add_argument("--issue-number", type=int, required=True)
    issue.add_argument("--output-dir", type=Path, required=True)
    issue.add_argument("--network-check", action="store_true")
    issue.add_argument("--github-env", type=Path)

    args = parser.parse_args()
    if args.command == "issue":
        report = intake_decision(
            args.issue_body.read_text(encoding="utf-8"),
            issue_number=args.issue_number,
            network_check=args.network_check,
        )
        write_outputs(report, args.output_dir, github_env=args.github_env)
        print(json.dumps({"decision": report["decision"], "reasons": report["reasons"]}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
