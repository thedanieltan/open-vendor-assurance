from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT
from tools.openva.source_discovery import unavailable_lifecycle

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "catalog_source_completion_report"
EXPECTED_GROUPS: dict[str, frozenset[str]] = {
    "privacy_notice": frozenset({"privacy_notice"}),
    "terms_of_service": frozenset({"terms_of_service"}),
    "security_assurance": frozenset({"security_page", "trust_center", "compliance_page"}),
    "dpa": frozenset({"dpa"}),
    "subprocessors_list": frozenset({"subprocessors_list"}),
    "status_page": frozenset({"status_page"}),
    "compliance": frozenset({"compliance_page", "certification_reference"}),
}
CORE_GROUPS = frozenset(
    {
        "privacy_notice",
        "terms_of_service",
        "security_assurance",
        "dpa",
        "subprocessors_list",
        "status_page",
    }
)
MANDATORY_LIVE_GROUPS = frozenset({"privacy_notice"})
MINIMUM_LIVE_CORE_GROUPS = 2


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML mapping")
    return data


def current_unavailable_types(vendor_dir: Path, *, today: date) -> set[str]:
    result: set[str] = set()
    for path in sorted((vendor_dir / "unavailable_sources").glob("*.yaml")):
        record = load_yaml(path)
        source_type = record.get("source_type")
        if isinstance(source_type, str) and unavailable_lifecycle(record, today=today) == "not_due":
            result.add(source_type)
    return result


def canonical_coverage(vendor_dir: Path) -> tuple[set[str], set[str]]:
    direct_types: set[str] = set()
    covered_roles: set[str] = set()
    for path in sorted((vendor_dir / "sources").glob("*.yaml")):
        record = load_yaml(path)
        source_type = record.get("source_type")
        if isinstance(source_type, str):
            direct_types.add(source_type)
            covered_roles.add(source_type)
        claims = record.get("coverage_claims") or []
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if (
                isinstance(claim, dict)
                and claim.get("coverage_type") in {"contains", "links_to"}
                and isinstance(claim.get("role"), str)
                and claim.get("role")
            ):
                covered_roles.add(str(claim["role"]))
    return direct_types, covered_roles


def group_resolution(
    group: str,
    covered_roles: set[str],
    unavailable_types: set[str],
    expected_types: frozenset[str],
) -> str:
    if covered_roles & expected_types:
        return "canonical_source_or_claim"
    if group in MANDATORY_LIVE_GROUPS:
        return "unresolved"
    if unavailable_types & expected_types:
        return "evidenced_unavailable"
    return "unresolved"


def vendor_completion(vendor_dir: Path, *, today: date) -> dict[str, Any]:
    vendor = load_yaml(vendor_dir / "vendor.yaml")
    direct_types, covered_roles = canonical_coverage(vendor_dir)
    unavailable = current_unavailable_types(vendor_dir, today=today)
    resolutions = {
        group: group_resolution(group, covered_roles, unavailable, expected)
        for group, expected in EXPECTED_GROUPS.items()
    }
    unresolved = [group for group, resolution in resolutions.items() if resolution == "unresolved"]
    live_core_groups = sorted(
        group for group in CORE_GROUPS if covered_roles & EXPECTED_GROUPS[group]
    )
    privacy_live = bool(covered_roles & EXPECTED_GROUPS["privacy_notice"])
    live_breadth_complete = len(live_core_groups) >= MINIMUM_LIVE_CORE_GROUPS
    completion_failures: list[str] = []
    if not privacy_live:
        completion_failures.append("privacy_notice_requires_live_source")
    if not live_breadth_complete:
        completion_failures.append("minimum_live_core_group_breadth_not_met")
    complete = not unresolved and not completion_failures
    return {
        "vendor_id": str(vendor.get("vendor_id") or vendor_dir.name),
        "display_name": vendor.get("display_name"),
        "group_resolutions": resolutions,
        "canonical_source_types": sorted(direct_types),
        "canonical_covered_roles": sorted(covered_roles),
        "current_unavailable_source_types": sorted(unavailable),
        "live_core_groups": live_core_groups,
        "live_core_group_count": len(live_core_groups),
        "privacy_live": privacy_live,
        "live_breadth_complete": live_breadth_complete,
        "unresolved_groups": unresolved,
        "completion_failures": completion_failures,
        "complete": complete,
        "not_advice": True,
    }


def build_report(
    root: Path = ROOT, *, today: date | None = None, generated_at: str | None = None
) -> dict[str, Any]:
    today = today or date.today()
    vendors = [
        vendor_completion(path, today=today)
        for path in sorted((root / "data" / "vendors").glob("*"))
        if path.is_dir() and (path / "vendor.yaml").exists()
    ]
    vendors.sort(key=lambda row: row["vendor_id"])
    unresolved_by_group = {
        group: sorted(row["vendor_id"] for row in vendors if group in row["unresolved_groups"])
        for group in EXPECTED_GROUPS
    }
    resolution_counts = Counter(
        resolution
        for row in vendors
        for resolution in row["group_resolutions"].values()
    )
    insufficient_live_breadth = sorted(
        row["vendor_id"] for row in vendors if not row["live_breadth_complete"]
    )
    missing_live_privacy = sorted(row["vendor_id"] for row in vendors if not row["privacy_live"])
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "generated_at": generated_at
        or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "as_of_date": today.isoformat(),
        "completion_rule": {
            "expected_source_groups": {key: sorted(value) for key, value in EXPECTED_GROUPS.items()},
            "core_groups": sorted(CORE_GROUPS),
            "mandatory_live_groups": sorted(MANDATORY_LIVE_GROUPS),
            "minimum_live_core_groups": MINIMUM_LIVE_CORE_GROUPS,
            "source_or_evidenced_unavailable_groups": sorted(set(EXPECTED_GROUPS) - set(MANDATORY_LIVE_GROUPS)),
            "accepted_coverage_claim_types": ["contains", "links_to"],
            "public_sources_only": True,
            "unavailable_states_are_bounded_discovery_not_nonexistence_claims": True,
            "not_advice": True,
        },
        "summary": {
            "vendor_count": len(vendors),
            "group_cell_count": len(vendors) * len(EXPECTED_GROUPS),
            "complete_vendor_count": sum(row["complete"] for row in vendors),
            "incomplete_vendor_count": sum(not row["complete"] for row in vendors),
            "unresolved_group_count": sum(len(row["unresolved_groups"]) for row in vendors),
            "missing_live_privacy_count": len(missing_live_privacy),
            "insufficient_live_breadth_count": len(insufficient_live_breadth),
            "canonical_group_resolution_count": resolution_counts["canonical_source_or_claim"],
            "evidenced_unavailable_group_resolution_count": resolution_counts["evidenced_unavailable"],
            "unresolved_by_group_count": {
                group: len(vendor_ids) for group, vendor_ids in unresolved_by_group.items()
            },
        },
        "unresolved_by_group": unresolved_by_group,
        "missing_live_privacy": missing_live_privacy,
        "insufficient_live_breadth": insufficient_live_breadth,
        "vendors": vendors,
        "not_advice": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-catalog-source-completion")
    parser.add_argument("command", choices={"build", "check"})
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("catalog-source-completion.json"))
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args(argv)
    report = build_report(args.root, today=args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    if args.command == "check" and report["summary"]["incomplete_vendor_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
