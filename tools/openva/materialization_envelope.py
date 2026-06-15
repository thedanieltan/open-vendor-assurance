"""Immutable evidence envelope for machine-provisional materialization."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.source_discovery import SOURCE_TYPE_REGISTRY
from tools.openva.source_verification import ROOT

ENVELOPE_TYPE = "machine_provisional_materialization"
REGISTRY_VERSION = "source_discovery_registry_0.2.0"
DEFAULT_EXPIRES_HOURS = 4


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def action_digest(action: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json({"vendor": action.get("vendor"), "source": action.get("source")}))


def source_digest(source: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(source))


def policy_digest(root: Path = ROOT) -> str:
    chunks: list[bytes] = []
    for rel in ("config/automerge-policy.yaml", "config/machine-evidence-thresholds.yaml"):
        path = root / rel
        if path.exists():
            chunks.append(path.read_bytes())
    return sha256_bytes(b"\n".join(chunks))


def artifact_entry(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix() if path.is_absolute() else path.as_posix(),
        "digest": file_digest(path if path.is_absolute() else root / path),
    }


def build_envelope(
    action: dict[str, Any],
    *,
    root: Path = ROOT,
    artifact_paths: dict[str, Path] | None = None,
    discovery_run_id: str | None = None,
    workflow_run_id: str | None = None,
    workflow_attempt: int | None = None,
    source_commit_sha: str | None = None,
    base_sha: str | None = None,
    generated_at: str | None = None,
    expires_hours: int = DEFAULT_EXPIRES_HOURS,
) -> dict[str, Any]:
    generated = parse_time(generated_at) if generated_at else datetime.now(UTC)
    expires_at = generated + timedelta(hours=expires_hours)
    vendor = action.get("vendor", {}) or {}
    source = action.get("source", {}) or {}
    artifacts = {
        name: artifact_entry(path, root)
        for name, path in (artifact_paths or {}).items()
        if path is not None
    }
    return {
        "schema_version": "0.1.0",
        "envelope_type": ENVELOPE_TYPE,
        "subject": {
            "candidate_vendor_id": vendor.get("candidate_vendor_id"),
            "candidate_source_id": source.get("candidate_source_id"),
        },
        "provenance": {
            "discovery_run_id": discovery_run_id,
            "discovery_workflow_run_id": workflow_run_id,
            "discovery_workflow_attempt": workflow_attempt,
            "source_commit_sha": source_commit_sha,
            "source_registry_version": REGISTRY_VERSION,
            "policy_digest": policy_digest(root),
        },
        "artifacts": artifacts,
        "selection": {
            "candidate_digest": action_digest(action),
            "selected_source_digest": source_digest(source),
            "competing_candidate_digests": [],
        },
        "validity": {
            "generated_at": generated.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "base_sha": base_sha,
        },
        "not_advice": True,
    }


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def verify_envelope(action: dict[str, Any], envelope: dict[str, Any], *, root: Path = ROOT, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    if envelope.get("schema_version") != "0.1.0":
        reasons.append("envelope_schema_version_invalid")
    if envelope.get("envelope_type") != ENVELOPE_TYPE:
        reasons.append("envelope_type_invalid")
    if envelope.get("not_advice") is not True:
        reasons.append("envelope_not_advice_not_true")
    subject = envelope.get("subject") or {}
    vendor = action.get("vendor", {}) or {}
    source = action.get("source", {}) or {}
    if subject.get("candidate_vendor_id") != vendor.get("candidate_vendor_id"):
        reasons.append("envelope_candidate_vendor_mismatch")
    if subject.get("candidate_source_id") != source.get("candidate_source_id"):
        reasons.append("envelope_candidate_source_mismatch")
    provenance = envelope.get("provenance") or {}
    if provenance.get("source_registry_version") != REGISTRY_VERSION:
        reasons.append("envelope_registry_version_mismatch")
    if provenance.get("policy_digest") != policy_digest(root):
        reasons.append("envelope_policy_digest_mismatch")
    selection = envelope.get("selection") or {}
    if selection.get("candidate_digest") != action_digest(action):
        reasons.append("envelope_candidate_digest_mismatch")
    if selection.get("selected_source_digest") != source_digest(source):
        reasons.append("envelope_selected_source_digest_mismatch")
    source_type = str(source.get("source_type_candidate") or "")
    if not SOURCE_TYPE_REGISTRY.get(source_type, {}).get("qualifies_for_vendor_materialization"):
        reasons.append(f"envelope_source_type_not_materialization:{source_type}")
    validity = envelope.get("validity") or {}
    expires_at = parse_time(validity.get("expires_at"))
    if expires_at is None:
        reasons.append("envelope_expires_at_missing")
    elif now > expires_at:
        reasons.append("envelope_expired")
    artifacts = envelope.get("artifacts") or {}
    if not isinstance(artifacts, dict) or not artifacts:
        reasons.append("envelope_artifacts_missing")
    else:
        for name, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                reasons.append(f"envelope_artifact_invalid:{name}")
                continue
            rel = artifact.get("path")
            digest = artifact.get("digest")
            if not rel or not digest:
                reasons.append(f"envelope_artifact_incomplete:{name}")
                continue
            path = Path(str(rel))
            path = path if path.is_absolute() else root / path
            if not path.exists():
                reasons.append(f"envelope_artifact_missing:{name}")
            elif file_digest(path) != digest:
                reasons.append(f"envelope_artifact_digest_mismatch:{name}")
    return reasons


def attach_envelopes_to_plan(
    plan: dict[str, Any],
    *,
    root: Path = ROOT,
    artifact_paths: dict[str, Path],
    discovery_run_id: str | None = None,
    workflow_run_id: str | None = None,
    workflow_attempt: int | None = None,
    source_commit_sha: str | None = None,
    base_sha: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    for action in plan.get("actions", []) or []:
        if action.get("action") == "strict_catalog_growth_promotion":
            action["materialization_envelope"] = build_envelope(
                action,
                root=root,
                artifact_paths=artifact_paths,
                discovery_run_id=discovery_run_id,
                workflow_run_id=workflow_run_id,
                workflow_attempt=workflow_attempt,
                source_commit_sha=source_commit_sha,
                base_sha=base_sha,
                generated_at=generated_at,
            )
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-materialization-envelope")
    subparsers = parser.add_subparsers(dest="command", required=True)
    attach = subparsers.add_parser("attach")
    attach.add_argument("--promotion-plan", type=Path, required=True)
    attach.add_argument("--vendor-candidate-report", type=Path, required=True)
    attach.add_argument("--source-discovery-report", type=Path, required=True)
    attach.add_argument("--eligibility-report", type=Path, required=True)
    attach.add_argument("--discovery-event-delta", type=Path)
    attach.add_argument("--output", type=Path, required=True)
    attach.add_argument("--discovery-run-id")
    attach.add_argument("--workflow-run-id")
    attach.add_argument("--workflow-attempt", type=int)
    attach.add_argument("--source-commit-sha")
    attach.add_argument("--base-sha")
    attach.add_argument("--generated-at")
    args = parser.parse_args(argv)

    if args.command == "attach":
        plan = load_json(args.promotion_plan)
        artifact_paths = {
            "vendor_candidate_report": args.vendor_candidate_report,
            "source_discovery_report": args.source_discovery_report,
            "eligibility_report": args.eligibility_report,
        }
        if args.discovery_event_delta:
            artifact_paths["discovery_event_delta"] = args.discovery_event_delta
        plan = attach_envelopes_to_plan(
            plan,
            artifact_paths=artifact_paths,
            discovery_run_id=args.discovery_run_id,
            workflow_run_id=args.workflow_run_id,
            workflow_attempt=args.workflow_attempt,
            source_commit_sha=args.source_commit_sha,
            base_sha=args.base_sha,
            generated_at=args.generated_at,
        )
        args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"actions": len(plan.get("actions", []) or [])}, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
