from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import yaml

from tools.openva.auto_canonical import build_machine_validated_source, is_machine_canonical_eligible

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "contribution_promotion_queue"


@dataclass
class QueueCandidate:
    vendor_id: str
    source_type: str
    url: str
    title: str
    vendor: dict[str, Any]
    candidate: dict[str, Any]
    verification: dict[str, Any]
    submissions: list[dict[str, Any]] = field(default_factory=list)


def normalize_url(url: str) -> str:
    parsed = urlparse(str(url).strip().rstrip(".,);]"))
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{host}{port}{path}{query}"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected YAML object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def iter_input_files(paths: Iterable[Path], suffix: str) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob(f"*{suffix}")))
        elif path.exists():
            files.append(path)
    return sorted(dict.fromkeys(files))


def load_vendor_records(root: Path) -> dict[str, dict[str, Any]]:
    vendors: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        vendor = load_yaml(path)
        vendor_id = str(vendor.get("vendor_id") or path.parent.name)
        vendor["vendor_id"] = vendor_id
        vendors[vendor_id] = vendor
    return vendors


def check_for_url(report: dict[str, Any], url: str) -> dict[str, Any]:
    normalized = normalize_url(url)
    for check in report.get("checks", []) or []:
        if normalize_url(str(check.get("url") or "")) == normalized:
            return check if isinstance(check, dict) else {}
    return {}


def verification_from_check(check: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    network = check.get("network_verification") or {}
    if not isinstance(network, dict):
        network = {}
    status = network.get("verification_status") or network.get("result") or network.get("status")
    if not status:
        status = "missing_verification"
    return {
        "verification_status": status,
        "http_status": network.get("http_status") or network.get("status_code"),
        "final_url": network.get("final_url") or source.get("source_url"),
        "page_title": network.get("title_detected") or source.get("title_en") or source.get("title_native"),
        "observed_at": network.get("observed_at") or network.get("collected_at"),
        "matched_terms": network.get("matched_terms") or [],
    }


def candidate_from_source(
    source: dict[str, Any], vendor_id: str, submission_id: str
) -> dict[str, Any]:
    source_type = str(source.get("source_type") or source.get("source_type_candidate") or "")
    url = str(source.get("source_url") or source.get("candidate_url") or "")
    title = str(source.get("title_en") or source.get("title_native") or source.get("title") or source_type)
    return {
        "vendor_id": vendor_id,
        "candidate_source_id": source.get("candidate_source_id")
        or source.get("source_id")
        or f"{vendor_id}-{source_type}-{submission_id}",
        "source_type_candidate": source_type,
        "candidate_url": url,
        "title": title,
        "title_en": source.get("title_en") or title,
        "title_native": source.get("title_native") or title,
        "source_language": source.get("source_language") or "en",
        "source_authority_class": source.get("source_authority_class") or "vendor_published",
        "access_class": source.get("access_class") or "public_web",
        "rights_class": source.get("rights_class") or "metadata_only",
    }


def queue_candidates_from_intake_report(
    path: Path, report: dict[str, Any], vendor_records: dict[str, dict[str, Any]]
) -> list[QueueCandidate]:
    vendor_info = report.get("vendor") or {}
    vendor_id = str(vendor_info.get("vendor_id") or "")
    result: list[QueueCandidate] = []
    if not vendor_id:
        return result
    vendor = dict(vendor_records.get(vendor_id) or vendor_info)
    vendor["vendor_id"] = vendor_id
    for index, source in enumerate(report.get("proposed_sources", []) or []):
        if not isinstance(source, dict):
            continue
        candidate = candidate_from_source(source, vendor_id, f"report-{index}")
        url = candidate["candidate_url"]
        check = check_for_url(report, url)
        verification = verification_from_check(check, source)
        submission = {
            "input_path": path.as_posix(),
            "issue_number": report.get("issue_number"),
            "decision": report.get("decision"),
        }
        result.append(
            QueueCandidate(
                vendor_id=vendor_id,
                source_type=candidate["source_type_candidate"],
                url=url,
                title=candidate["title"],
                vendor=vendor,
                candidate=candidate,
                verification=verification,
                submissions=[submission],
            )
        )
    return result


def queue_candidates_from_batch(path: Path, batch: dict[str, Any]) -> list[QueueCandidate]:
    result: list[QueueCandidate] = []
    batch_id = str(batch.get("batch_id") or path.stem)
    observed_at = batch.get("collected_at")
    for vendor_entry in batch.get("vendors", []) or []:
        if not isinstance(vendor_entry, dict):
            continue
        vendor_id = str(vendor_entry.get("vendor_id") or "")
        if not vendor_id:
            continue
        vendor = dict(vendor_entry)
        vendor["vendor_id"] = vendor_id
        for index, source in enumerate(vendor_entry.get("sources", []) or []):
            if not isinstance(source, dict):
                continue
            candidate = candidate_from_source(source, vendor_id, f"{batch_id}-{index}")
            verification = {
                "verification_status": source.get("verification_status") or "missing_verification",
                "http_status": source.get("http_status"),
                "final_url": source.get("final_url") or candidate["candidate_url"],
                "page_title": source.get("title_en") or source.get("title_native"),
                "observed_at": observed_at,
                "matched_terms": source.get("matched_terms") or [],
            }
            result.append(
                QueueCandidate(
                    vendor_id=vendor_id,
                    source_type=candidate["source_type_candidate"],
                    url=candidate["candidate_url"],
                    title=candidate["title"],
                    vendor=vendor,
                    candidate=candidate,
                    verification=verification,
                    submissions=[{"input_path": path.as_posix(), "batch_id": batch_id}],
                )
            )
    return result


def candidate_key(candidate: QueueCandidate) -> tuple[str, str, str]:
    return (candidate.vendor_id, candidate.source_type, normalize_url(candidate.url))


def verification_score(verification: dict[str, Any]) -> int:
    status = str(verification.get("verification_status") or "")
    http_status = verification.get("http_status")
    if status in {"ok", "success", "reachable", "verified", "fetch_ok", "public"}:
        return 3
    try:
        code = int(http_status)
    except (TypeError, ValueError):
        return 0
    if 200 <= code < 300:
        return 2
    return 1


def dedupe_candidates(candidates: list[QueueCandidate]) -> list[QueueCandidate]:
    by_key: dict[tuple[str, str, str], QueueCandidate] = {}
    for candidate in candidates:
        key = candidate_key(candidate)
        if key not in by_key:
            by_key[key] = candidate
            continue
        existing = by_key[key]
        existing.submissions.extend(candidate.submissions)
        if verification_score(candidate.verification) > verification_score(existing.verification):
            existing.verification = candidate.verification
        if not existing.vendor.get("official_domains") and candidate.vendor.get("official_domains"):
            existing.vendor = candidate.vendor
    return list(by_key.values())


def observation_for(candidate: QueueCandidate) -> dict[str, Any] | None:
    status = candidate.verification.get("verification_status")
    if not status or status == "missing_verification":
        return None
    return {
        "vendor_id": candidate.vendor_id,
        "source_type": candidate.source_type,
        "source_url": candidate.url,
        "observed_at": candidate.verification.get("observed_at"),
        "result": status,
        "http_status": candidate.verification.get("http_status"),
        "final_url": candidate.verification.get("final_url"),
        "canonical": False,
        "catalog_tier": "observation",
        "review_state": "auto_observed",
        "advisory_boundary": "non_advisory",
    }


def classify_candidate(candidate: QueueCandidate) -> tuple[str, dict[str, Any]]:
    eligible, reasons = is_machine_canonical_eligible(
        candidate.candidate, candidate.vendor, candidate.verification
    )
    base = {
        "vendor_id": candidate.vendor_id,
        "source_type": candidate.source_type,
        "candidate_url": normalize_url(candidate.url),
        "submissions": candidate.submissions,
        "verification": candidate.verification,
    }
    if eligible:
        source = build_machine_validated_source(candidate.candidate, candidate.vendor, candidate.verification)
        return "machine_validated_promotions", {**base, "source": source, "reasons": []}
    if any(reason in reasons for reason in ("advisory_wording_present", "raw_or_extracted_full_text_present")):
        return "rejected", {**base, "reasons": reasons}
    return "human_review_required", {**base, "reasons": reasons}


def build_contribution_promotion_queue(
    *,
    root: Path,
    intake_paths: list[Path] | None = None,
    batch_paths: list[Path] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    vendor_records = load_vendor_records(root)
    candidates: list[QueueCandidate] = []
    input_files: list[str] = []

    for path in iter_input_files(intake_paths or [], ".json"):
        report = load_json(path)
        input_files.append(path.as_posix())
        candidates.extend(queue_candidates_from_intake_report(path, report, vendor_records))

    for path in iter_input_files(batch_paths or [], ".yaml"):
        batch = load_yaml(path)
        input_files.append(path.as_posix())
        candidates.extend(queue_candidates_from_batch(path, batch))

    deduped = dedupe_candidates(candidates)
    buckets: dict[str, list[dict[str, Any]]] = {
        "machine_validated_promotions": [],
        "human_review_required": [],
        "rejected": [],
    }
    observations: list[dict[str, Any]] = []

    for candidate in deduped:
        observation = observation_for(candidate)
        if observation:
            observations.append(observation)
        bucket, item = classify_candidate(candidate)
        buckets[bucket].append(item)

    by_vendor: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for bucket, items in buckets.items():
        for item in items:
            by_vendor[str(item["vendor_id"])][bucket] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "generated_at": generated_at,
        "posture": {
            "collates_contributor_inputs": True,
            "deduplicates_by_vendor_source_type_url": True,
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "auto_merge": False,
            "non_advisory": True,
        },
        "inputs": sorted(input_files),
        "summary": {
            "submitted_candidates": len(candidates),
            "deduplicated_candidates": len(deduped),
            "machine_validated_promotions": len(buckets["machine_validated_promotions"]),
            "human_review_required": len(buckets["human_review_required"]),
            "rejected": len(buckets["rejected"]),
            "observations": len(observations),
            "vendors": {vendor: dict(counts) for vendor, counts in sorted(by_vendor.items())},
        },
        "machine_validated_promotions": buckets["machine_validated_promotions"],
        "human_review_required": buckets["human_review_required"],
        "rejected": buckets["rejected"],
        "observations": observations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-contribution-promotion-queue")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--root", type=Path, default=Path.cwd())
    build.add_argument("--intake", type=Path, action="append", default=[])
    build.add_argument("--batch", type=Path, action="append", default=[])
    build.add_argument("--out", type=Path, default=Path(".openva-promotion-queue/queue.json"))

    args = parser.parse_args()
    if args.command == "build":
        queue = build_contribution_promotion_queue(
            root=args.root,
            intake_paths=args.intake,
            batch_paths=args.batch,
        )
        write_json(args.out, queue)
        print(json.dumps(queue["summary"], indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
