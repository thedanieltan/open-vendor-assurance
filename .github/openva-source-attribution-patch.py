from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def write_text(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def update_source_schema() -> None:
    path = ROOT / "schemas/openva/source-reference.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    properties = schema["properties"]
    properties["publisher_attribution"] = {
        "type": "object",
        "description": "Who publishes the source and how that publisher relates to the selected product. This is source provenance only, not a legal, compliance, procurement, security, or vendor-risk conclusion.",
        "required": ["publisher_name", "publisher_domain", "relationship"],
        "properties": {
            "publisher_name": {"type": "string", "minLength": 1, "maxLength": 200},
            "publisher_vendor_id": {
                "type": ["string", "null"],
                "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$",
            },
            "publisher_domain": {
                "type": "string",
                "pattern": "^[A-Za-z0-9.-]+$",
                "minLength": 3,
                "maxLength": 253,
            },
            "relationship": {
                "enum": [
                    "self",
                    "parent",
                    "affiliate",
                    "regional_entity",
                    "authorized_host",
                    "public_authority",
                ]
            },
        },
        "additionalProperties": False,
    }
    properties["applicability"] = {
        "type": "object",
        "description": "Why this source is applicable to the product represented by vendor_id. Required by the changed-record catalog guard for cross-domain canonical sources.",
        "required": ["status", "coverage_basis", "covered_products", "evidence"],
        "properties": {
            "status": {"enum": ["verified", "not_required", "unresolved"]},
            "coverage_basis": {
                "enum": [
                    "same_product_domain",
                    "explicit_product_name",
                    "explicit_product_domain",
                    "defined_services_inclusion",
                    "incorporated_agreement",
                    "official_link",
                    "official_redirect",
                    "manual_exception",
                ]
            },
            "covered_products": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
            },
            "evidence": {
                "type": "object",
                "required": ["evidence_url", "statement", "assessed_at"],
                "properties": {
                    "evidence_url": {"type": "string", "format": "uri"},
                    "statement": {"type": "string", "minLength": 1, "maxLength": 800},
                    "assessed_at": {"type": "string", "format": "date-time"},
                    "evidence_digest": {
                        "type": ["string", "null"],
                        "pattern": "^sha256:[a-f0-9]{64}$",
                    },
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }
    path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_source_attribution_tool() -> None:
    write_text(
        "tools/openva/source_attribution.py",
        textwrap.dedent(
            '''
            from __future__ import annotations

            import argparse
            import json
            from collections import Counter
            from datetime import UTC, datetime
            from pathlib import Path
            from typing import Any
            from urllib.parse import urlparse

            import yaml

            ROOT = Path(__file__).resolve().parents[2]
            RELATIONSHIPS = {
                "self",
                "parent",
                "affiliate",
                "regional_entity",
                "authorized_host",
                "public_authority",
            }


            def load_yaml(path: Path) -> dict[str, Any]:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError(f"{path}: expected YAML mapping")
                return data


            def normalize_domain(value: str | None) -> str:
                raw = str(value or "").strip().lower().rstrip(".")
                if not raw:
                    return ""
                if "://" in raw:
                    raw = urlparse(raw).hostname or ""
                raw = raw.split("/")[0].split(":")[0].rstrip(".")
                return raw[4:] if raw.startswith("www.") else raw


            def source_hostname(source: dict[str, Any]) -> str:
                return normalize_domain(urlparse(str(source.get("source_url") or "")).hostname)


            def host_matches_domain(host: str, domain: str) -> bool:
                host = normalize_domain(host)
                domain = normalize_domain(domain)
                return bool(host and domain and (host == domain or host.endswith(f".{domain}")))


            def primary_product_domain(vendor: dict[str, Any]) -> str:
                domains = [normalize_domain(item) for item in vendor.get("official_domains", []) or []]
                domains = [item for item in domains if item]
                for domain in domains:
                    if not domain.startswith(("status.", "trust.", "security.")):
                        return domain
                return domains[0] if domains else ""


            def source_requires_attribution(source: dict[str, Any], vendor: dict[str, Any]) -> bool:
                host = source_hostname(source)
                primary = primary_product_domain(vendor)
                return bool(host and primary and not host_matches_domain(host, primary))


            def validate_source_attribution(source: dict[str, Any], vendor: dict[str, Any]) -> list[str]:
                if not source_requires_attribution(source, vendor):
                    return []

                failures: list[str] = []
                publisher = source.get("publisher_attribution")
                applicability = source.get("applicability")
                if not isinstance(publisher, dict):
                    failures.append("cross-domain source is missing publisher_attribution")
                    publisher = {}
                if not isinstance(applicability, dict):
                    failures.append("cross-domain source is missing applicability")
                    applicability = {}

                relationship = str(publisher.get("relationship") or "")
                if relationship not in RELATIONSHIPS:
                    failures.append("publisher_attribution.relationship is missing or unsupported")
                elif relationship == "self":
                    failures.append("cross-domain source cannot use publisher relationship self")

                publisher_name = str(publisher.get("publisher_name") or "").strip()
                if not publisher_name:
                    failures.append("publisher_attribution.publisher_name is required")

                publisher_domain = normalize_domain(publisher.get("publisher_domain"))
                host = source_hostname(source)
                if not publisher_domain:
                    failures.append("publisher_attribution.publisher_domain is required")
                elif not host_matches_domain(host, publisher_domain):
                    failures.append("publisher_attribution.publisher_domain does not match source_url host")

                if applicability.get("status") != "verified":
                    failures.append("cross-domain applicability.status must be verified")
                covered_products = applicability.get("covered_products")
                if not isinstance(covered_products, list) or not any(str(item).strip() for item in covered_products):
                    failures.append("applicability.covered_products must identify at least one product")
                if not str(applicability.get("coverage_basis") or "").strip():
                    failures.append("applicability.coverage_basis is required")

                evidence = applicability.get("evidence")
                if not isinstance(evidence, dict):
                    failures.append("applicability.evidence is required")
                else:
                    evidence_url = str(evidence.get("evidence_url") or "")
                    if urlparse(evidence_url).scheme != "https":
                        failures.append("applicability.evidence.evidence_url must be public HTTPS")
                    if not str(evidence.get("statement") or "").strip():
                        failures.append("applicability.evidence.statement is required")
                    if not str(evidence.get("assessed_at") or "").strip():
                        failures.append("applicability.evidence.assessed_at is required")
                return failures


            def classify_source(source: dict[str, Any], vendor: dict[str, Any]) -> tuple[str, list[str]]:
                if not source_requires_attribution(source, vendor):
                    return "same_product_domain", []
                failures = validate_source_attribution(source, vendor)
                if failures:
                    has_metadata = isinstance(source.get("publisher_attribution"), dict) or isinstance(
                        source.get("applicability"), dict
                    )
                    return ("invalid_attribution" if has_metadata else "unproven_cross_domain"), failures
                relationship = str(source["publisher_attribution"]["relationship"])
                return f"attributed_{relationship}", []


            def build_source_attribution_report(root: Path = ROOT) -> dict[str, Any]:
                rows: list[dict[str, Any]] = []
                failures: list[str] = []
                for vendor_path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
                    try:
                        vendor = load_yaml(vendor_path)
                    except Exception as exc:  # noqa: BLE001 - audit continues per vendor.
                        failures.append(f"{vendor_path}: {type(exc).__name__}: {exc}")
                        continue
                    source_dir = vendor_path.parent / "sources"
                    for source_path in sorted(source_dir.glob("*.yaml")):
                        try:
                            source = load_yaml(source_path)
                            classification, issues = classify_source(source, vendor)
                            publisher = source.get("publisher_attribution") or {}
                            applicability = source.get("applicability") or {}
                            rows.append(
                                {
                                    "vendor_id": source.get("vendor_id"),
                                    "source_id": source.get("source_id"),
                                    "source_type": source.get("source_type"),
                                    "source_url": source.get("source_url"),
                                    "classification": classification,
                                    "publisher_relationship": publisher.get("relationship"),
                                    "publisher_name": publisher.get("publisher_name"),
                                    "applicability_status": applicability.get("status"),
                                    "coverage_basis": applicability.get("coverage_basis"),
                                    "issues": issues,
                                    "path": source_path.relative_to(root).as_posix(),
                                }
                            )
                        except Exception as exc:  # noqa: BLE001 - audit continues per source.
                            failures.append(f"{source_path}: {type(exc).__name__}: {exc}")

                counts = Counter(row["classification"] for row in rows)
                unresolved = [
                    row for row in rows if row["classification"] in {"unproven_cross_domain", "invalid_attribution"}
                ]
                return {
                    "schema_version": "0.1.0",
                    "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "report_type": "source_publisher_attribution_audit",
                    "posture": {
                        "network_fetch_performed": False,
                        "writes_repository_state": False,
                        "mutates_catalog": False,
                        "non_advisory": True,
                    },
                    "summary": {
                        "source_count": len(rows),
                        "cross_domain_source_count": sum(
                            count for classification, count in counts.items() if classification != "same_product_domain"
                        ),
                        "unresolved_cross_domain_source_count": len(unresolved),
                        "pipeline_failure_count": len(failures),
                        "classification_counts": dict(sorted(counts.items())),
                    },
                    "sources": rows,
                    "unresolved": unresolved,
                    "failures": failures,
                }


            def main() -> int:
                parser = argparse.ArgumentParser(prog="openva-source-attribution")
                subparsers = parser.add_subparsers(dest="command", required=True)
                audit = subparsers.add_parser("audit")
                audit.add_argument("--output", type=Path, default=Path("source-attribution-audit.json"))
                audit.add_argument("--fail-on-unproven", action="store_true")
                args = parser.parse_args()

                report = build_source_attribution_report()
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                print(json.dumps(report["summary"], indent=2, sort_keys=True))
                if args.fail_on_unproven and (
                    report["summary"]["unresolved_cross_domain_source_count"]
                    or report["summary"]["pipeline_failure_count"]
                ):
                    return 1
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
            '''
        ),
    )


def patch_catalog_guard() -> None:
    replace_once(
        "tools/openva/catalog_guard.py",
        "from tools.openva.paths import normalize_repo_path, relative_repo_path\n",
        "from tools.openva.paths import normalize_repo_path, relative_repo_path\nfrom tools.openva.source_attribution import validate_source_attribution\n",
    )
    anchor = '''def validate_catalog_pr(paths: list[str], *, root: Path = ROOT) -> list[str]:
    failures = validate_catalog_paths(paths)
    failures.extend(validate_catalog_generated_outputs(paths))
    failures.extend(validate_changed_source_observations(paths, root=root))
    failures.extend(validate_catalog_batch_duplicates(paths, root=root))
    return failures
'''
    replacement = '''def validate_changed_source_attribution(paths: list[str], *, root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for raw_path in paths:
        path = normalize_path(raw_path)
        if not is_source_record_path(path):
            continue
        source_path = root / path
        if not source_path.exists():
            continue
        try:
            source = load_yaml(source_path)
            vendor_path = source_path.parent.parent / "vendor.yaml"
            vendor = load_yaml(vendor_path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        for issue in validate_source_attribution(source, vendor):
            failures.append(f"{path}: {issue}")
    return failures


def validate_catalog_pr(paths: list[str], *, root: Path = ROOT) -> list[str]:
    failures = validate_catalog_paths(paths)
    failures.extend(validate_catalog_generated_outputs(paths))
    failures.extend(validate_changed_source_observations(paths, root=root))
    failures.extend(validate_changed_source_attribution(paths, root=root))
    failures.extend(validate_catalog_batch_duplicates(paths, root=root))
    return failures
'''
    replace_once("tools/openva/catalog_guard.py", anchor, replacement)


def patch_site_build() -> None:
    replace_once(
        "site/build_core.py",
        '''        "provenance": source.get("provenance") or {},
        "source_health": source_health or source_health_for_source(source, {}),
''',
        '''        "provenance": source.get("provenance") or {},
        "publisher_attribution": source.get("publisher_attribution") or {},
        "applicability": source.get("applicability") or {},
        "source_health": source_health or source_health_for_source(source, {}),
''',
    )


def patch_site_app() -> None:
    replace_once(
        "site/src/app.js",
        '''function csvValue(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join("; ");
  return String(value);
}
''',
        '''function csvValue(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join("; ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
''',
    )
    replace_once(
        "site/src/app.js",
        '''      <p>Official domains: ${(vendor.official_domains || []).map((domain) => `<code>${html(domain)}</code>`).join(" ") || "Unavailable"}</p>
      <p>Headquarters country: ${html(vendor.headquarters_country)}</p>
''',
        '''      <p>Official domains: ${(vendor.official_domains || []).map((domain) => `<code>${html(domain)}</code>`).join(" ") || "Unavailable"}</p>
      ${vendorSourceAttributionNotice(vendor, sources)}
      <p>Headquarters country: ${html(vendor.headquarters_country)}</p>
''',
    )
    source_template = '''function sourceTemplate(source) {
  const health = source.source_health || {};
  const bucket = health.status_bucket || "missing";
  const label = health.label || SOURCE_HEALTH_LABELS[bucket] || SOURCE_HEALTH_LABELS.missing;
  const finalUrl = health.final_url && health.final_url !== source.source_url
    ? `<br>final_url: <a href="${html(health.final_url)}" target="_blank" rel="noreferrer">${html(health.final_url)}</a>`
    : "";
  return `
    <li>
      <span class="source-health source-health--${html(bucket)}">${html(label)}</span>
      status: ${html(health.status || "No source-health observation")} | last checked: ${html(health.verified_at || "No source-health observation")} | ${html(health.snapshot_notice || "Source health is based on the latest maintenance snapshot and may change.")}${finalUrl}<br>
      <label><input type="checkbox" data-select-source="${html(source.source_id)}" ${selectedSources.has(source.source_id) ? "checked" : ""}> Select source</label>
      <strong>${html(sourceTypeLabel(source.source_type))}</strong> · <a href="${html(source.source_url)}" target="_blank" rel="noreferrer">${html(source.title)}</a><br>
      language: ${html(source.source_language)} · authority: ${html(source.source_authority_class)} · access: ${html(source.access_class)} · rights: ${html(source.rights_class)}<br>
      provenance.collected_at: ${html(source.provenance && source.provenance.collected_at)} · catalog_tier: ${html(source.catalog_tier)} · review_state: ${html(source.review_state)} · advisory_boundary: ${html(source.advisory_boundary)}
    </li>
  `;
}
'''
    attributed_template = '''const SOURCE_RELATIONSHIP_LABELS = {
  self: "Product-published source",
  parent: "Parent-company source",
  affiliate: "Affiliate-published source",
  regional_entity: "Regional-entity source",
  authorized_host: "Authorized hosted source",
  public_authority: "Public-authority source",
};

function sourceDestinationDomain(source) {
  const publisher = source.publisher_attribution || {};
  if (publisher.publisher_domain) return publisher.publisher_domain;
  try {
    return new URL(source.source_url).hostname;
  } catch (_error) {
    return "Destination domain unavailable";
  }
}

function sourceAttributionTemplate(source) {
  const publisher = source.publisher_attribution || {};
  const applicability = source.applicability || {};
  if (!publisher.publisher_name) return "";
  const relationshipLabel = SOURCE_RELATIONSHIP_LABELS[publisher.relationship] || "Attributed source";
  const coveredProducts = Array.isArray(applicability.covered_products)
    ? applicability.covered_products.join(", ")
    : "Product coverage unavailable";
  const evidence = applicability.evidence || {};
  const evidenceLink = evidence.evidence_url
    ? `<a href="${html(evidence.evidence_url)}" target="_blank" rel="noreferrer">View coverage evidence</a>`
    : "Coverage evidence link unavailable";
  return `
    <div class="source-attribution">
      <div class="source-attribution__heading">
        <span class="source-attribution__badge">${html(relationshipLabel)}</span>
        <code>${html(sourceDestinationDomain(source))}</code>
      </div>
      <strong>Published by ${html(publisher.publisher_name)}</strong>
      <p>Covers ${html(coveredProducts)} · applicability: ${html(applicability.status || "unresolved")} · basis: ${html((applicability.coverage_basis || "unavailable").replaceAll("_", " "))}</p>
      <details>
        <summary>Why this source applies</summary>
        <p>${html(evidence.statement || "No applicability statement is recorded.")}</p>
        <p>${evidenceLink}</p>
      </details>
    </div>
  `;
}

function vendorSourceAttributionNotice(vendor, sources) {
  const attributed = sources.filter((source) => {
    const publisher = source.publisher_attribution || {};
    return publisher.publisher_name && publisher.relationship && publisher.relationship !== "self";
  });
  if (!attributed.length) return "";
  const publishers = [...new Set(attributed.map((source) => source.publisher_attribution.publisher_name))];
  return `
    <div class="source-attribution-notice">
      <strong>Some ${html(vendor.display_name)} documents are published by ${html(publishers.join(", "))}.</strong>
      <p>OpenVA identifies the publisher, relationship, destination domain, and product-coverage evidence before each cross-domain link.</p>
    </div>
  `;
}

function sourceTemplate(source) {
  const health = source.source_health || {};
  const bucket = health.status_bucket || "missing";
  const label = health.label || SOURCE_HEALTH_LABELS[bucket] || SOURCE_HEALTH_LABELS.missing;
  const finalUrl = health.final_url && health.final_url !== source.source_url
    ? `<br>final_url: <a href="${html(health.final_url)}" target="_blank" rel="noreferrer">${html(health.final_url)}</a>`
    : "";
  return `
    <li>
      <span class="source-health source-health--${html(bucket)}">${html(label)}</span>
      status: ${html(health.status || "No source-health observation")} | last checked: ${html(health.verified_at || "No source-health observation")} | ${html(health.snapshot_notice || "Source health is based on the latest maintenance snapshot and may change.")}${finalUrl}<br>
      <label><input type="checkbox" data-select-source="${html(source.source_id)}" ${selectedSources.has(source.source_id) ? "checked" : ""}> Select source</label>
      <strong>${html(sourceTypeLabel(source.source_type))}</strong><br>
      ${sourceAttributionTemplate(source)}
      <a class="source-open-link" href="${html(source.source_url)}" target="_blank" rel="noreferrer">Open ${html(source.title)}</a><br>
      language: ${html(source.source_language)} · authority: ${html(source.source_authority_class)} · access: ${html(source.access_class)} · rights: ${html(source.rights_class)}<br>
      provenance.collected_at: ${html(source.provenance && source.provenance.collected_at)} · catalog_tier: ${html(source.catalog_tier)} · review_state: ${html(source.review_state)} · advisory_boundary: ${html(source.advisory_boundary)}
    </li>
  `;
}
'''
    replace_once("site/src/app.js", source_template, attributed_template)
    replace_once(
        "site/src/app.js",
        '''    const header = ["source_id", "vendor_id", "source_type", "title", "source_url", "catalog_tier", "review_state", "advisory_boundary"];
''',
        '''    const header = ["source_id", "vendor_id", "source_type", "title", "source_url", "publisher_attribution", "applicability", "catalog_tier", "review_state", "advisory_boundary"];
''',
    )


def patch_site_styles() -> None:
    path = ROOT / "site/src/styles.css"
    text = path.read_text(encoding="utf-8")
    marker = "/* Source publisher attribution and product applicability. */"
    if marker in text:
        return
    addition = textwrap.dedent(
        '''

        /* Source publisher attribution and product applicability. */
        .source-attribution-notice {
          margin: 1rem 0;
          border: 1px solid var(--page-line, var(--line));
          border-left: 4px solid var(--page-brand, var(--accent));
          border-radius: .85rem;
          background: var(--page-brand-soft, var(--accent-soft));
          padding: .85rem 1rem;
        }
        .source-attribution-notice p { margin: .35rem 0 0; color: var(--page-muted, var(--muted)); }
        .source-attribution {
          display: grid;
          gap: .35rem;
          margin: .55rem 0;
          border: 1px solid var(--page-line, var(--line));
          border-radius: .75rem;
          background: var(--page-surface-muted, var(--surface-soft));
          padding: .75rem .85rem;
        }
        .source-attribution__heading {
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: .45rem;
        }
        .source-attribution__badge {
          display: inline-flex;
          width: fit-content;
          border-radius: 999px;
          background: var(--page-brand-soft, var(--accent-soft));
          color: var(--page-brand-strong, var(--accent-strong));
          padding: .2rem .55rem;
          font-size: .78rem;
          font-weight: 780;
        }
        .source-attribution p { margin: 0; color: var(--page-muted, var(--muted)); font-size: .88rem; }
        .source-attribution details { font-size: .86rem; }
        .source-attribution summary { cursor: pointer; color: var(--page-brand-strong, var(--brand)); font-weight: 720; }
        .source-open-link { display: inline-flex; margin: .25rem 0 .4rem; font-weight: 760; }
        '''
    )
    path.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def patch_exporters() -> None:
    replace_once(
        "adapters/python/openva_csv_export/openva_csv_export/exporter.py",
        '''    "source_language",
    "not_advice",
''',
        '''    "source_language",
    "publisher_attribution",
    "applicability",
    "not_advice",
''',
    )
    replace_once(
        "adapters/python/openva_sqlite_export/openva_sqlite_export/exporter.py",
        '''        "source_language": "TEXT",
        "not_advice": "INTEGER",
''',
        '''        "source_language": "TEXT",
        "publisher_attribution": "TEXT",
        "applicability": "TEXT",
        "not_advice": "INTEGER",
''',
    )


def patch_source_maintenance_workflow() -> None:
    replace_once(
        ".github/workflows/source-maintenance-report.yml",
        '''      - name: Build source health inventory report
        run: python -m tools.openva.source_health build --output source-health-report.json
      - name: Build network source verification report
''',
        '''      - name: Build source health inventory report
        run: python -m tools.openva.source_health build --output source-health-report.json
      - name: Build source publisher attribution audit
        run: python -m tools.openva.source_attribution audit --output source-attribution-audit.json
      - name: Build network source verification report
''',
    )
    replace_once(
        ".github/workflows/source-maintenance-report.yml",
        '''          health = json.load(open('source-health-report.json', encoding='utf-8'))
          verification = json.load(open('source-verification-report.json', encoding='utf-8'))
''',
        '''          health = json.load(open('source-health-report.json', encoding='utf-8'))
          attribution = json.load(open('source-attribution-audit.json', encoding='utf-8'))
          verification = json.load(open('source-verification-report.json', encoding='utf-8'))
''',
    )
    replace_once(
        ".github/workflows/source-maintenance-report.yml",
        '''              f"- Source health issues: `{health['summary']['sources_with_issues']}`",
              f"- Verification sources requiring review: `{verification['summary']['sources_requiring_review']}`",
''',
        '''              f"- Source health issues: `{health['summary']['sources_with_issues']}`",
              f"- Cross-domain sources without complete attribution: `{attribution['summary']['unresolved_cross_domain_source_count']}`",
              f"- Verification sources requiring review: `{verification['summary']['sources_requiring_review']}`",
''',
    )
    replace_once(
        ".github/workflows/source-maintenance-report.yml",
        '''              "- `source-quality-refinement-*`: human-reviewed queue for reachable source quality issues.",
''',
        '''              "- `source-attribution-audit.json`: publisher relationship and product-applicability inventory for cross-domain sources.",
              "- `source-quality-refinement-*`: human-reviewed queue for reachable source quality issues.",
''',
    )
    replace_once(
        ".github/workflows/source-maintenance-report.yml",
        '''              'source-health-report.json',
              'source-verification-report.json',
''',
        '''              'source-health-report.json',
              'source-attribution-audit.json',
              'source-verification-report.json',
''',
    )
    replace_once(
        ".github/workflows/source-maintenance-report.yml",
        '''            source-health-report.json
            source-verification-report.json
''',
        '''            source-health-report.json
            source-attribution-audit.json
            source-verification-report.json
''',
    )


def update_acuity_sources() -> None:
    shared_publisher = {
        "publisher_name": "Squarespace",
        "publisher_vendor_id": "squarespace",
        "publisher_domain": "squarespace.com",
        "relationship": "parent",
    }
    rows = {
        "acuity-scheduling-privacy.yaml": {
            "coverage_basis": "explicit_product_domain",
            "evidence_url": "https://www.squarespace.com/privacy",
            "statement": "The Squarespace Privacy Policy explicitly lists acuityscheduling.com among the Squarespace Services it covers.",
        },
        "acuity-scheduling-dpa.yaml": {
            "coverage_basis": "defined_services_inclusion",
            "evidence_url": "https://www.squarespace.com/terms-of-service",
            "statement": "The Squarespace Terms define the covered Services to include services provided through acuityscheduling.com; the DPA applies to those Squarespace Services.",
        },
        "acuity-scheduling-security.yaml": {
            "coverage_basis": "defined_services_inclusion",
            "evidence_url": "https://www.squarespace.com/terms-of-service",
            "statement": "The Squarespace Terms include acuityscheduling.com within the Squarespace Services, and Squarespace publishes this security page for that service family.",
        },
        "acuity-scheduling-terms-of-service.yaml": {
            "coverage_basis": "explicit_product_domain",
            "evidence_url": "https://www.squarespace.com/terms-of-service",
            "statement": "The Squarespace Terms of Service explicitly include services provided through acuityscheduling.com.",
        },
        "acuity-scheduling-status-page.yaml": {
            "coverage_basis": "explicit_product_name",
            "evidence_url": "https://status.squarespace.com/",
            "statement": "The Squarespace status page explicitly lists Acuity Scheduling as a monitored service.",
            "publisher_domain": "status.squarespace.com",
        },
    }
    for filename, evidence in rows.items():
        path = ROOT / "data/vendors/acuity-scheduling/sources" / filename
        source = yaml.safe_load(path.read_text(encoding="utf-8"))
        publisher = dict(shared_publisher)
        if evidence.get("publisher_domain"):
            publisher["publisher_domain"] = evidence["publisher_domain"]
        source["publisher_attribution"] = publisher
        source["applicability"] = {
            "status": "verified",
            "coverage_basis": evidence["coverage_basis"],
            "covered_products": ["Acuity Scheduling"],
            "evidence": {
                "evidence_url": evidence["evidence_url"],
                "statement": evidence["statement"],
                "assessed_at": "2026-07-15T00:00:00Z",
            },
        }
        path.write_text(yaml.safe_dump(source, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_documentation() -> None:
    write_text(
        "docs/source-publisher-attribution.md",
        textwrap.dedent(
            '''
            # Source Publisher Attribution and Product Applicability

            OpenVA distinguishes the product represented by a vendor record from the organization or service that publishes a source URL.

            A source hosted outside the product's primary domain may be canonical only when OpenVA records both:

            1. `publisher_attribution`: who publishes the source and the publisher's relationship to the product; and
            2. `applicability`: why the source covers the product represented by `vendor_id`.

            This metadata is factual source provenance. It is not legal, compliance, procurement, security, audit, suitability, approval, or vendor-risk advice.

            ## Publishing relationships

            - `self`: the selected product publishes the source directly;
            - `parent`: a verified parent company publishes a centralized source;
            - `affiliate`: another entity in the same corporate group publishes the source;
            - `regional_entity`: a regional operating or contracting entity publishes the source;
            - `authorized_host`: an authorized status, trust, or document host publishes the source;
            - `public_authority`: a public authority publishes the source.

            ## Admission behavior

            The catalog guard applies a changed-record gate:

            - same-product-domain sources remain compatible with existing records;
            - newly added or modified cross-domain sources require complete publisher attribution and verified applicability;
            - existing cross-domain records are inventoried by the report-only source attribution audit and can be backfilled in bounded catalog work packages;
            - incomplete or ambiguous attribution fails closed for changed records.

            Run the report-only audit with:

            ```bash
            python -m tools.openva.source_attribution audit --output source-attribution-audit.json
            ```

            `source-maintenance-report.yml` includes this audit in its maintenance artifact bundle.

            ## Public presentation

            The vendor detail surface displays, before a cross-domain link:

            - the source publisher;
            - the relationship to the selected product;
            - the destination domain;
            - the covered product;
            - the recorded coverage basis; and
            - a disclosure containing the applicability statement and evidence link.

            CSV, SQLite, site JSON, and selected-source JSON exports preserve the same structured metadata.
            '''
        ),
    )


def write_tests() -> None:
    write_text(
        "tests/test_source_attribution.py",
        textwrap.dedent(
            '''
            import json
            import runpy
            from pathlib import Path

            import yaml
            from jsonschema import Draft202012Validator, FormatChecker

            from tools.openva.catalog_guard import validate_changed_source_attribution
            from tools.openva.source_attribution import (
                build_source_attribution_report,
                classify_source,
                source_requires_attribution,
                validate_source_attribution,
            )

            ROOT = Path(__file__).resolve().parents[1]
            ACUITY_SOURCE_DIR = ROOT / "data/vendors/acuity-scheduling/sources"


            def load_yaml(path: Path):
                return yaml.safe_load(path.read_text(encoding="utf-8"))


            def test_acuity_cross_domain_sources_have_explainable_parent_attribution():
                vendor = load_yaml(ROOT / "data/vendors/acuity-scheduling/vendor.yaml")
                for path in sorted(ACUITY_SOURCE_DIR.glob("*.yaml")):
                    source = load_yaml(path)
                    assert source_requires_attribution(source, vendor)
                    assert validate_source_attribution(source, vendor) == []
                    classification, issues = classify_source(source, vendor)
                    assert classification == "attributed_parent"
                    assert issues == []
                    assert source["publisher_attribution"]["publisher_name"] == "Squarespace"
                    assert source["applicability"]["covered_products"] == ["Acuity Scheduling"]


            def test_cross_domain_source_without_applicability_fails_closed():
                vendor = {"official_domains": ["product.example"]}
                source = {
                    "source_url": "https://parent.example/privacy",
                    "source_id": "product-privacy",
                    "vendor_id": "product",
                }
                failures = validate_source_attribution(source, vendor)
                assert "cross-domain source is missing publisher_attribution" in failures
                assert "cross-domain source is missing applicability" in failures
                assert classify_source(source, vendor)[0] == "unproven_cross_domain"


            def test_same_product_domain_remains_backward_compatible():
                vendor = {"official_domains": ["product.example"]}
                source = {"source_url": "https://www.product.example/privacy"}
                assert not source_requires_attribution(source, vendor)
                assert validate_source_attribution(source, vendor) == []
                assert classify_source(source, vendor) == ("same_product_domain", [])


            def test_source_schema_accepts_attribution_and_applicability():
                schema = json.loads((ROOT / "schemas/openva/source-reference.schema.json").read_text(encoding="utf-8"))
                validator = Draft202012Validator(schema, format_checker=FormatChecker())
                for path in sorted(ACUITY_SOURCE_DIR.glob("*.yaml")):
                    errors = sorted(validator.iter_errors(load_yaml(path)), key=lambda error: list(error.path))
                    assert errors == []


            def test_changed_record_gate_accepts_attributed_acuity_sources():
                paths = [path.relative_to(ROOT).as_posix() for path in sorted(ACUITY_SOURCE_DIR.glob("*.yaml"))]
                assert validate_changed_source_attribution(paths, root=ROOT) == []


            def test_audit_is_report_only_and_surfaces_cross_domain_inventory():
                report = build_source_attribution_report(ROOT)
                assert report["report_type"] == "source_publisher_attribution_audit"
                assert report["posture"] == {
                    "network_fetch_performed": False,
                    "writes_repository_state": False,
                    "mutates_catalog": False,
                    "non_advisory": True,
                }
                acuity = [row for row in report["sources"] if row["vendor_id"] == "acuity-scheduling"]
                assert len(acuity) == 5
                assert {row["classification"] for row in acuity} == {"attributed_parent"}


            def test_site_projection_and_export_contract_preserve_attribution():
                source = load_yaml(ACUITY_SOURCE_DIR / "acuity-scheduling-privacy.yaml")
                build_core = runpy.run_path(str(ROOT / "site/build_core.py"))
                compact = build_core["compact_source"](source)
                assert compact["publisher_attribution"]["relationship"] == "parent"
                assert compact["applicability"]["status"] == "verified"

                app = (ROOT / "site/src/app.js").read_text(encoding="utf-8")
                assert "Why this source applies" in app
                assert "Parent-company source" in app
                assert "publisher_attribution" in app
                assert "applicability" in app

                csv_exporter = (
                    ROOT / "adapters/python/openva_csv_export/openva_csv_export/exporter.py"
                ).read_text(encoding="utf-8")
                sqlite_exporter = (
                    ROOT / "adapters/python/openva_sqlite_export/openva_sqlite_export/exporter.py"
                ).read_text(encoding="utf-8")
                for field in ("publisher_attribution", "applicability"):
                    assert f'"{field}"' in csv_exporter
                    assert f'"{field}": "TEXT"' in sqlite_exporter


            def test_source_maintenance_workflow_publishes_attribution_audit():
                workflow = (ROOT / ".github/workflows/source-maintenance-report.yml").read_text(encoding="utf-8")
                assert "python -m tools.openva.source_attribution audit" in workflow
                assert "source-attribution-audit.json" in workflow
            '''
        ),
    )


def main() -> None:
    update_source_schema()
    write_source_attribution_tool()
    patch_catalog_guard()
    patch_site_build()
    patch_site_app()
    patch_site_styles()
    patch_exporters()
    patch_source_maintenance_workflow()
    update_acuity_sources()
    write_documentation()
    write_tests()


if __name__ == "__main__":
    main()
