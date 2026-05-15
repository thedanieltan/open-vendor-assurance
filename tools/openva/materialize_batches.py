from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.catalog_batch import generate_catalog_batch, load_yaml
from tools.openva.indexes import build_indexes

ROOT = Path(__file__).resolve().parents[2]
LANES_PATH = ROOT / "config/materialization-lanes.yaml"
DEFAULT_REPORT_PATH = ROOT / "materialization-report.json"


def load_lanes(path: Path = LANES_PATH) -> dict[str, Any]:
    data = load_yaml(path)
    lanes = data.get("lanes")
    if not isinstance(lanes, dict):
        raise ValueError("materialization lanes config must contain a lanes mapping")
    return data


def manifest_vendor_ids(manifest_path: Path) -> list[str]:
    manifest = load_yaml(manifest_path)
    return [str(vendor["vendor_id"]) for vendor in manifest.get("vendors", [])]


def vendor_is_materialized(vendor_id: str) -> bool:
    return (ROOT / "data" / "vendors" / vendor_id / "vendor.yaml").exists()


def lane_manifest_paths(lane: str | None, explicit_manifests: list[str]) -> list[Path]:
    if explicit_manifests:
        return [ROOT / manifest for manifest in explicit_manifests]

    config = load_lanes()
    lanes = config["lanes"]
    if lane is None:
        manifests: list[str] = []
        for lane_config in lanes.values():
            manifests.extend(lane_config.get("manifests", []))
        return [ROOT / manifest for manifest in manifests]

    if lane not in lanes:
        raise ValueError(f"unknown lane {lane!r}; expected one of {sorted(lanes)}")
    return [ROOT / manifest for manifest in lanes[lane].get("manifests", [])]


def plan_materialization(lane: str | None, explicit_manifests: list[str]) -> dict[str, Any]:
    manifests = lane_manifest_paths(lane, explicit_manifests)
    manifest_reports: list[dict[str, Any]] = []
    missing_manifest_paths: list[str] = []

    for manifest_path in manifests:
        rel = str(manifest_path.relative_to(ROOT))
        if not manifest_path.exists():
            missing_manifest_paths.append(rel)
            continue
        vendor_ids = manifest_vendor_ids(manifest_path)
        already_materialized = [vendor_id for vendor_id in vendor_ids if vendor_is_materialized(vendor_id)]
        pending = [vendor_id for vendor_id in vendor_ids if not vendor_is_materialized(vendor_id)]
        manifest_reports.append(
            {
                "manifest": rel,
                "vendor_count": len(vendor_ids),
                "pending_count": len(pending),
                "already_materialized_count": len(already_materialized),
                "pending_vendor_ids": pending,
                "already_materialized_vendor_ids": already_materialized,
            }
        )

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "materialization_plan",
        "posture": {
            "public_sources_only": True,
            "non_advisory": True,
            "raw_documents_mirrored": False,
            "gated_materials_excluded": True,
        },
        "lane": lane or "all",
        "summary": {
            "manifest_count": len(manifest_reports),
            "missing_manifest_count": len(missing_manifest_paths),
            "pending_vendor_count": sum(item["pending_count"] for item in manifest_reports),
            "already_materialized_vendor_count": sum(
                item["already_materialized_count"] for item in manifest_reports
            ),
        },
        "missing_manifests": missing_manifest_paths,
        "manifests": manifest_reports,
    }


def materialize(lane: str | None, explicit_manifests: list[str], *, build: bool) -> dict[str, Any]:
    plan = plan_materialization(lane, explicit_manifests)
    generated_manifests: list[str] = []
    skipped_manifests: list[str] = []
    failed_manifests: list[dict[str, Any]] = []

    for item in plan["manifests"]:
        manifest = item["manifest"]
        if item["pending_count"] == 0:
            skipped_manifests.append(manifest)
            continue
        result = generate_catalog_batch(ROOT / manifest, force=False, build=False)
        if result == 0:
            generated_manifests.append(manifest)
        else:
            failed_manifests.append({"manifest": manifest, "exit_code": result})

    if build and generated_manifests:
        build_indexes()

    plan["materialization"] = {
        "generated_manifests": generated_manifests,
        "skipped_manifests": skipped_manifests,
        "failed_manifests": failed_manifests,
    }
    return plan


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-materialize-batches")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("plan", "run"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--lane", default=None)
        sub.add_argument("--manifest", action="append", default=[])
        sub.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)

    args = parser.parse_args()

    if args.command == "plan":
        report = plan_materialization(args.lane, args.manifest)
        write_report(report, args.output)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0

    if args.command == "run":
        report = materialize(args.lane, args.manifest, build=True)
        write_report(report, args.output)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        failures = report.get("materialization", {}).get("failed_manifests", [])
        return 1 if failures else 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
