
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
                args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "
", encoding="utf-8")
                print(json.dumps(report["summary"], indent=2, sort_keys=True))
                if args.fail_on_unproven and (
                    report["summary"]["unresolved_cross_domain_source_count"]
                    or report["summary"]["pipeline_failure_count"]
                ):
                    return 1
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
