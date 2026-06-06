from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.paths import relative_repo_path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "coverage-audit-report.json"

CORE_ARTIFACT_TYPES = (
    "dpa",
    "subprocessors_list",
    "privacy_notice",
    "security_page",
    "trust_center",
    "compliance_page",
)

HIGH_VALUE_ARTIFACT_TYPES = frozenset(CORE_ARTIFACT_TYPES)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{relative_repo_path(path, ROOT)}: expected YAML mapping")
    return data


def vendor_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/vendor.yaml"))


def artifact_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/artifacts/*.yaml"))


def source_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/sources/*.yaml"))


def full_coverage_claims(source: dict[str, Any]) -> list[dict[str, Any]]:
    claims = source.get("coverage_claims", []) or []
    if not isinstance(claims, list):
        return []
    return [
        claim
        for claim in claims
        if isinstance(claim, dict)
        and claim.get("coverage_type") in {"contains", "links_to"}
        and isinstance(claim.get("role"), str)
        and claim.get("role")
    ]


def source_roles(source: dict[str, Any]) -> set[str]:
    roles = {str(source["source_type"])} if source.get("source_type") else set()
    roles.update(str(claim["role"]) for claim in full_coverage_claims(source))
    return roles


def duplicate_source_url_count(sources: list[dict[str, Any]]) -> int:
    counts = Counter(str(source.get("source_url", "")).rstrip("/") for source in sources if source.get("source_url"))
    return sum(count - 1 for count in counts.values() if count > 1)


def build_coverage_audit(root: Path = ROOT) -> dict[str, Any]:
    vendors: dict[str, dict[str, Any]] = {}
    artifacts_by_vendor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sources_by_vendor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: list[str] = []

    for path in vendor_paths(root):
        try:
            vendor = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        vendor_id = str(vendor.get("vendor_id") or path.parent.name)
        vendors[vendor_id] = {
            "vendor_id": vendor_id,
            "display_name": vendor.get("display_name"),
            "legal_name": vendor.get("legal_name"),
            "headquarters_country": vendor.get("headquarters_country"),
            "regions_served": vendor.get("regions_served", []),
            "vendor_categories": vendor.get("vendor_categories", []),
            "path": relative_repo_path(path, root),
        }

    for path in artifact_paths(root):
        try:
            artifact = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        vendor_id = str(artifact.get("vendor_id") or path.parents[1].name)
        artifacts_by_vendor[vendor_id].append(
            {
                "artifact_id": artifact.get("artifact_id"),
                "artifact_type": artifact.get("artifact_type"),
                "canonical_url": artifact.get("canonical_url"),
                "path": relative_repo_path(path, root),
            }
        )

    for path in source_paths(root):
        try:
            source = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        vendor_id = str(source.get("vendor_id") or path.parents[1].name)
        sources_by_vendor[vendor_id].append(
            {
                "source_id": source.get("source_id"),
                "source_type": source.get("source_type"),
                "source_url": source.get("source_url"),
                "coverage_claims": source.get("coverage_claims", []),
                "path": relative_repo_path(path, root),
            }
        )

    vendor_reports: list[dict[str, Any]] = []
    artifact_type_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    region_counter: Counter[str] = Counter()

    for vendor_id, vendor in sorted(vendors.items()):
        artifacts = artifacts_by_vendor.get(vendor_id, [])
        sources = sources_by_vendor.get(vendor_id, [])
        artifact_types = sorted(
            {str(artifact.get("artifact_type")) for artifact in artifacts if artifact.get("artifact_type")}
        )
        primary_source_types = sorted({str(source.get("source_type")) for source in sources if source.get("source_type")})
        claim_roles = sorted({str(claim["role"]) for source in sources for claim in full_coverage_claims(source)})
        covered_roles = sorted({role for source in sources for role in source_roles(source)})
        unique_source_locations = len({str(source.get("source_url", "")).rstrip("/") for source in sources if source.get("source_url")})
        roles_by_url: dict[str, set[str]] = defaultdict(set)
        for source in sources:
            source_url = str(source.get("source_url", "")).rstrip("/")
            if source_url:
                roles_by_url[source_url].update(source_roles(source))
        artifact_type_set = set(artifact_types)
        missing_core = [artifact_type for artifact_type in CORE_ARTIFACT_TYPES if artifact_type not in artifact_type_set]
        present_core = [artifact_type for artifact_type in CORE_ARTIFACT_TYPES if artifact_type in artifact_type_set]

        for artifact_type in artifact_types:
            artifact_type_counter[artifact_type] += 1
        for category in vendor.get("vendor_categories", []):
            category_counter[str(category)] += 1
        for region in vendor.get("regions_served", []):
            region_counter[str(region)] += 1

        depth_score = round(len(present_core) / len(CORE_ARTIFACT_TYPES), 3)
        vendor_reports.append(
            {
                **vendor,
                "artifact_count": len(artifacts),
                "artifact_types": artifact_types,
                "unique_source_locations": unique_source_locations,
                "primary_source_type_coverage": primary_source_types,
                "coverage_claim_role_coverage": claim_roles,
                "covered_roles": covered_roles,
                "roles_covered_via_claims": sum(len(full_coverage_claims(source)) for source in sources),
                "roles_covered_via_same_source_url": sorted({role for roles in roles_by_url.values() if len(roles) > 1 for role in roles}),
                "duplicate_source_url_count": duplicate_source_url_count(sources),
                "core_artifacts_present": present_core,
                "core_artifacts_missing": missing_core,
                "depth_score": depth_score,
                "depth_tier": depth_tier(depth_score),
            }
        )

    depth_counter = Counter(report["depth_tier"] for report in vendor_reports)
    vendors_with_dpa = sum(1 for report in vendor_reports if "dpa" in report["artifact_types"])
    vendors_with_subprocessors = sum(
        1 for report in vendor_reports if "subprocessors_list" in report["artifact_types"]
    )
    vendors_with_at_least_three_core = sum(
        1 for report in vendor_reports if len(report["core_artifacts_present"]) >= 3
    )
    source_role_counter = Counter(role for report in vendor_reports for role in report["covered_roles"])
    coverage_claim_role_counter = Counter(role for report in vendor_reports for role in report["coverage_claim_role_coverage"])

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "breadth_depth_coverage_audit",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
            "coverage_scores_are_catalog_completeness_only": True,
        },
        "targets": {
            "minimum_materialized_vendors_for_public_usefulness": 150,
            "near_term_materialized_vendors": 250,
            "core_artifact_types": list(CORE_ARTIFACT_TYPES),
            "tier_1_vendor_minimum_core_artifacts": 4,
            "general_vendor_minimum_core_artifacts": 2,
        },
        "summary": {
            "vendor_count": len(vendors),
            "artifact_count": sum(len(items) for items in artifacts_by_vendor.values()),
            "unique_source_locations": sum(report["unique_source_locations"] for report in vendor_reports),
            "primary_source_type_coverage_count": sum(len(report["primary_source_type_coverage"]) for report in vendor_reports),
            "coverage_claim_role_coverage_count": sum(len(report["coverage_claim_role_coverage"]) for report in vendor_reports),
            "roles_covered_via_claims": sum(report["roles_covered_via_claims"] for report in vendor_reports),
            "duplicate_source_url_count": sum(report["duplicate_source_url_count"] for report in vendor_reports),
            "vendors_with_dpa": vendors_with_dpa,
            "vendors_with_subprocessors_list": vendors_with_subprocessors,
            "vendors_with_at_least_three_core_artifacts": vendors_with_at_least_three_core,
            "parse_failures": len(failures),
        },
        "breakdowns": {
            "artifact_types": dict(sorted(artifact_type_counter.items())),
            "covered_roles": dict(sorted(source_role_counter.items())),
            "coverage_claim_roles": dict(sorted(coverage_claim_role_counter.items())),
            "depth_tiers": dict(sorted(depth_counter.items())),
            "vendor_categories": dict(category_counter.most_common()),
            "regions_served": dict(region_counter.most_common()),
        },
        "gaps": {
            "vendors_missing_dpa": sorted(
                report["vendor_id"] for report in vendor_reports if "dpa" not in report["artifact_types"]
            ),
            "vendors_missing_subprocessors_list": sorted(
                report["vendor_id"]
                for report in vendor_reports
                if "subprocessors_list" not in report["artifact_types"]
            ),
            "vendors_with_single_artifact": sorted(
                report["vendor_id"] for report in vendor_reports if report["artifact_count"] == 1
            ),
            "vendors_below_three_core_artifacts": sorted(
                report["vendor_id"]
                for report in vendor_reports
                if len(report["core_artifacts_present"]) < 3
            ),
        },
        "failures": failures,
        "vendors": vendor_reports,
    }


def depth_tier(score: float) -> str:
    if score >= 0.667:
        return "strong"
    if score >= 0.333:
        return "partial"
    if score > 0:
        return "thin"
    return "none"


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-coverage-audit")
    parser.add_argument("build", nargs="?", default="build")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fail-on-parse-failures", action="store_true")
    args = parser.parse_args()

    if args.build != "build":
        parser.error("only the 'build' command is supported")

    report = build_coverage_audit()
    write_report(report, args.output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(json.dumps(report["breakdowns"].get("artifact_types", {}), indent=2, sort_keys=True))

    if args.fail_on_parse_failures and report["summary"]["parse_failures"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
