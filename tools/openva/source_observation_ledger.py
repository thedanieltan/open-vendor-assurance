from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

REPORT_TYPE = "source_observation_ledger"
SCHEMA_VERSION = "0.1.0"
DEFAULT_OBSERVER = "source-verification-report"


@dataclass(frozen=True)
class LedgerBuildResult:
    records: list[dict[str, Any]]
    duplicates: int


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def validate_source_verification_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("report_type") != "source_verification_report":
        raise ValueError("expected report_type=source_verification_report")
    sources = report.get("sources")
    if not isinstance(sources, list):
        raise ValueError("expected sources list")
    rows: list[dict[str, Any]] = []
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("expected each source verification row to be an object")
        required = ("vendor_id", "source_id", "source_url", "verification_status")
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ValueError(f"source verification row missing required field(s): {', '.join(missing)}")
        rows.append(row)
    return rows


def observation_id(
    *,
    vendor_id: str,
    source_id: str,
    source_url: str,
    verified_at: str,
    run_id: str,
) -> str:
    digest = sha256(
        "\n".join([vendor_id, source_id, source_url, verified_at, run_id]).encode("utf-8")
    ).hexdigest()[:16]
    return f"{vendor_id}-{source_id}-{digest}"


def observation_record(row: dict[str, Any], *, verified_at: str, run_id: str, observer: str) -> dict[str, Any]:
    vendor_id = str(row["vendor_id"])
    source_id = str(row["source_id"])
    source_url = str(row["source_url"])
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id(
            vendor_id=vendor_id,
            source_id=source_id,
            source_url=source_url,
            verified_at=verified_at,
            run_id=run_id,
        ),
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_url": source_url,
        "status": str(row["verification_status"]),
        "http_status": row.get("http_status"),
        "final_url": row.get("final_url"),
        "verified_at": verified_at,
        "run_id": run_id,
        "observer": observer,
    }


def dedupe_records(records: list[dict[str, Any]]) -> LedgerBuildResult:
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicates = 0
    for record in records:
        key = (
            record["vendor_id"],
            record["source_id"],
            record["source_url"],
            record["status"],
            record.get("http_status"),
            record.get("final_url"),
            record["verified_at"],
            record["run_id"],
            record["observer"],
        )
        if key in seen:
            duplicates += 1
            continue
        seen[key] = record
    return LedgerBuildResult(
        sorted(seen.values(), key=lambda item: (item["vendor_id"], item["source_id"], item["source_url"])),
        duplicates,
    )


def build_source_observation_ledger(
    source_verification_report: dict[str, Any],
    *,
    run_id: str,
    observer: str = DEFAULT_OBSERVER,
    generated_at: str | None = None,
) -> dict[str, Any]:
    rows = validate_source_verification_report(source_verification_report)
    verified_at = source_verification_report.get("generated_at")
    if not isinstance(verified_at, str) or not verified_at:
        raise ValueError("source verification report missing generated_at")
    if not run_id:
        raise ValueError("run_id is required")
    if not observer:
        raise ValueError("observer is required")

    raw_records = [
        observation_record(row, verified_at=verified_at, run_id=run_id, observer=observer)
        for row in rows
    ]
    result = dedupe_records(raw_records)
    status_counts = Counter(record["status"] for record in result.records)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": REPORT_TYPE,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "inputs": {
            "source_verification_report_type": source_verification_report.get("report_type"),
            "source_verification_generated_at": verified_at,
            "run_id": run_id,
            "observer": observer,
        },
        "summary": {
            "source_verification_rows_seen": len(rows),
            "observation_records": len(result.records),
            "duplicate_records_deduplicated": result.duplicates,
            "status_counts": dict(sorted(status_counts.items())),
        },
        "observations": result.records,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    inputs = report["inputs"]
    status_counts = summary.get("status_counts", {})

    lines = [
        "# OpenVA Source Observation Ledger",
        "",
        "This artifact records source verification observations from a source maintenance run.",
        "",
        "It is operational metadata only. It is not legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        f"- Source verification rows seen: `{summary['source_verification_rows_seen']}`",
        f"- Observation records: `{summary['observation_records']}`",
        f"- Duplicate records deduplicated: `{summary['duplicate_records_deduplicated']}`",
        "",
        "## Inputs",
        "",
        f"- Source verification report type: `{inputs['source_verification_report_type']}`",
        f"- Source verification generated at: `{inputs['source_verification_generated_at']}`",
        f"- Run ID: `{inputs['run_id']}`",
        f"- Observer: `{inputs['observer']}`",
        "",
        "## Status Counts",
        "",
    ]
    if status_counts:
        lines.extend(f"- `{status}`: `{count}`" for status, count in sorted(status_counts.items()))
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Guardrails",
        "",
        "- Builds from an existing source-verification-report.json artifact.",
        "- Does not perform live network fetches.",
        "- Does not mutate catalog files.",
        "- Does not open repair PRs.",
        "- Does not enable automerge.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-observation-ledger")
    parser.add_argument("command", choices={"build"})
    parser.add_argument("--source-verification-report", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observer", default=DEFAULT_OBSERVER)
    parser.add_argument("--output", type=Path, default=Path("source-observation-ledger.json"))
    parser.add_argument("--summary-md", type=Path)
    args = parser.parse_args(argv)

    report = build_source_observation_ledger(
        load_json(args.source_verification_report),
        run_id=args.run_id,
        observer=args.observer,
    )
    write_json(report, args.output)
    if args.summary_md:
        write_markdown(report, args.summary_md)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
