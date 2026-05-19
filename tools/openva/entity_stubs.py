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
DEFAULT_OUTPUT = ROOT / "entity-stub-report.json"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{relative_repo_path(path, ROOT)}: expected YAML mapping")
    return data


def legal_entity_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/legal_entities/*.yaml"))


def source_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/sources/*.yaml"))


def build_entity_stub_report(root: Path = ROOT) -> dict[str, Any]:
    stubs: list[dict[str, Any]] = []
    sources_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: list[str] = []

    for path in source_paths(root):
        try:
            source = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        entity_id = source.get("entity_id")
        if entity_id:
            sources_by_entity[str(entity_id)].append(
                {
                    "source_id": source.get("source_id"),
                    "source_authority_class": source.get("source_authority_class"),
                    "path": relative_repo_path(path, root),
                }
            )

    for path in legal_entity_paths(root):
        try:
            entity = load_yaml(path)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if entity.get("catalog_status") != "stub":
            continue
        entity_id = str(entity.get("entity_id") or path.stem)
        candidate_sources = sources_by_entity.get(entity_id, [])
        stubs.append(
            {
                "entity_id": entity_id,
                "vendor_id": entity.get("vendor_id"),
                "legal_name": entity.get("legal_name"),
                "jurisdiction": entity.get("jurisdiction"),
                "verified_observed_at": entity.get("verified_observed_at"),
                "path": relative_repo_path(path, root),
                "possible_verification_source_ids": sorted(
                    str(source["source_id"]) for source in candidate_sources if source.get("source_id")
                ),
            }
        )

    by_vendor = Counter(str(stub.get("vendor_id") or "unknown") for stub in stubs)
    observed_dates = sorted(str(stub["verified_observed_at"]) for stub in stubs if stub.get("verified_observed_at"))
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "entity_stub_inventory",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
            "promotion_sla_created": False,
        },
        "summary": {
            "stub_count": len(stubs),
            "vendors_with_stubs": len(by_vendor),
            "oldest_stub_verified_observed_at": observed_dates[0] if observed_dates else None,
            "stubs_with_possible_verification_sources": sum(1 for stub in stubs if stub["possible_verification_source_ids"]),
            "parse_failures": len(failures),
        },
        "breakdowns": {"stubs_by_vendor": dict(sorted(by_vendor.items()))},
        "failures": failures,
        "stubs": sorted(stubs, key=lambda item: (str(item.get("vendor_id")), str(item.get("entity_id")))),
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-entity-stubs")
    parser.add_argument("build", nargs="?", default="build")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fail-on-parse-failures", action="store_true")
    args = parser.parse_args()

    if args.build != "build":
        parser.error("only the 'build' command is supported")

    report = build_entity_stub_report()
    write_report(report, args.output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))

    if args.fail_on_parse_failures and report["summary"]["parse_failures"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
