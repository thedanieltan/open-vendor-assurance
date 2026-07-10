"""Discovery-mesh intake planning and validation.

This module bridges verified discovery-mesh reports into reviewed, non-mutating
candidate promotion plans. It never writes canonical vendor or source records.
The existing candidate-promotion workflow remains the sole canonical mutation
authority.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import yaml

from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION
from tools.openva.source_authority import is_on_official_domain
from tools.openva.source_verification import ROOT, display_path
from tools.openva.url_safety import validate_url_safety

SCHEMA_VERSION = "0.1.0"
PLAN_ROOT = Path("maintenance/reviewed/discovery-mesh")
CANDIDATE_PATH_RE = re.compile(r"^data/vendors/([^/]+)/candidate_sources/([^/]+)\.yaml$")
PLAN_PATH_RE = re.compile(r"^maintenance/reviewed/discovery-mesh/([^/]+)/([^/]+)\.json$")


class IntakeValidationError(ValueError):
    """Raised when a discovery-mesh intake violates its noncanonical boundary."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return value


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:100] or "unresolved"


def action_vendor_id(action: dict[str, Any]) -> str:
    vendor_id = str(action.get("vendor_id") or "")
    if vendor_id:
        return vendor_id
    vendor = action.get("vendor") or {}
    if isinstance(vendor, dict):
        return str(vendor.get("candidate_vendor_id") or "")
    return ""


def reviewed_actions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    actions = plan.get("actions", []) or []
    if not isinstance(actions, list):
        raise ValueError("promotion plan actions must be a list")
    return [
        dict(action)
        for action in actions
        if isinstance(action, dict) and action.get("action") == REVIEWED_CANDIDATE_PROMOTION_ACTION
    ]


def vendor_plan(
    actions: list[dict[str, Any]],
    *,
    vendor_id: str,
    source_plan_path: str,
    run_token: str,
    batch_index: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "candidate_promotion_plan_proposal",
        "source_plan_path": source_plan_path,
        "discovery_mesh_run_token": run_token,
        "batch_index": batch_index,
        "vendor_id": vendor_id,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "writes_canonical_sources": False,
            "requires_existing_candidate_records": True,
            "non_advisory": True,
        },
        "summary": {
            "action_count": len(actions),
            "vendor_count": 1,
            "action_types": {REVIEWED_CANDIDATE_PROMOTION_ACTION: len(actions)},
        },
        "actions": actions,
    }


def build_vendor_promotion_plans(
    plan: dict[str, Any],
    *,
    source_plan_path: str,
    run_token: str,
    output_root: Path,
) -> tuple[list[Path], dict[str, Any]]:
    """Write one reviewed plan per vendor, with no vendor-count ceiling."""

    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_token):
        raise ValueError("run_token may contain only letters, numbers, dot, underscore, and hyphen")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in reviewed_actions(plan):
        vendor_id = action_vendor_id(action)
        if not vendor_id:
            raise ValueError("reviewed candidate action is missing vendor_id")
        grouped[vendor_id].append(action)

    run_root = output_root / run_token
    paths: list[Path] = []
    action_count = 0
    for index, vendor_id in enumerate(sorted(grouped), start=1):
        actions = sorted(
            grouped[vendor_id],
            key=lambda item: (
                str(item.get("source_type") or ""),
                str(item.get("candidate_source_id") or ""),
            ),
        )
        action_count += len(actions)
        path = run_root / f"{safe_slug(vendor_id)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                vendor_plan(
                    actions,
                    vendor_id=vendor_id,
                    source_plan_path=source_plan_path,
                    run_token=run_token,
                    batch_index=index,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths.append(path)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "discovery_mesh_intake_manifest",
        "run_token": run_token,
        "summary": {
            "vendor_plan_count": len(paths),
            "reviewed_action_count": action_count,
            "vendor_count_cap": None,
            "action_count_cap": None,
        },
        "plan_paths": [path.as_posix() for path in paths],
        "posture": {
            "one_vendor_per_promotion_plan": True,
            "canonical_mutation_performed": False,
            "non_advisory": True,
        },
    }
    return paths, manifest


def allowed_intake_path(path: str) -> bool:
    return bool(CANDIDATE_PATH_RE.fullmatch(path) or PLAN_PATH_RE.fullmatch(path))


def validate_changed_paths(changed_paths: Iterable[str]) -> list[str]:
    paths = sorted({str(path).strip() for path in changed_paths if str(path).strip()})
    if not paths:
        raise IntakeValidationError("discovery-mesh intake has no changed paths")
    invalid = [path for path in paths if not allowed_intake_path(path)]
    if invalid:
        raise IntakeValidationError("out-of-scope intake paths: " + ", ".join(invalid))
    if not any(CANDIDATE_PATH_RE.fullmatch(path) for path in paths):
        raise IntakeValidationError("intake must contain at least one candidate source record")
    if not any(PLAN_PATH_RE.fullmatch(path) for path in paths):
        raise IntakeValidationError("intake must contain at least one reviewed promotion plan")
    return paths


def _public_safe_url(url: str) -> bool:
    try:
        return not validate_url_safety(url, resolve_dns=False)
    except (TypeError, ValueError):
        return False


def validate_candidate(candidate: dict[str, Any], vendor: dict[str, Any], path: str) -> None:
    required = ("candidate_source_id", "vendor_id", "source_type_candidate", "candidate_url", "evidence")
    missing = [field for field in required if not candidate.get(field)]
    if missing:
        raise IntakeValidationError(f"{path}: missing candidate fields: {', '.join(missing)}")
    if candidate.get("requires_review") is not True:
        raise IntakeValidationError(f"{path}: candidate must require review")
    if candidate.get("not_advice") is not True:
        raise IntakeValidationError(f"{path}: candidate must be non-advisory")
    if candidate.get("candidate_status") != "selected":
        raise IntakeValidationError(f"{path}: candidate_status must be selected")

    evidence = candidate.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise IntakeValidationError(f"{path}: evidence must be an object")
    if evidence.get("http_status") != 200:
        raise IntakeValidationError(f"{path}: candidate requires HTTP 200 evidence")
    if not evidence.get("matched_terms"):
        raise IntakeValidationError(f"{path}: candidate requires semantic matched terms")
    final_url = str(evidence.get("final_url") or "")
    candidate_url = str(candidate.get("candidate_url") or "")
    if not final_url or not candidate_url:
        raise IntakeValidationError(f"{path}: candidate and final URLs are required")
    if not _public_safe_url(candidate_url) or not _public_safe_url(final_url):
        raise IntakeValidationError(f"{path}: candidate URL is not public-safe")

    official_domains = [str(value) for value in vendor.get("official_domains", []) or [] if value]
    if not official_domains:
        raise IntakeValidationError(f"{path}: vendor has no official domains")
    if not is_on_official_domain(candidate_url, official_domains):
        raise IntakeValidationError(f"{path}: candidate URL is not on an official vendor domain")
    if not is_on_official_domain(final_url, official_domains):
        raise IntakeValidationError(f"{path}: observed final URL is not on an official vendor domain")


def validate_plan(plan: dict[str, Any], path: str, root: Path) -> set[str]:
    if plan.get("report_type") != "candidate_promotion_plan_proposal":
        raise IntakeValidationError(f"{path}: unexpected report_type")
    posture = plan.get("posture") or {}
    if not isinstance(posture, dict):
        raise IntakeValidationError(f"{path}: posture must be an object")
    if posture.get("writes_canonical_vendors") is not False or posture.get("writes_canonical_sources") is not False:
        raise IntakeValidationError(f"{path}: intake plan must be non-mutating")
    if posture.get("non_advisory") is not True:
        raise IntakeValidationError(f"{path}: intake plan must be non-advisory")

    plan_vendor_id = str(plan.get("vendor_id") or "")
    actions = plan.get("actions", []) or []
    if not isinstance(actions, list) or not actions:
        raise IntakeValidationError(f"{path}: reviewed plan must contain actions")
    referenced: set[str] = set()
    action_vendors: set[str] = set()
    for action in actions:
        if not isinstance(action, dict) or action.get("action") != REVIEWED_CANDIDATE_PROMOTION_ACTION:
            raise IntakeValidationError(f"{path}: unsupported action in reviewed plan")
        if action.get("requires_human_review") is not True:
            raise IntakeValidationError(f"{path}: reviewed action must require human review")
        if action.get("writes_canonical_sources") is not False:
            raise IntakeValidationError(f"{path}: reviewed action must remain non-mutating")
        if action.get("non_advisory") is not True:
            raise IntakeValidationError(f"{path}: reviewed action must be non-advisory")
        vendor_id = action_vendor_id(action)
        candidate_id = str(action.get("candidate_source_id") or "")
        if not vendor_id or not candidate_id:
            raise IntakeValidationError(f"{path}: action is missing vendor or candidate id")
        action_vendors.add(vendor_id)
        referenced.add(candidate_id)
        candidate_path = root / "data" / "vendors" / vendor_id / "candidate_sources" / f"{candidate_id}.yaml"
        if not candidate_path.exists():
            raise IntakeValidationError(f"{path}: referenced candidate does not exist: {display_path(candidate_path, root)}")
    if len(action_vendors) != 1:
        raise IntakeValidationError(f"{path}: each mesh promotion plan must contain exactly one vendor")
    if plan_vendor_id and action_vendors != {plan_vendor_id}:
        raise IntakeValidationError(f"{path}: plan vendor_id does not match its actions")
    return referenced


def validate_intake(root: Path, changed_paths: Iterable[str]) -> dict[str, Any]:
    paths = validate_changed_paths(changed_paths)
    changed_candidate_ids: set[str] = set()
    plan_references: set[str] = set()
    candidate_count = 0
    plan_count = 0

    for relative in paths:
        candidate_match = CANDIDATE_PATH_RE.fullmatch(relative)
        if candidate_match:
            vendor_id, candidate_id = candidate_match.groups()
            candidate = load_yaml(root / relative)
            vendor = load_yaml(root / "data" / "vendors" / vendor_id / "vendor.yaml")
            if str(candidate.get("vendor_id") or "") != vendor_id:
                raise IntakeValidationError(f"{relative}: candidate vendor_id does not match path")
            if str(candidate.get("candidate_source_id") or "") != candidate_id:
                raise IntakeValidationError(f"{relative}: candidate_source_id does not match filename")
            validate_candidate(candidate, vendor, relative)
            changed_candidate_ids.add(candidate_id)
            candidate_count += 1
            continue
        if PLAN_PATH_RE.fullmatch(relative):
            plan_references.update(validate_plan(load_json(root / relative), relative, root))
            plan_count += 1

    unplanned = sorted(changed_candidate_ids - plan_references)
    if unplanned:
        raise IntakeValidationError("candidate records are not referenced by a reviewed plan: " + ", ".join(unplanned))
    unknown = sorted(plan_references - changed_candidate_ids)
    if unknown:
        raise IntakeValidationError("reviewed plans reference candidates outside this intake: " + ", ".join(unknown))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "discovery_mesh_intake_validation",
        "valid": True,
        "summary": {
            "changed_path_count": len(paths),
            "candidate_count": candidate_count,
            "plan_count": plan_count,
            "referenced_candidate_count": len(plan_references),
        },
        "posture": {
            "canonical_paths_changed": False,
            "official_domain_candidates_only": True,
            "canonical_mutation_authority_unchanged": True,
            "non_advisory": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-mesh-activation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-plans")
    build.add_argument("--promotion-plan", type=Path, required=True)
    build.add_argument("--source-plan-path", required=True)
    build.add_argument("--run-token", required=True)
    build.add_argument("--output-root", type=Path, default=ROOT / PLAN_ROOT)
    build.add_argument("--manifest-output", type=Path, required=True)

    guard = subparsers.add_parser("guard")
    guard.add_argument("--root", type=Path, default=ROOT)
    guard.add_argument("--changed-paths-file", type=Path, required=True)
    guard.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "build-plans":
        paths, manifest = build_vendor_promotion_plans(
            load_json(args.promotion_plan),
            source_plan_path=args.source_plan_path,
            run_token=args.run_token,
            output_root=args.output_root,
        )
        manifest["plan_paths"] = [display_path(path, ROOT) for path in paths]
        args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
        return 0

    changed_paths = args.changed_paths_file.read_text(encoding="utf-8").splitlines()
    report = validate_intake(args.root, changed_paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
