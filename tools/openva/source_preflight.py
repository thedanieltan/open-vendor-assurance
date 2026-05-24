from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from tools.openva.paths import normalize_repo_path
from tools.openva.source_verification import load_yaml, verify_source

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "source_preflight_report"

PASS_STATUSES = {"ok", "redirected"}
FAIL_STATUSES = {
    "not_found",
    "gone",
    "bot_protected",
    "forbidden_unknown",
    "gated_or_login_required",
    "homepage_or_generic_redirect",
    "possible_mismatch",
    "rate_limited",
    "suspect_inferred_url",
    "unreachable",
    "client_error",
    "server_error",
}

Verifier = Callable[[dict[str, Any], Path], dict[str, Any]]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_changed_source_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    parts = normalized.split("/")
    return (
        len(parts) == 5
        and parts[0] == "data"
        and parts[1] == "vendors"
        and bool(parts[2])
        and parts[3] == "sources"
        and parts[4].endswith(".yaml")
    )


def read_paths(path: Path) -> list[str]:
    return [
        normalize_repo_path(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if normalize_repo_path(line)
    ]


def default_verifier(source: dict[str, Any], path: Path) -> dict[str, Any]:
    return verify_source(source, path)


def verification_failure_reason(status: str) -> str:
    if status in FAIL_STATUSES:
        return f"source_preflight_failed:{status}"
    return f"source_preflight_failed:unknown_status:{status}"


def checked_row(path: str, verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": path,
        "vendor_id": verification.get("vendor_id"),
        "source_id": verification.get("source_id"),
        "source_type": verification.get("source_type"),
        "source_url": verification.get("source_url"),
        "final_url": verification.get("final_url"),
        "http_status": verification.get("http_status"),
        "verification_status": verification.get("verification_status"),
        "requires_review": verification.get("requires_review"),
    }


def check_changed_sources(
    paths: list[str],
    *,
    root: Path = ROOT,
    verifier: Verifier | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    verifier = verifier or default_verifier
    normalized_paths = [normalize_repo_path(path) for path in paths if normalize_repo_path(path)]
    source_paths = sorted({path for path in normalized_paths if is_changed_source_path(path)})
    skipped_paths = sorted({path for path in normalized_paths if not is_changed_source_path(path)})
    checked_sources: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    verification_ran = False

    for relative_path in source_paths:
        full_path = root / relative_path
        if not full_path.exists():
            failures.append(
                {
                    "path": relative_path,
                    "reason": "changed_source_file_missing",
                    "verification_status": "missing_file",
                }
            )
            continue
        try:
            source = load_yaml(full_path)
            verification_ran = True
            verification = verifier(source, full_path)
        except Exception as exc:  # noqa: BLE001 - preflight should fail closed per source.
            failures.append(
                {
                    "path": relative_path,
                    "reason": f"source_preflight_exception:{type(exc).__name__}",
                    "message": str(exc),
                }
            )
            continue

        row = checked_row(relative_path, verification)
        checked_sources.append(row)
        status = str(verification.get("verification_status") or "")
        if status not in PASS_STATUSES:
            failures.append(
                {
                    **row,
                    "reason": verification_failure_reason(status),
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "report_type": REPORT_TYPE,
        "changed_source_count": len(source_paths),
        "checked_source_count": len(checked_sources),
        "passed_count": sum(1 for row in checked_sources if row.get("verification_status") in PASS_STATUSES),
        "failed_count": len(failures),
        "skipped_count": len(skipped_paths),
        "message": (
            "No changed source records requiring source preflight."
            if not source_paths
            else "Changed source records were checked by source preflight."
        ),
        "posture": {
            "network_fetch_performed": verification_ran,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "failures": failures,
        "checked_sources": checked_sources,
        "skipped_paths": skipped_paths,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-preflight")
    parser.add_argument("command", choices={"check-changed-sources"})
    parser.add_argument("--paths-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("source-preflight-report.json"))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    report = check_changed_sources(read_paths(args.paths_file), root=args.root)
    write_json(report, args.output)
    print(json.dumps({
        "changed_source_count": report["changed_source_count"],
        "checked_source_count": report["checked_source_count"],
        "passed_count": report["passed_count"],
        "failed_count": report["failed_count"],
        "skipped_count": report["skipped_count"],
        "message": report["message"],
    }, indent=2, sort_keys=True))
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
