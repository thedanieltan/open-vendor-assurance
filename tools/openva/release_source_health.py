from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_TYPE = "release_source_health_readiness"
SCHEMA_VERSION = "0.1.0"
DEFAULT_MAX_VERIFICATION_AGE_HOURS = 168

WARN_STATUSES = (
    "bot_protected",
    "forbidden_unknown",
    "gated_or_login_required",
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "suspect_inferred_url",
)


@dataclass(frozen=True)
class LoadedReport:
    path: str
    present: bool
    report_type: str | None
    generated_at: str | None
    data: dict[str, Any] | None


def load_optional_json(path: Path) -> LoadedReport:
    if not path.exists():
        return LoadedReport(path.as_posix(), False, None, None, None)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return LoadedReport(
        path.as_posix(),
        True,
        str(data.get("report_type") or ""),
        data.get("generated_at") if isinstance(data.get("generated_at"), str) else None,
        data,
    )


def parse_generated_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def verification_status_counts(report: dict[str, Any] | None) -> dict[str, int]:
    if not report:
        return {}
    breakdowns = report.get("breakdowns")
    if isinstance(breakdowns, dict):
        statuses = breakdowns.get("verification_statuses")
        if isinstance(statuses, dict):
            return {str(key): int(value) for key, value in statuses.items()}
    sources = report.get("sources")
    if isinstance(sources, list):
        counts: dict[str, int] = {}
        for row in sources:
            if isinstance(row, dict):
                status = str(row.get("verification_status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
        return dict(sorted(counts.items()))
    return {}


def source_count(report: dict[str, Any] | None) -> int | None:
    if not report:
        return None
    summary = report.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("source_count"), int):
        return summary["source_count"]
    sources = report.get("sources")
    if isinstance(sources, list):
        return len(sources)
    return None


def confirmed_p0_count(report: dict[str, Any] | None) -> int | None:
    if not report:
        return None
    summary = report.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("confirmed_p0_count"), int):
        return summary["confirmed_p0_count"]
    rows = report.get("confirmed_p0")
    if isinstance(rows, list):
        return len(rows)
    return None


def build_release_source_health_readiness(
    source_verification_report: LoadedReport,
    confirmed_p0_scan: LoadedReport,
    *,
    now: datetime | None = None,
    max_verification_age_hours: int = DEFAULT_MAX_VERIFICATION_AGE_HOURS,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not source_verification_report.present:
        warnings.append({
            "code": "missing_source_verification_report",
            "message": "Source verification artifact is missing; release source health cannot be fully assessed.",
        })
    elif source_verification_report.report_type != "source_verification_report":
        warnings.append({
            "code": "unexpected_source_verification_report_type",
            "message": f"Expected source_verification_report, got {source_verification_report.report_type!r}.",
        })

    generated = parse_generated_at(source_verification_report.generated_at)
    stale = False
    age_hours: float | None = None
    if source_verification_report.present:
        if generated is None:
            stale = True
            warnings.append({
                "code": "source_verification_generated_at_missing_or_invalid",
                "message": "Source verification artifact does not have a parseable generated_at timestamp.",
            })
        else:
            age_hours = max(0.0, (now - generated).total_seconds() / 3600)
            if age_hours > max_verification_age_hours:
                stale = True
                warnings.append({
                    "code": "stale_source_verification_report",
                    "message": f"Source verification artifact is {age_hours:.1f} hours old.",
                })

    status_counts = verification_status_counts(source_verification_report.data)
    for status in WARN_STATUSES:
        count = status_counts.get(status, 0)
        if count:
            warnings.append({
                "code": f"source_status_warning:{status}",
                "status": status,
                "count": count,
                "message": f"{count} source(s) have verification_status={status}.",
            })

    p0_count = confirmed_p0_count(confirmed_p0_scan.data)
    if confirmed_p0_scan.present and confirmed_p0_scan.report_type != "confirmed_p0_source_refinement_scan":
        warnings.append({
            "code": "unexpected_confirmed_p0_scan_report_type",
            "message": f"Expected confirmed_p0_source_refinement_scan, got {confirmed_p0_scan.report_type!r}.",
        })
    if p0_count is None:
        warnings.append({
            "code": "missing_confirmed_p0_scan",
            "message": "Confirmed P0 scan artifact is missing; release cannot confirm repeated hard-dead source count.",
        })
    elif p0_count > 0:
        failures.append({
            "code": "confirmed_p0_sources_present",
            "count": p0_count,
            "message": f"{p0_count} confirmed P0 source(s) are present.",
        })

    status = "blocked" if failures else "warning" if warnings else "ready"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "report_type": REPORT_TYPE,
        "status": status,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "policy": {
            "mode": "report_only",
            "fail_when_confirmed_p0_count_gt": 0,
            "warn_statuses": list(WARN_STATUSES),
            "max_verification_age_hours": max_verification_age_hours,
        },
        "inputs": {
            "source_verification_report": {
                "path": source_verification_report.path,
                "present": source_verification_report.present,
                "report_type": source_verification_report.report_type,
                "generated_at": source_verification_report.generated_at,
                "age_hours": age_hours,
                "stale": stale,
            },
            "confirmed_p0_scan": {
                "path": confirmed_p0_scan.path,
                "present": confirmed_p0_scan.present,
                "report_type": confirmed_p0_scan.report_type,
                "generated_at": confirmed_p0_scan.generated_at,
            },
        },
        "summary": {
            "source_count": source_count(source_verification_report.data),
            "confirmed_p0_count": p0_count,
            "failure_count": len(failures),
            "warning_count": len(warnings),
            "verification_statuses": status_counts,
        },
        "failures": failures,
        "warnings": warnings,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# OpenVA Release Source Health Readiness",
        "",
        "This report is a release-readiness signal only. It does not mutate catalog records, generate repairs, or open pull requests.",
        "",
        "## Summary",
        "",
        f"- Status: `{report['status']}`",
        f"- Sources assessed: `{summary['source_count']}`",
        f"- Confirmed P0 count: `{summary['confirmed_p0_count']}`",
        f"- Failures: `{summary['failure_count']}`",
        f"- Warnings: `{summary['warning_count']}`",
        "",
        "## Inputs",
        "",
        f"- Source verification report: `{report['inputs']['source_verification_report']['path']}`",
        f"- Source verification present: `{report['inputs']['source_verification_report']['present']}`",
        f"- Confirmed P0 scan: `{report['inputs']['confirmed_p0_scan']['path']}`",
        f"- Confirmed P0 scan present: `{report['inputs']['confirmed_p0_scan']['present']}`",
        "",
        "## Failures",
        "",
    ]
    if report["failures"]:
        lines.extend(f"- `{item['code']}`: {item['message']}" for item in report["failures"])
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        lines.extend(f"- `{item['code']}`: {item['message']}" for item in report["warnings"])
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Guardrails",
        "",
        "- Consumes source health artifacts only.",
        "- Does not run live source verification.",
        "- Does not mutate catalog files.",
        "- Does not create repair plans or repair PRs.",
        "- Report-only in this work package.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-release-source-health")
    parser.add_argument("command", choices={"check"})
    parser.add_argument("--source-verification-report", type=Path, default=Path("source-verification-report.json"))
    parser.add_argument("--confirmed-p0-scan", type=Path, default=Path("confirmed-p0-repair-candidates.json"))
    parser.add_argument("--output-json", type=Path, default=Path("release-source-health-readiness.json"))
    parser.add_argument("--summary-md", type=Path, default=Path("release-source-health-summary.md"))
    parser.add_argument("--max-verification-age-hours", type=int, default=DEFAULT_MAX_VERIFICATION_AGE_HOURS)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)

    report = build_release_source_health_readiness(
        load_optional_json(args.source_verification_report),
        load_optional_json(args.confirmed_p0_scan),
        max_verification_age_hours=args.max_verification_age_hours,
    )
    write_json(report, args.output_json)
    write_markdown(report, args.summary_md)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(f"status={report['status']}")
    if args.report_only:
        return 0
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
