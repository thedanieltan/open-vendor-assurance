from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.source_verification import ROOT, display_path

PROMOTABLE_VERIFICATION_STATUSES = {"ok", "redirected"}
PROMOTABLE_SEMANTIC_STATUSES = {"strong", "not_evaluated_pdf_sample"}
REVIEWED_CANDIDATE_PROMOTION_ACTION = "promote_candidate_source_for_review"
STRICT_GROWTH_PROMOTION_ACTION = "strict_catalog_growth_promotion"
REVIEWABLE_VERIFICATION_STATUSES = {
    "suspect_inferred_url",
    "possible_mismatch",
    "homepage_or_generic_redirect",
    "bot_protected",
    "gated_or_login_required",
    "forbidden_unknown",
    "rate_limited",
    "not_found",
    "gone",
    "server_error",
    "client_error",
    "unreachable",
}


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def load_json_if_exists(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def iter_records(root: Path, record_dir: str) -> list[tuple[Path, dict[str, Any]]]:
    paths = sorted((root / "data/vendors").glob(f"*/{record_dir}/*.yaml"))
    return [(path, load_yaml(path)) for path in paths]


def canonical_source_types(root: Path) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for _, source in iter_records(root, "sources"):
        result.add((str(source["vendor_id"]), str(source["source_type"])))
    return result


def verification_by_source_id(report: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    if not report:
        return {}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in report.get("sources", []) or []:
        vendor_id = item.get("vendor_id")
        source_id = item.get("source_id")
        if vendor_id and source_id:
            result[(str(vendor_id), str(source_id))] = item
    return result


def candidate_report_by_key(report: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    if not report:
        return {}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for vendor in report.get("vendors", []) or []:
        for candidate in vendor.get("candidates", []) or []:
            vendor_id = candidate.get("vendor_id")
            source_type = candidate.get("source_type_candidate")
            if vendor_id and source_type:
                result[(str(vendor_id), str(source_type))] = candidate
    return result


def plan_for_candidate(
    path: Path,
    candidate: dict[str, Any],
    existing_types: set[tuple[str, str]],
    discovery_candidates: dict[tuple[str, str], dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    vendor_id = str(candidate["vendor_id"])
    source_type = str(candidate["source_type_candidate"])
    key = (vendor_id, source_type)
    evidence = candidate.get("evidence", {}) or {}
    semantic_terms = evidence.get("matched_terms", []) or []
    report_candidate = discovery_candidates.get(key)
    report_evidence = (report_candidate or {}).get("evidence", {}) if report_candidate else {}
    confidence = str(candidate.get("confidence", "candidate"))
    http_status = evidence.get("http_status") or report_evidence.get("http_status")

    if key in existing_types:
        action = "no_action_existing_source_type"
        reason = "A canonical source already exists for this vendor/source_type."
    elif confidence == "likely" and http_status == 200 and semantic_terms:
        action = REVIEWED_CANDIDATE_PROMOTION_ACTION
        reason = "Candidate has public HTTP 200 evidence and matched terms, but still requires review before canonical promotion."
    else:
        action = "manual_review_required"
        reason = "Candidate exists but evidence is not strong enough for promotion planning."

    return {
        "action": action,
        "reason": reason,
        "vendor_id": vendor_id,
        "source_type": source_type,
        "candidate_source_id": candidate.get("candidate_source_id"),
        "candidate_url": candidate.get("candidate_url"),
        "path": display_path(path, root),
        "evidence": {
            "confidence": confidence,
            "http_status": http_status,
            "matched_terms": semantic_terms,
            "page_title": evidence.get("page_title") or report_evidence.get("page_title"),
        },
        "requires_human_review": True,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }


def plan_for_unavailable(path: Path, unavailable: dict[str, Any], existing_types: set[tuple[str, str]], root: Path) -> dict[str, Any]:
    vendor_id = str(unavailable["vendor_id"])
    source_type = str(unavailable["source_type"])
    key = (vendor_id, source_type)
    if key in existing_types:
        action = "review_unavailable_conflict"
        reason = "Unavailable-source ledger entry conflicts with an existing canonical source type."
    else:
        action = "keep_unavailable_until_next_review"
        reason = "No canonical source exists and this absence has been recorded for review cadence."

    return {
        "action": action,
        "reason": reason,
        "vendor_id": vendor_id,
        "source_type": source_type,
        "unavailable_source_id": unavailable.get("unavailable_source_id"),
        "path": display_path(path, root),
        "next_review_after": unavailable.get("next_review_after"),
        "status": unavailable.get("status"),
        "requires_human_review": action == "review_unavailable_conflict",
        "non_advisory": True,
    }


def plan_for_existing_source(
    path: Path,
    source: dict[str, Any],
    verification: dict[str, Any] | None,
    root: Path,
) -> dict[str, Any] | None:
    if not verification:
        return None

    status = str(verification.get("verification_status") or "")
    semantic_status = str((verification.get("semantic_match") or {}).get("status") or "")
    if status in PROMOTABLE_VERIFICATION_STATUSES:
        return None
    if status not in REVIEWABLE_VERIFICATION_STATUSES:
        return None

    if status in {"not_found", "gone"}:
        action = "retire_or_replace_source_for_review"
        reason = "Existing canonical source is unavailable according to verification report."
    elif status in {"suspect_inferred_url", "possible_mismatch", "homepage_or_generic_redirect"}:
        action = "cleanup_source_for_review"
        reason = "Existing canonical source appears mismatched, generic, or likely inferred."
    else:
        action = "manual_review_required"
        reason = "Existing canonical source requires review based on verification status."

    return {
        "action": action,
        "reason": reason,
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "source_url": source.get("source_url"),
        "path": display_path(path, root),
        "verification": {
            "verification_status": status,
            "semantic_status": semantic_status,
            "http_status": verification.get("http_status"),
            "final_url": verification.get("final_url"),
            "title_detected": verification.get("title_detected"),
        },
        "requires_human_review": True,
        "non_advisory": True,
    }


def build_promotion_plan(
    root: Path = ROOT,
    verification_report_path: Path | None = None,
    discovery_report_path: Path | None = None,
) -> dict[str, Any]:
    verification_report = load_json_if_exists(verification_report_path)
    discovery_report = load_json_if_exists(discovery_report_path)
    verifications = verification_by_source_id(verification_report)
    discovery_candidates = candidate_report_by_key(discovery_report)
    existing_types = canonical_source_types(root)

    actions: list[dict[str, Any]] = []

    for path, source in iter_records(root, "sources"):
        verification = verifications.get((str(source.get("vendor_id")), str(source.get("source_id"))))
        action = plan_for_existing_source(path, source, verification, root=root)
        if action:
            actions.append(action)
    for path, candidate in iter_records(root, "candidate_sources"):
        actions.append(plan_for_candidate(path, candidate, existing_types, discovery_candidates, root=root))
    for path, unavailable in iter_records(root, "unavailable_sources"):
        actions.append(plan_for_unavailable(path, unavailable, existing_types, root=root))

    counts = Counter(action["action"] for action in actions)
    by_vendor: dict[str, list[str]] = defaultdict(list)
    for action in actions:
        vendor_id = action.get("vendor_id")
        if vendor_id:
            by_vendor[str(vendor_id)].append(action["action"])

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "promotion_plan",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "inputs": {
            "verification_report_path": display_path(verification_report_path, root) if verification_report_path else None,
            "discovery_report_path": display_path(discovery_report_path, root) if discovery_report_path else None,
            "verification_report_loaded": verification_report is not None,
            "discovery_report_loaded": discovery_report is not None,
        },
        "summary": {
            "action_count": len(actions),
            "actions_requiring_human_review": sum(1 for action in actions if action.get("requires_human_review")),
            "action_types": dict(sorted(counts.items())),
            "vendors_with_actions": {vendor_id: sorted(set(action_types)) for vendor_id, action_types in sorted(by_vendor.items())},
        },
        "actions": actions,
    }


def strict_growth_action(item: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    vendor = action["vendor"]
    source = action["source"]
    return {
        "action": STRICT_GROWTH_PROMOTION_ACTION,
        "reason": "Candidate passed strict catalog growth eligibility and may be applied through the candidate promotion apply path.",
        "vendor": vendor,
        "source": source,
        "classification": item.get("classification"),
        "reason_codes": item.get("reason_codes", []),
        "requires_human_review": False,
        "writes_canonical_vendors": False,
        "writes_canonical_sources": False,
        "strict_machine_candidate": True,
        "non_advisory": True,
    }


def build_strict_growth_plan(
    eligibility_report: dict[str, Any],
    *,
    head_sha: str | None = None,
    base_sha: str | None = None,
) -> dict[str, Any]:
    if eligibility_report.get("report_type") != "catalog_growth_eligibility_report":
        raise ValueError("expected catalog_growth_eligibility_report")
    strict_by_vendor = {
        str(item.get("candidate_vendor_id")): item
        for item in eligibility_report.get("items", []) or []
        if item.get("classification") == "strict_promote_ready"
    }
    actions = [
        strict_growth_action(strict_by_vendor[str(action["vendor"]["candidate_vendor_id"])], action)
        for action in eligibility_report.get("strict_promotions", []) or []
        if str(action.get("vendor", {}).get("candidate_vendor_id")) in strict_by_vendor
    ]
    counts = Counter(action["action"] for action in actions)
    plan = {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "strict_growth_promotion_plan",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "non_advisory": True,
        },
        "summary": {
            "action_count": len(actions),
            "actions_requiring_human_review": 0,
            "action_types": dict(sorted(counts.items())),
        },
        "actions": actions,
    }
    effective_head_sha = head_sha or eligibility_report.get("head_sha")
    effective_base_sha = base_sha or eligibility_report.get("base_sha")
    if effective_head_sha:
        plan["head_sha"] = effective_head_sha
    if effective_base_sha:
        plan["base_sha"] = effective_base_sha
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-promotion-planner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--verification-report", type=Path)
    plan.add_argument("--discovery-report", type=Path)
    plan.add_argument("--output", type=Path, default=ROOT / "promotion-plan.json")
    strict = subparsers.add_parser("plan-strict-growth")
    strict.add_argument("--eligibility-report", type=Path, required=True)
    strict.add_argument("--output", type=Path, default=ROOT / "strict-growth-promotion-plan.json")
    strict.add_argument("--head-sha")
    strict.add_argument("--base-sha")
    args = parser.parse_args()
    if args.command == "plan-strict-growth":
        report = build_strict_growth_plan(
            load_json(args.eligibility_report),
            head_sha=args.head_sha,
            base_sha=args.base_sha,
        )
    else:
        report = build_promotion_plan(
            verification_report_path=args.verification_report,
            discovery_report_path=args.discovery_report,
        )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
