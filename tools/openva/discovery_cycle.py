from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from tools.openva.source_verification import ROOT

SCHEMA_VERSION = "0.1.0"
BUNDLE_TYPE = "discovery_cycle_bundle"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def normalize_domain(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    return raw.split("/", 1)[0].removeprefix("www.").strip(".")


def current_vendor_identity(root: Path = ROOT) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    domains: set[str] = set()
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        vendor_id = str(data.get("vendor_id") or path.parent.name).strip()
        if vendor_id:
            ids.add(vendor_id)
        for key in ("official_domains", "previous_domains", "public_entrypoints"):
            for value in data.get(key, []) or []:
                domain = normalize_domain(value)
                if domain:
                    domains.add(domain)
    return ids, domains


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    try:
        priority = int(row.get("priority") or 0)
    except (TypeError, ValueError):
        priority = 0
    return (
        -priority,
        str(row.get("coverage_lane") or ""),
        str(row.get("candidate_vendor_id") or ""),
    )


def select_rotating_workset(
    candidate_report: dict[str, Any],
    *,
    limit: int,
    cycle_number: int,
    root: Path = ROOT,
    generated_at: str | None = None,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    """Select one fair, deterministic slice of a vendor-candidate report.

    The old growth loop repeatedly consumed the first ``vendor_limit`` candidates.
    This selector partitions the complete eligible set into stable bounded slices
    and advances by ``cycle_number``. Runtime limits therefore remain transaction
    safety bounds instead of becoming an accidental catalog-growth ceiling.
    """

    if candidate_report.get("report_type") != "vendor_candidate_discovery_report":
        raise ValueError("expected vendor_candidate_discovery_report")
    if limit < 1:
        raise ValueError("limit must be positive")
    if cycle_number < 1:
        raise ValueError("cycle_number must be positive")

    known_ids, known_domains = current_vendor_identity(root)
    eligible: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_domains: set[str] = set()
    filtered_known = 0
    filtered_invalid = 0
    filtered_duplicate = 0

    for raw in candidate_report.get("vendor_candidates", []) or []:
        if not isinstance(raw, dict):
            filtered_invalid += 1
            continue
        row = dict(raw)
        vendor_id = str(row.get("candidate_vendor_id") or "").strip()
        domain = normalize_domain(row.get("official_domain_candidate"))
        if not vendor_id or not domain:
            filtered_invalid += 1
            continue
        if vendor_id in known_ids or domain in known_domains:
            filtered_known += 1
            continue
        if vendor_id in seen_ids or domain in seen_domains:
            filtered_duplicate += 1
            continue
        seen_ids.add(vendor_id)
        seen_domains.add(domain)
        row["official_domain_candidate"] = domain
        eligible.append(row)

    eligible.sort(key=_candidate_sort_key)
    total = len(eligible)
    bucket_count = max(1, math.ceil(total / limit)) if total else 1
    bucket_index = (cycle_number - 1) % bucket_count
    start = bucket_index * limit
    selected = eligible[start : start + limit]

    generated = generated_at or now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "report_type": "vendor_candidate_discovery_report",
        "discovery_context": "rotating_discovery_cycle_workset",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "candidate_vendor_count": len(selected),
            "eligible_candidate_vendor_count": total,
            "known_vendor_count": len(known_ids),
            "filtered_known_count": filtered_known,
            "filtered_invalid_count": filtered_invalid,
            "filtered_duplicate_count": filtered_duplicate,
            "catalog_vendor_count_cap": None,
            "runtime_vendor_limit": limit,
            "rotation_bucket_count": bucket_count,
            "rotation_bucket_index": bucket_index,
            "rotation_cycle_number": cycle_number,
            "source_run_id": source_run_id,
        },
        "vendor_candidates": selected,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def build_bundle_manifest(
    files: dict[str, Path],
    *,
    source_run_id: str,
    source_run_attempt: int,
    source_commit_sha: str,
    cycle_number: int,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if not source_run_id or not source_run_id.isdigit():
        raise ValueError("source_run_id must be numeric")
    if source_run_attempt < 1:
        raise ValueError("source_run_attempt must be positive")
    if cycle_number < 1:
        raise ValueError("cycle_number must be positive")
    if len(source_commit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in source_commit_sha.lower()):
        raise ValueError("source_commit_sha must be a 40-character hexadecimal SHA")
    if not files:
        raise ValueError("bundle must contain at least one file")

    entries: dict[str, dict[str, str]] = {}
    for name, path in sorted(files.items()):
        if not name:
            raise ValueError("bundle file names must be non-empty")
        if not path.is_file():
            raise ValueError(f"bundle file missing: {path}")
        entries[name] = {"path": path.as_posix(), "digest": sha256_file(path)}

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_type": BUNDLE_TYPE,
        "generated_at": generated_at or now_iso(),
        "source": {
            "workflow": "discovery-mesh",
            "run_id": source_run_id,
            "run_attempt": source_run_attempt,
            "source_commit_sha": source_commit_sha,
            "cycle_number": cycle_number,
        },
        "files": entries,
        "posture": {
            "raw_discovery_evidence_external_to_git": True,
            "catalog_mutation_authority": "candidate-promotion-pr.yml",
            "non_advisory": True,
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["bundle_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return manifest


def _parse_file_args(values: list[str]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--file values must use NAME=PATH")
        name, raw_path = value.split("=", 1)
        name = name.strip()
        raw_path = raw_path.strip()
        if not name or not raw_path:
            raise ValueError("--file values must use NAME=PATH")
        if name in files:
            raise ValueError(f"duplicate bundle file name: {name}")
        files[name] = Path(raw_path)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-cycle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select-workset")
    select.add_argument("--candidates", type=Path, required=True)
    select.add_argument("--limit", type=int, required=True)
    select.add_argument("--cycle-number", type=int, required=True)
    select.add_argument("--source-run-id", default="")
    select.add_argument("--generated-at")
    select.add_argument("--output", type=Path, required=True)

    bundle = subparsers.add_parser("build-bundle")
    bundle.add_argument("--file", action="append", default=[])
    bundle.add_argument("--source-run-id", required=True)
    bundle.add_argument("--source-run-attempt", type=int, required=True)
    bundle.add_argument("--source-commit-sha", required=True)
    bundle.add_argument("--cycle-number", type=int, required=True)
    bundle.add_argument("--generated-at")
    bundle.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "select-workset":
        report = select_rotating_workset(
            load_json(args.candidates),
            limit=args.limit,
            cycle_number=args.cycle_number,
            generated_at=args.generated_at,
            source_run_id=args.source_run_id or None,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0

    files = _parse_file_args(args.file)
    manifest = build_bundle_manifest(
        files,
        source_run_id=args.source_run_id,
        source_run_attempt=args.source_run_attempt,
        source_commit_sha=args.source_commit_sha,
        cycle_number=args.cycle_number,
        generated_at=args.generated_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"bundle_digest": manifest["bundle_digest"], "file_count": len(files)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
