from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_TYPE = "latest_source_health_index"
SCHEMA_VERSION = "0.1.0"

HEALTHY_STATUSES = {"ok", "redirected"}
UNAVAILABLE_STATUSES = {"not_found", "gone"}
WARNING_STATUSES = {
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "suspect_inferred_url",
}
AMBIGUOUS_STATUSES = {
    "bot_protected",
    "client_error",
    "forbidden_unknown",
    "gated_or_login_required",
    "rate_limited",
    "server_error",
    "unreachable",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def status_bucket(status: str) -> str:
    if status in HEALTHY_STATUSES:
        return "healthy"
    if status in UNAVAILABLE_STATUSES:
        return "unavailable"
    if status in WARNING_STATUSES:
        return "warning"
    if status in AMBIGUOUS_STATUSES:
        return "ambiguous"
    return "ambiguous"


def validate_source_observation_ledger(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != "source_observation_ledger":
        raise ValueError("expected report_type=source_observation_ledger")
    observations = report.get("observations")
    if not isinstance(observations, list):
        raise ValueError("expected observations list")

    rows: list[dict[str, Any]] = []
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("expected each observation row to be an object")
        required = (
            "vendor_id",
            "source_id",
            "source_url",
            "status",
            "verified_at",
            "run_id",
            "observer",
        )
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ValueError(f"source observation row missing required field(s): {', '.join(missing)}")
        rows.append(row)
    return rows


def latest_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_source: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in observations:
        key = (str(row["vendor_id"]), str(row["source_id"]), str(row["source_url"]))
        current = latest_by_source.get(key)
        if current is None or observation_sort_key(row) > observation_sort_key(current):
            latest_by_source[key] = row
    return sorted(latest_by_source.values(), key=lambda item: (item["vendor_id"], item["source_id"], item["source_url"]))


def observation_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("verified_at") or ""),
        str(row.get("run_id") or ""),
        str(row.get("observation_id") or ""),
    )


def health_row(observation: dict[str, Any]) -> dict[str, Any]:
    status = str(observation["status"])
    return {
        "schema_version": SCHEMA_VERSION,
        "vendor_id": str(observation["vendor_id"]),
        "source_id": str(observation["source_id"]),
        "source_url": str(observation["source_url"]),
        "status": status,
        "status_bucket": status_bucket(status),
        "http_status": observation.get("http_status"),
        "final_url": observation.get("final_url"),
        "verified_at": str(observation["verified_at"]),
        "run_id": str(observation["run_id"]),
        "observer": str(observation["observer"]),
        "observation_id": observation.get("observation_id"),
    }


def build_latest_source_health_index(
    source_observation_ledger: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    resolved_generated_at = generated_at or now_iso()
    observations = validate_source_observation_ledger(source_observation_ledger)
    rows = [health_row(observation) for observation in latest_observations(observations)]
    status_counts = Counter(row["status"] for row in rows)
    bucket_counts = Counter(row["status_bucket"] for row in rows)
    latest_verified_at = max((row["verified_at"] for row in rows), default=None)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": resolved_generated_at,
        "report_type": REPORT_TYPE,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "site_ui_generated": False,
            "historical_ledger_committed": False,
            "non_advisory": True,
        },
        "inputs": {
            "source_observation_ledger_report_type": source_observation_ledger.get("report_type"),
            "source_observation_ledger_generated_at": source_observation_ledger.get("generated_at"),
            "source_observation_ledger_observations": len(observations),
        },
        "snapshot": {
            "generated_at": resolved_generated_at,
            "source_observation_ledger_generated_at": source_observation_ledger.get("generated_at"),
            "latest_verified_at": latest_verified_at,
            "latest_source_health_records": len(rows),
        },
        "summary": {
            "observations_seen": len(observations),
            "latest_source_health_records": len(rows),
            "superseded_observations": len(observations) - len(rows),
            "status_counts": dict(sorted(status_counts.items())),
            "status_bucket_counts": dict(sorted(bucket_counts.items())),
        },
        "sources": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-latest-health")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--source-observation-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("latest-source-health.json"))
    args = parser.parse_args(argv)

    report = build_latest_source_health_index(load_json(args.source_observation_ledger))
    write_json(report, args.output)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
