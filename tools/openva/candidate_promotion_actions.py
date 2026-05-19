from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.catalog_lifecycle import change_event
from tools.openva.indexes import build_indexes
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION
from tools.openva.source_verification import ROOT, display_path

HASH_TBD = "sha256:TBD"
CONFIDENCE_MAP = {
    "likely": "high",
    "possible": "medium",
    "candidate": "low",
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def source_id(vendor_id: str, source_type: str) -> str:
    return f"{vendor_id}-{source_type.replace('_', '-')}"


def artifact_type(source_type: str) -> str:
    if source_type == "other_public_source":
        return "other_public_artifact"
    return source_type


def candidate_path(action: dict[str, Any], root: Path) -> Path:
    if action.get("path"):
        return root / str(action["path"])
    return root / "data" / "vendors" / str(action["vendor_id"]) / "candidate_sources" / f"{action['candidate_source_id']}.yaml"


def validate_action(action: dict[str, Any]) -> None:
    if action.get("action") != REVIEWED_CANDIDATE_PROMOTION_ACTION:
        raise ValueError("unsupported candidate promotion action")
    if action.get("requires_human_review") is not True:
        raise ValueError("candidate promotion action must require review")
    if action.get("writes_canonical_sources") is not False:
        raise ValueError("promotion plan action must be non-mutating")
    if action.get("non_advisory") is not True:
        raise ValueError("candidate promotion action must be non-advisory")
    for field in ["vendor_id", "source_type", "candidate_source_id", "candidate_url"]:
        if not action.get(field):
            raise ValueError(f"candidate promotion action missing {field}")


def validate_candidate(candidate: dict[str, Any], action: dict[str, Any]) -> None:
    expected = {
        "vendor_id": action["vendor_id"],
        "candidate_source_id": action["candidate_source_id"],
        "source_type_candidate": action["source_type"],
        "candidate_url": action["candidate_url"],
    }
    for key, value in expected.items():
        if candidate.get(key) != value:
            raise ValueError(f"candidate {key} does not match reviewed action")
    if candidate.get("requires_review") is not True:
        raise ValueError("candidate source must require review")
    if candidate.get("not_advice") is not True:
        raise ValueError("candidate source must be non-advisory")
    evidence = candidate.get("evidence", {}) or {}
    if evidence.get("http_status") != 200:
        raise ValueError("candidate promotion requires HTTP 200 evidence")
    if not evidence.get("matched_terms"):
        raise ValueError("candidate promotion requires matched terms")


def source_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    vendor_id = str(candidate["vendor_id"])
    source_type = str(candidate["source_type_candidate"])
    evidence = candidate.get("evidence", {}) or {}
    confidence = CONFIDENCE_MAP.get(str(candidate.get("confidence", "candidate")), "low")
    return {
        "schema_version": "0.1.0",
        "source_id": source_id(vendor_id, source_type),
        "vendor_id": vendor_id,
        "source_type": source_type,
        "source_authority_class": "vendor_published",
        "title_native": str(evidence.get("page_title") or source_type.replace("_", " ").title()),
        "source_url": str(candidate["candidate_url"]),
        "source_language": "en",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "vendor",
            "collected_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "observer": "agent",
            "confidence": confidence,
        },
        "not_advice": True,
    }


def artifact_from_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "artifact_id": str(source["source_id"]),
        "vendor_id": str(source["vendor_id"]),
        "source_id": str(source["source_id"]),
        "artifact_type": artifact_type(str(source["source_type"])),
        "canonical_url": str(source["source_url"]),
        "source_language": str(source["source_language"]),
        "region_scope": [],
        "entity_scope": {"scope_type": "brand_surface", "entity_ids": []},
        "product_scope": [],
        "access_class": str(source["access_class"]),
        "rights_class": str(source["rights_class"]),
        "effective_or_published_at": None,
        "hashes": {
            "raw_sha256": HASH_TBD,
            "normalized_text_sha256": HASH_TBD,
            "hash_method": "metadata_plus_hash_only",
        },
        "storage": {
            "raw_document_stored": False,
            "extracted_text_stored": False,
            "screenshot_stored": False,
        },
        "not_advice": True,
    }


def apply_candidate_promotions(promotion_plan: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    actions = [
        action for action in promotion_plan.get("actions", []) or []
        if action.get("action") == REVIEWED_CANDIDATE_PROMOTION_ACTION
    ]
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    for action in actions:
        try:
            validate_action(action)
            c_path = candidate_path(action, root)
            candidate = load_yaml(c_path)
            validate_candidate(candidate, action)
            record = source_from_candidate(candidate)
            s_path = root / "data" / "vendors" / record["vendor_id"] / "sources" / f"{record['source_id']}.yaml"
            a_path = root / "data" / "vendors" / record["vendor_id"] / "artifacts" / f"{record['source_id']}.yaml"
            c_path_out = root / "data" / "vendors" / record["vendor_id"] / "changes" / f"candidate-promotion-{record['source_id']}.yaml"
            if s_path.exists():
                raise ValueError("canonical source already exists")
            if a_path.exists():
                raise ValueError("canonical artifact already exists")
            write_yaml(s_path, record)
            artifact = artifact_from_source(record)
            write_yaml(a_path, artifact)
            write_yaml(
                c_path_out,
                change_event(
                    change_id=f"candidate-promotion-{record['source_id']}",
                    vendor_id=str(record["vendor_id"]),
                    source_id=str(record["source_id"]),
                    artifact_id=str(artifact["artifact_id"]),
                    change_type="created",
                    detected_at=str(record["provenance"]["collected_at"]),
                    summary="Reviewed candidate source promoted to canonical public source metadata.",
                ),
            )
            applied.extend(
                [
                    {"action": "write", "path": display_path(s_path, root), "candidate_path": display_path(c_path, root)},
                    {"action": "write", "path": display_path(a_path, root), "candidate_path": display_path(c_path, root)},
                    {"action": "write", "path": display_path(c_path_out, root), "candidate_path": display_path(c_path, root)},
                ]
            )
        except ValueError as exc:
            skipped.append({"action": action, "reason": str(exc)})

    if root.resolve() == ROOT.resolve():
        build_indexes()
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "candidate_promotion_apply_report",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": True,
            "writes_canonical_sources": True,
            "non_advisory": True,
        },
        "summary": {
            "promotion_actions_seen": len(actions),
            "canonical_sources_written": sum(1 for item in applied if "/sources/" in item["path"]),
            "canonical_artifacts_written": sum(1 for item in applied if "/artifacts/" in item["path"]),
            "change_events_written": sum(1 for item in applied if "/changes/" in item["path"]),
            "skipped_actions": len(skipped),
        },
        "file_actions": applied,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-candidate-promotion-actions")
    parser.add_argument("command", choices={"apply"})
    parser.add_argument("--promotion-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "candidate-promotion-report.json")
    args = parser.parse_args()
    report = apply_candidate_promotions(load_json(args.promotion_plan))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
