from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "source-health-report.json"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path.relative_to(ROOT)}: expected YAML mapping")
    return data


def source_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/sources/*.yaml"))


def artifact_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/artifacts/*.yaml"))


def classify_source(source: dict[str, Any], path: Path) -> dict[str, Any]:
    source_url = str(source.get("source_url") or "")
    parsed = urlparse(source_url)
    issues: list[str] = []

    if not source_url:
        issues.append("missing_source_url")
    if parsed.scheme not in {"http", "https"}:
        issues.append("non_http_source_url")
    if parsed.scheme == "http":
        issues.append("plain_http_source_url")
    if not parsed.netloc:
        issues.append("missing_source_domain")
    if source.get("access_class") != "public_web":
        issues.append("non_public_web_access_class")
    if source.get("rights_class") != "metadata_only":
        issues.append("unexpected_rights_class")
    if source.get("not_advice") is not True:
        issues.append("missing_not_advice_true")

    return {
        "path": str(path.relative_to(ROOT)),
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "source_url": source_url,
        "source_domain": parsed.netloc.lower(),
        "source_language": source.get("source_language"),
        "access_class": source.get("access_class"),
        "rights_class": source.get("rights_class"),
        "issues": issues,
    }


def build_source_health_report(root: Path = ROOT) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    failures: list[str] = []

    for path in source_paths(root):
        try:
            source = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        sources.append(classify_source(source, path))

    artifact_count = len(artifact_paths(root))
    issue_counter: Counter[str] = Counter(issue for source in sources for issue in source.get("issues", []))
    domain_counter: Counter[str] = Counter(
        source["source_domain"] for source in sources if source.get("source_domain")
    )
    language_counter: Counter[str] = Counter(
        str(source.get("source_language") or "unknown") for source in sources
    )
    type_counter: Counter[str] = Counter(
        str(source.get("source_type") or "unknown") for source in sources
    )
    vendors_by_issue: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        for issue in source.get("issues", []):
            vendor_id = source.get("vendor_id")
            if vendor_id:
                vendors_by_issue[issue].add(str(vendor_id))

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "source_health_inventory",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
        },
        "summary": {
            "vendor_count": len({source.get("vendor_id") for source in sources if source.get("vendor_id")}),
            "source_count": len(sources),
            "artifact_count": artifact_count,
            "sources_with_issues": sum(1 for source in sources if source.get("issues")),
            "parse_failures": len(failures),
        },
        "breakdowns": {
            "issues": dict(sorted(issue_counter.items())),
            "top_domains": dict(domain_counter.most_common(25)),
            "languages": dict(sorted(language_counter.items())),
            "source_types": dict(sorted(type_counter.items())),
            "vendors_by_issue": {
                issue: sorted(vendors) for issue, vendors in sorted(vendors_by_issue.items())
            },
        },
        "failures": failures,
        "sources": sources,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-health")
    parser.add_argument("build", nargs="?", default="build")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fail-on-issues", action="store_true")
    args = parser.parse_args()

    if args.build != "build":
        parser.error("only the 'build' command is supported")

    report = build_source_health_report()
    write_report(report, args.output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))

    if args.fail_on_issues and (
        report["summary"]["sources_with_issues"] or report["summary"]["parse_failures"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
