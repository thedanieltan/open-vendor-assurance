from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT = Path("source-repair-evidence.json")

CONFIRMED_SCAN_REPORT_TYPE = "confirmed_p0_source_refinement_scan"
EVIDENCE_REPORT_TYPE = "p0_source_repair_evidence"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_confirmed_scan(scan: dict[str, Any]) -> list[dict[str, Any]]:
    if scan.get("report_type") != CONFIRMED_SCAN_REPORT_TYPE:
        raise ValueError(f"expected report_type={CONFIRMED_SCAN_REPORT_TYPE}")
    confirmed = scan.get("confirmed_p0")
    if not isinstance(confirmed, list):
        raise ValueError("expected confirmed_p0 list")
    for row in confirmed:
        if not isinstance(row, dict):
            raise ValueError("expected each confirmed_p0 row to be an object")
        required = (
            "vendor_id",
            "source_id",
            "source_url",
            "prior_status",
            "fresh_status",
            "prior_http_status",
            "fresh_http_status",
            "prior_verified_at",
            "fresh_verified_at",
        )
        missing = [field for field in required if field not in row]
        if missing:
            raise ValueError(f"confirmed_p0 row missing required field(s): {', '.join(missing)}")
        status_pair = (row.get("prior_status"), row.get("fresh_status"))
        if status_pair not in {("not_found", "not_found"), ("gone", "gone")}:
            raise ValueError(f"confirmed_p0 row has non-confirmed status pair: {status_pair}")
    return confirmed


def evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_id": row.get("vendor_id"),
        "source_id": row.get("source_id"),
        "source_url": row.get("source_url"),
        "original": {
            "prior": {
                "verification_status": row.get("prior_status"),
                "http_status": row.get("prior_http_status"),
                "final_url": row.get("prior_final_url"),
                "verified_at": row.get("prior_verified_at"),
            },
            "fresh": {
                "verification_status": row.get("fresh_status"),
                "http_status": row.get("fresh_http_status"),
                "final_url": row.get("fresh_final_url"),
                "verified_at": row.get("fresh_verified_at"),
            },
        },
        "replacement": None,
        "proposed_change": None,
    }


def build_source_repair_evidence(scan: dict[str, Any]) -> dict[str, Any]:
    confirmed = validate_confirmed_scan(scan)
    repairs = [evidence_row(row) for row in confirmed]
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": EVIDENCE_REPORT_TYPE,
        "evidence_type": "confirmed_p0_original_source_evidence",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "contains_replacement_evidence": False,
            "contains_automerge_recommendation": False,
            "non_advisory": True,
        },
        "inputs": {
            "scan_report_type": scan.get("report_type"),
            "scan_generated_at": scan.get("generated_at"),
            "prior_report_run_id": scan.get("prior_report_run_id"),
            "fresh_report_run_id": scan.get("fresh_report_run_id"),
            "prior_report_generated_at": scan.get("prior_report_generated_at"),
            "fresh_report_generated_at": scan.get("fresh_report_generated_at"),
        },
        "repairs": repairs,
        "summary": {
            "repair_evidence_count": len(repairs),
            "contains_replacement_evidence": False,
            "contains_automerge_recommendation": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--confirmed-p0-scan", type=Path, required=True)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    args = parser.parse_args()
    if args.command == "build":
        report = build_source_repair_evidence(load_json(args.confirmed_p0_scan))
        write_report(report, args.output)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
