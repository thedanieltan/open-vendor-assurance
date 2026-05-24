from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT = Path("confirmed-p0-repair-candidates.json")

ALLOWED_VERIFICATION_STATUSES = {
    "bot_protected",
    "client_error",
    "forbidden_unknown",
    "gated_or_login_required",
    "gone",
    "homepage_or_generic_redirect",
    "not_found",
    "ok",
    "possible_mismatch",
    "rate_limited",
    "redirected",
    "server_error",
    "suspect_inferred_url",
    "unreachable",
}

CONFIRMED_P0_STATUS_PAIRS = {
    ("not_found", "not_found"),
    ("gone", "gone"),
}

P0_STATUSES = {"not_found", "gone"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def source_key(source: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(source.get("vendor_id") or ""),
        str(source.get("source_id") or ""),
        str(source.get("source_url") or ""),
    )


def validate_report(report: dict[str, Any], label: str) -> list[dict[str, Any]]:
    if report.get("report_type") != "source_verification_report":
        raise ValueError(f"{label}: expected report_type=source_verification_report")
    sources = report.get("sources")
    if not isinstance(sources, list):
        raise ValueError(f"{label}: expected sources list")

    unknown_statuses: list[dict[str, Any]] = []
    duplicate_keys: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError(f"{label}: expected each source row to be an object")
        key = source_key(source)
        if not all(key):
            raise ValueError(f"{label}: source row missing vendor_id, source_id, or source_url: {key}")
        if key in seen:
            duplicate_keys.append(key)
        seen.add(key)
        status = str(source.get("verification_status") or "")
        if status not in ALLOWED_VERIFICATION_STATUSES:
            unknown_statuses.append(row_summary(source, reason="unknown_verification_status"))

    if duplicate_keys:
        formatted = ", ".join(" | ".join(key) for key in duplicate_keys[:5])
        raise ValueError(f"{label}: duplicate vendor_id+source_id+source_url keys: {formatted}")
    if unknown_statuses:
        statuses = sorted({str(row.get("status") or "") for row in unknown_statuses})
        raise ValueError(f"{label}: unknown verification_status value(s): {', '.join(statuses)}")
    return sources


def row_summary(source: dict[str, Any], reason: str | None = None, prefix: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "source_url": source.get("source_url"),
        f"{prefix}status" if prefix else "status": source.get("verification_status"),
        f"{prefix}http_status" if prefix else "http_status": source.get("http_status"),
        f"{prefix}final_url" if prefix else "final_url": source.get("final_url"),
    }
    if reason:
        row["reason"] = reason
    return row


def comparison_row(
    prior: dict[str, Any] | None,
    fresh: dict[str, Any] | None,
    reason: str,
    prior_generated_at: str | None,
    fresh_generated_at: str | None,
) -> dict[str, Any]:
    source = fresh or prior or {}
    row: dict[str, Any] = {
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "source_url": source.get("source_url"),
        "reason": reason,
    }
    if prior is not None:
        row.update(
            {
                "prior_status": prior.get("verification_status"),
                "prior_http_status": prior.get("http_status"),
                "prior_final_url": prior.get("final_url"),
                "prior_verified_at": prior_generated_at,
            }
        )
    if fresh is not None:
        row.update(
            {
                "fresh_status": fresh.get("verification_status"),
                "fresh_http_status": fresh.get("http_status"),
                "fresh_final_url": fresh.get("final_url"),
                "fresh_verified_at": fresh_generated_at,
            }
        )
    return row


def confirmed_p0_row(
    prior: dict[str, Any],
    fresh: dict[str, Any],
    prior_generated_at: str | None,
    fresh_generated_at: str | None,
) -> dict[str, Any]:
    return {
        "vendor_id": fresh.get("vendor_id"),
        "source_id": fresh.get("source_id"),
        "source_type": fresh.get("source_type"),
        "source_url": fresh.get("source_url"),
        "prior_status": prior.get("verification_status"),
        "fresh_status": fresh.get("verification_status"),
        "prior_http_status": prior.get("http_status"),
        "fresh_http_status": fresh.get("http_status"),
        "prior_final_url": prior.get("final_url"),
        "fresh_final_url": fresh.get("final_url"),
        "prior_verified_at": prior_generated_at,
        "fresh_verified_at": fresh_generated_at,
    }


def build_index(sources: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {source_key(source): source for source in sources}


def compare_verification_reports(
    prior_report: dict[str, Any],
    fresh_report: dict[str, Any],
    prior_report_run_id: str | None = None,
    fresh_report_run_id: str | None = None,
) -> dict[str, Any]:
    prior_sources = validate_report(prior_report, "prior_report")
    fresh_sources = validate_report(fresh_report, "fresh_report")
    prior_by_key = build_index(prior_sources)
    fresh_by_key = build_index(fresh_sources)
    prior_generated_at = prior_report.get("generated_at")
    fresh_generated_at = fresh_report.get("generated_at")

    confirmed_p0: list[dict[str, Any]] = []
    inconclusive: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for key in sorted(set(prior_by_key) | set(fresh_by_key)):
        prior = prior_by_key.get(key)
        fresh = fresh_by_key.get(key)
        if prior is None:
            inconclusive.append(
                comparison_row(
                    prior,
                    fresh,
                    "missing_from_prior_report",
                    prior_generated_at,
                    fresh_generated_at,
                )
            )
            continue
        if fresh is None:
            inconclusive.append(
                comparison_row(
                    prior,
                    fresh,
                    "missing_from_fresh_report",
                    prior_generated_at,
                    fresh_generated_at,
                )
            )
            continue

        prior_status = str(prior.get("verification_status"))
        fresh_status = str(fresh.get("verification_status"))
        if (prior_status, fresh_status) in CONFIRMED_P0_STATUS_PAIRS:
            confirmed_p0.append(
                confirmed_p0_row(prior, fresh, prior_generated_at, fresh_generated_at)
            )
        elif prior_status != fresh_status:
            inconclusive.append(
                comparison_row(
                    prior,
                    fresh,
                    "status_changed_between_runs",
                    prior_generated_at,
                    fresh_generated_at,
                )
            )
        elif fresh_status in P0_STATUSES:
            inconclusive.append(
                comparison_row(
                    prior,
                    fresh,
                    "p0_status_not_confirmed_by_exact_allowed_pair",
                    prior_generated_at,
                    fresh_generated_at,
                )
            )
        else:
            excluded.append(
                comparison_row(
                    prior,
                    fresh,
                    "not_eligible_for_automated_p0_repair",
                    prior_generated_at,
                    fresh_generated_at,
                )
            )

    prior_statuses = Counter(str(source.get("verification_status")) for source in prior_sources)
    fresh_statuses = Counter(str(source.get("verification_status")) for source in fresh_sources)

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "confirmed_p0_source_refinement_scan",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "non_advisory": True,
        },
        "prior_report_run_id": prior_report_run_id,
        "fresh_report_run_id": fresh_report_run_id,
        "prior_report_generated_at": prior_generated_at,
        "fresh_report_generated_at": fresh_generated_at,
        "confirmed_p0": confirmed_p0,
        "inconclusive": inconclusive,
        "excluded": excluded,
        "unknown_statuses": [],
        "summary": {
            "prior_source_count": len(prior_sources),
            "fresh_source_count": len(fresh_sources),
            "confirmed_p0_count": len(confirmed_p0),
            "inconclusive_count": len(inconclusive),
            "excluded_count": len(excluded),
            "unknown_status_count": 0,
            "prior_statuses": dict(sorted(prior_statuses.items())),
            "fresh_statuses": dict(sorted(fresh_statuses.items())),
        },
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-refinement-scan")
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--prior-verification-report", type=Path, required=True)
    compare.add_argument("--fresh-verification-report", type=Path, required=True)
    compare.add_argument("--prior-report-run-id")
    compare.add_argument("--fresh-report-run-id")
    compare.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    args = parser.parse_args()
    if args.command == "compare":
        report = compare_verification_reports(
            load_json(args.prior_verification_report),
            load_json(args.fresh_verification_report),
            prior_report_run_id=args.prior_report_run_id,
            fresh_report_run_id=args.fresh_report_run_id,
        )
        write_report(report, args.output)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
