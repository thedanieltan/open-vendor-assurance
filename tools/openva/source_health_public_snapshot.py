from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_TYPE = "source_health_public_snapshot"
SCHEMA_VERSION = "0.1.0"
SOURCE = "latest-source-health"
SNAPSHOT_TYPE = "artifact_derived"
BUCKETS = ("healthy", "warning", "unavailable", "ambiguous")
SELF_CERTIFYING_FIELDS = {"eligible", "eligible_for_automerge", "tool_recommendation"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_latest_source_health(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != "latest_source_health_index":
        raise ValueError("expected report_type=latest_source_health_index")
    sources = report.get("sources")
    if not isinstance(sources, list):
        raise ValueError("expected sources list")

    rows: list[dict[str, Any]] = []
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("expected each latest source health row to be an object")
        forbidden = sorted(SELF_CERTIFYING_FIELDS.intersection(row))
        if forbidden:
            raise ValueError(f"latest source health row contains self-certifying field(s): {', '.join(forbidden)}")
        required = (
            "vendor_id",
            "source_id",
            "source_url",
            "status",
            "status_bucket",
            "verified_at",
            "run_id",
            "observer",
        )
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ValueError(f"latest source health row missing required field(s): {', '.join(missing)}")
        bucket = str(row.get("status_bucket"))
        if bucket not in BUCKETS:
            raise ValueError(f"unknown status_bucket: {bucket}")
        rows.append(row)
    return rows


def public_health_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_id": str(row["vendor_id"]),
        "source_id": str(row["source_id"]),
        "source_url": str(row["source_url"]),
        "status": str(row["status"]),
        "status_bucket": str(row["status_bucket"]),
        "http_status": row.get("http_status"),
        "final_url": row.get("final_url"),
        "verified_at": str(row["verified_at"]),
        "run_id": str(row["run_id"]),
        "observer": str(row["observer"]),
    }


def bucket_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row["status_bucket"]) for row in rows)
    return {bucket: counts.get(bucket, 0) for bucket in BUCKETS}


def build_source_health_public_snapshot(
    latest_source_health: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    resolved_generated_at = generated_at or now_iso()
    latest_rows = validate_latest_source_health(latest_source_health)
    rows = [public_health_row(row) for row in latest_rows]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": resolved_generated_at,
        "report_type": REPORT_TYPE,
        "source": SOURCE,
        "snapshot_type": SNAPSHOT_TYPE,
        "metadata": {
            "snapshot_notice": (
                "This file is a point-in-time source health snapshot derived from maintenance artifacts. "
                "It is not a permanent guarantee that a source remains reachable or suitable."
            ),
            "non_advisory": True,
            "artifact_derived": True,
            "network_fetch_performed": False,
            "catalog_mutation_performed": False,
            "historical_ledger_committed": False,
            "ui_generated": False,
            "release_policy_changed": False,
        },
        "inputs": {
            "latest_source_health_report_type": latest_source_health.get("report_type"),
            "latest_source_health_generated_at": latest_source_health.get("generated_at"),
            "latest_source_health_snapshot": latest_source_health.get("snapshot", {}),
        },
        "summary": {
            "source_count": len(rows),
            "status_bucket_counts": bucket_counts(rows),
        },
        "health": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-health-public-snapshot")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--latest-source-health", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("public/source-health-snapshot.json"))
    args = parser.parse_args(argv)

    report = build_source_health_public_snapshot(load_json(args.latest_source_health))
    write_json(report, args.output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
