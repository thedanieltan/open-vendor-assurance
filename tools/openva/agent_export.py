"""WP33 Agent Export Contract.

Builds the static, deterministic, agent-facing JSON exports served at the
site URL under /public/... The exports expose the safe subset of catalog and
observation state: vendor identity, source locations, confidence, retrieval
method, latest observed health, and change state.

Static export contract only: no hosted API, no MCP server, no risk scoring,
no private or gated content. Exports are publish-time artifacts, never
committed; snapshot identity is commit SHA + content digest, not a
catalog-wide semantic version.

Input model (three classes):
1. committed catalog records from HEAD            -> vendor/source fields
2. committed WP32 event ledger                    -> changes/latest.json ONLY
3. latest source-maintenance run artifact         -> observations/latest.json,
   (latest-observations + freshness reports)         source_health,
                                                     last_observed_at, freshness

The committed event ledger is SPARSE (events only, no no-change
observations), so it is used for source_health/last_observed_at only as an
explicitly marked fallback when the run artifact is unavailable. When the run
artifact is present, the committed-event fallback is ignored entirely.

Determinism: the builder is a pure function of its inputs; commit_sha and
generated_at are injected, never computed inside payload construction. Each
file's digest is sha256 over canonical JSON of that file's payload EXCLUDING
its own snapshot block; the root index's exports map excludes the root index
itself, so no digest ever covers an object containing that digest.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT
from tools.openva.observation_ledger import DEFAULT_LEDGER_DIR, DOCTRINE, load_ledger_baseline
from tools.openva.pack import canonical_json, sha256_bytes

SCHEMA_VERSION = "0.1.0"

GUARANTEES = {
    "public_sources_only": True,
    "metadata_first": True,
    "non_advisory": True,
    "raw_documents_mirrored_by_default": False,
}

OBSERVATION_INPUT_RUN_ARTIFACT = "run_artifact"
OBSERVATION_INPUT_FALLBACK = "committed_events_fallback"
OBSERVATION_INPUT_NONE = "none"

AGENT_INDEX_FILE = "openva-agent-index.json"
VENDORS_INDEX_FILE = "vendors/index.json"
SOURCES_INDEX_FILE = "sources/index.json"
OBSERVATIONS_LATEST_FILE = "observations/latest.json"
CHANGES_LATEST_FILE = "changes/latest.json"
VENDOR_EXPORT_TEMPLATE = "vendors/{vendor_id}.json"

WORKSPACE_WRITEBACK_SOURCE_COLUMNS = {
    "dpa": "openva_dpa_url",
    "privacy_notice": "openva_privacy_url",
    "subprocessors_list": "openva_subprocessors_url",
    "security_page": "openva_security_url",
    "trust_center": "openva_trust_center_url",
}

WORKSPACE_WRITEBACK_COLUMNS = (
    "openva_match_status",
    "openva_vendor_id",
    "openva_vendor_name",
    "openva_dpa_url",
    "openva_privacy_url",
    "openva_subprocessors_url",
    "openva_security_url",
    "openva_trust_center_url",
    "openva_result_mode",
    "openva_notes",
    "openva_not_advice",
)

WORKSPACE_WRITEBACK_FORBIDDEN_ADVISORY_KEYS = frozenset(
    {
        "approval",
        "approved",
        "recommendation",
        "recommended",
        "risk_score",
        "risk_rating",
        "compliance_decision",
        "security_decision",
        "procurement_decision",
        "legal_opinion",
        "vendor_approval",
        "suitability",
    }
)


def load_records(root: Path, glob: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted(root.glob(glob)):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(record, dict):
            records.append(record)
    return records


def payload_digest(payload: dict[str, Any]) -> str:
    """Digest over the payload EXCLUDING its snapshot block."""
    material = {key: value for key, value in payload.items() if key != "snapshot"}
    return sha256_bytes(canonical_json(material))


def finalize(payload: dict[str, Any], *, commit_sha: str, generated_at: str) -> dict[str, Any]:
    digest = payload_digest(payload)
    return {
        **payload,
        "snapshot": {
            "commit_sha": commit_sha,
            "generated_at": generated_at,
            "digest": digest,
        },
    }


def real_hash(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("sha256:") and value != "sha256:TBD":
        return value
    return None


def _assert_non_advisory_workspace_payload(payload: dict[str, Any], *, where: str) -> None:
    forbidden = WORKSPACE_WRITEBACK_FORBIDDEN_ADVISORY_KEYS & set(payload)
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise ValueError(f"{where} carries forbidden advisory field(s): {names}")
    if payload.get("not_advice") is not True:
        raise ValueError(f"{where} must carry not_advice: true")


def _workspace_notes(source_pack: dict[str, Any]) -> str:
    notes = [str(note) for note in source_pack.get("notes") or [] if str(note).strip()]
    missing = sorted(str(item) for item in source_pack.get("missing_source_types") or [] if str(item).strip())
    ambiguous = sorted(str(item) for item in source_pack.get("ambiguous_source_types") or [] if str(item).strip())
    if missing:
        notes.append("missing: " + ",".join(missing))
    if ambiguous:
        notes.append("ambiguous: " + ",".join(ambiguous))
    return "; ".join(notes)


def workspace_writeback_row(source_pack: dict[str, Any]) -> dict[str, str]:
    """Project a Phase 3 source pack into stable workspace write-back columns.

    This is the Phase 7 export contract for CSV/spreadsheet/agent workspace
    write-back. It is intentionally connector-neutral: callers can write this row
    into Google Sheets, Notion, Jira, a CSV, or another workspace using their own
    authority. The row contains public source locator metadata only and carries
    no advisory, approval, risk, security, compliance, procurement, or legal
    conclusion.
    """
    _assert_non_advisory_workspace_payload(source_pack, where="source_pack")
    for index, source in enumerate(source_pack.get("sources") or []):
        if not isinstance(source, dict):
            raise ValueError(f"source_pack.sources[{index}] must be an object")
        _assert_non_advisory_workspace_payload(source, where=f"source_pack.sources[{index}]")

    vendor_input = source_pack.get("vendor_input") or {}
    matched_vendor = source_pack.get("matched_vendor") or {}
    row = {column: "" for column in WORKSPACE_WRITEBACK_COLUMNS}
    row["openva_match_status"] = str(source_pack.get("match_status") or "")
    row["openva_vendor_id"] = str(matched_vendor.get("vendor_id") or "")
    row["openva_vendor_name"] = str(
        matched_vendor.get("display_name") or vendor_input.get("display_name") or ""
    )
    row["openva_result_mode"] = str(source_pack.get("mode") or "")
    row["openva_notes"] = _workspace_notes(source_pack)
    row["openva_not_advice"] = "true"

    for source in source_pack.get("sources") or []:
        source_type = str(source.get("source_type") or "")
        column = WORKSPACE_WRITEBACK_SOURCE_COLUMNS.get(source_type)
        if column is None:
            continue
        if source.get("result_state") == "found" and source.get("source_url"):
            row[column] = str(source.get("source_url"))
    return row


def observation_entries(
    latest_observations: dict[str, Any] | None,
    ledger_baseline: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Resolve the observation-state input class.

    The run artifact is authoritative when present; the sparse committed
    event ledger is used only as an explicitly marked fallback.
    """
    if latest_observations is not None:
        entries = {
            str(entry.get("source_id")): entry
            for entry in latest_observations.get("sources", [])
            if entry.get("source_id")
        }
        return OBSERVATION_INPUT_RUN_ARTIFACT, entries
    if ledger_baseline:
        return OBSERVATION_INPUT_FALLBACK, dict(ledger_baseline)
    return OBSERVATION_INPUT_NONE, {}


def material_change_since_baseline(
    source_record: dict[str, Any],
    observation: dict[str, Any] | None,
) -> bool | None:
    change_detection = source_record.get("change_detection") or {}
    baseline = real_hash(change_detection.get("baseline_normalized_text_sha256"))
    observed = real_hash((observation or {}).get("normalized_text_sample_sha256"))
    if baseline and observed:
        return observed != baseline
    return None


def source_row(source_record: dict[str, Any], observation: dict[str, Any] | None) -> dict[str, Any]:
    canonical_confidence = (source_record.get("canonical_confidence") or {}).get("class")
    retrieval = source_record.get("retrieval") or {}
    # verified_scope is a committed source-classification fact, projected
    # verbatim (null when the record did not classify it) — the export never
    # invents scope from access_class. gated_child_content_observed is a
    # universal non-observation doctrine guarantee, not a measured result:
    # OpenVA never observes gated child documents, so it is always false.
    scope = source_record.get("verified_scope")
    return {
        "source_id": source_record.get("source_id"),
        "source_type": source_record.get("source_type"),
        "source_url": source_record.get("source_url"),
        "canonical_confidence": canonical_confidence,
        "retrieval_method": retrieval.get("method"),
        "machine_readable": retrieval.get("machine_readable"),
        "source_health": (observation or {}).get("source_health_status"),
        "last_observed_at": (observation or {}).get("observed_at"),
        "material_change_since_baseline": material_change_since_baseline(source_record, observation),
        "verified_scope": scope if scope in ("full_content", "landing_page_only") else None,
        "gated_child_content_observed": False,
    }


def legal_entity_projection(entity: dict[str, Any]) -> dict[str, Any]:
    """Public legal-entity identity fields only — the same shape the matcher emits.

    Source-backed public identity metadata (legal_name, jurisdiction, typed
    registration identifier, registered address). Carries no private or
    self-certifying content."""
    projected = {
        "entity_id": entity.get("entity_id"),
        "vendor_id": entity.get("vendor_id"),
        "legal_name": entity.get("legal_name"),
        "jurisdiction": entity.get("jurisdiction"),
        "registration_number": entity.get("registration_number"),
        "catalog_status": entity.get("catalog_status"),
        "registered_address": entity.get("registered_address"),
    }
    for key in ("identifier_scheme", "identifier_authority", "identifier_authority_url"):
        if entity.get(key) is not None:
            projected[key] = entity.get(key)
    return projected


def vendor_export_payload(
    vendor: dict[str, Any],
    sources: list[dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    legal_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [
        source_row(source, observations.get(str(source.get("source_id"))))
        for source in sorted(sources, key=lambda record: str(record.get("source_id") or ""))
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "vendor_id": vendor.get("vendor_id"),
        "canonical_name": vendor.get("display_name"),
        "domains": list(vendor.get("official_domains") or []),
        # WP36: expose lifecycle state so provisional/promoted/quarantined
        # vendors are visible to consumers rather than silently dropped.
        "catalog_status": vendor.get("catalog_status"),
        "sources": rows,
        "not_advice": True,
    }
    # Optional, backward-compatible (versioning-policy 0.1.x additive optional field):
    # the key is emitted only when the vendor has legal-entity records, so vendors
    # without them (the entire shipped catalogue today) keep a byte-identical export.
    entities = sorted(legal_entities or [], key=lambda record: str(record.get("entity_id") or ""))
    if entities:
        payload["legal_entities"] = [legal_entity_projection(entity) for entity in entities]
    return payload


def observation_projection(entry: dict[str, Any], freshness: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "vendor_id": entry.get("vendor_id"),
        "source_id": entry.get("source_id"),
        "source_url": entry.get("source_url"),
        "observed_at": entry.get("observed_at"),
        "observation_id": entry.get("observation_id"),
        "final_url": entry.get("final_url"),
        "http_status": entry.get("http_status"),
        "source_health": entry.get("source_health_status"),
        "change_class": entry.get("change_class"),
        "retrieval_method": entry.get("retrieval_method"),
        "raw_sample_sha256": entry.get("raw_sample_sha256"),
        "normalized_text_sample_sha256": entry.get("normalized_text_sample_sha256"),
        "review_signal": entry.get("review_signal"),
        "freshness": freshness,
    }


def change_projection(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_id": event.get("vendor_id"),
        "source_id": event.get("source_id"),
        "source_url": event.get("source_url"),
        "observed_at": event.get("observed_at"),
        "observation_id": event.get("observation_id"),
        "event_type": event.get("event_type"),
        "change_class": event.get("change_class"),
        "final_url": event.get("final_url"),
        "http_status": event.get("http_status"),
        "source_health": event.get("source_health_status"),
        "review_signal": event.get("review_signal"),
    }


def write_export(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_agent_exports(
    *,
    root: Path = ROOT,
    out_dir: Path,
    commit_sha: str,
    generated_at: str,
    latest_observations: dict[str, Any] | None = None,
    freshness_report: dict[str, Any] | None = None,
    ledger_dir: Path | None = None,
) -> dict[str, Any]:
    ledger_dir = ledger_dir if ledger_dir is not None else (root / "maintenance" / "source-observations" / "events")
    vendors = sorted(
        load_records(root, "data/vendors/*/vendor.yaml"),
        key=lambda record: str(record.get("vendor_id") or ""),
    )
    sources = load_records(root, "data/vendors/*/sources/*.yaml")
    sources_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        sources_by_vendor.setdefault(str(source.get("vendor_id") or ""), []).append(source)

    # Only VERIFIED (canonical) legal entities are exported. Canonical entities carry
    # at least one verification_source_id by schema invariant, so the export stays
    # public-source-backed; unverified stubs are excluded (consistent with their
    # exclusion from contracting-entity-resolution). This keeps the export's
    # public_sources_only guarantee honest.
    legal_entities = load_records(root, "data/vendors/*/legal_entities/*.yaml")
    legal_entities_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for entity in legal_entities:
        if entity.get("catalog_status") != "canonical":
            continue
        legal_entities_by_vendor.setdefault(str(entity.get("vendor_id") or ""), []).append(entity)

    ledger_baseline = load_ledger_baseline(ledger_dir)
    observation_input, observations = observation_entries(latest_observations, ledger_baseline)
    freshness_by_source = {
        str(row.get("source_id")): row.get("freshness")
        for row in (freshness_report or {}).get("sources", [])
        if row.get("source_id")
    }

    exports_map: dict[str, dict[str, str]] = {}
    vendor_exports: list[dict[str, str]] = []

    def emit(rel_path: str, payload: dict[str, Any]) -> dict[str, Any]:
        document = finalize(payload, commit_sha=commit_sha, generated_at=generated_at)
        write_export(out_dir / rel_path, document)
        return document

    vendor_index_rows = []
    for vendor in vendors:
        vendor_id = str(vendor.get("vendor_id"))
        rel_path = VENDOR_EXPORT_TEMPLATE.format(vendor_id=vendor_id)
        document = emit(
            rel_path,
            vendor_export_payload(
                vendor,
                sources_by_vendor.get(vendor_id, []),
                observations,
                legal_entities_by_vendor.get(vendor_id, []),
            ),
        )
        vendor_exports.append({"vendor_id": vendor_id, "path": rel_path, "digest": document["snapshot"]["digest"]})
        vendor_index_rows.append(
            {
                "vendor_id": vendor_id,
                "canonical_name": vendor.get("display_name"),
                "domains": list(vendor.get("official_domains") or []),
                "catalog_status": vendor.get("catalog_status"),
                "source_count": len(sources_by_vendor.get(vendor_id, [])),
                "export_path": rel_path,
            }
        )

    vendors_index = emit(
        VENDORS_INDEX_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "doctrine": DOCTRINE,
            "count": len(vendor_index_rows),
            "vendors": vendor_index_rows,
            "not_advice": True,
        },
    )

    flat_rows = []
    for vendor in vendors:
        vendor_id = str(vendor.get("vendor_id"))
        for source in sorted(sources_by_vendor.get(vendor_id, []), key=lambda record: str(record.get("source_id") or "")):
            flat_rows.append(
                {"vendor_id": vendor_id, **source_row(source, observations.get(str(source.get("source_id"))))}
            )
    sources_index = emit(
        SOURCES_INDEX_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "doctrine": DOCTRINE,
            "count": len(flat_rows),
            "sources": flat_rows,
            "not_advice": True,
        },
    )

    observation_rows = [
        observation_projection(entry, freshness_by_source.get(source_id))
        for source_id, entry in sorted(observations.items())
    ]
    observations_latest = emit(
        OBSERVATIONS_LATEST_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "doctrine": DOCTRINE,
            "observation_input": observation_input,
            "count": len(observation_rows),
            "sources": observation_rows,
            "not_advice": True,
        },
    )

    change_rows = [change_projection(event) for _, event in sorted(ledger_baseline.items())]
    by_event_type: dict[str, int] = {}
    for row in change_rows:
        key = str(row.get("event_type"))
        by_event_type[key] = by_event_type.get(key, 0) + 1
    changes_latest = emit(
        CHANGES_LATEST_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "doctrine": DOCTRINE,
            "count": len(change_rows),
            "by_event_type": dict(sorted(by_event_type.items())),
            "sources": change_rows,
            "not_advice": True,
        },
    )

    # The exports map excludes the root index itself; the root index's own
    # digest is computed over its payload excluding its snapshot block, so no
    # digest covers an object containing that digest.
    exports_map = {
        "vendors_index": {"path": VENDORS_INDEX_FILE, "digest": vendors_index["snapshot"]["digest"]},
        "sources_index": {"path": SOURCES_INDEX_FILE, "digest": sources_index["snapshot"]["digest"]},
        "observations_latest": {"path": OBSERVATIONS_LATEST_FILE, "digest": observations_latest["snapshot"]["digest"]},
        "changes_latest": {"path": CHANGES_LATEST_FILE, "digest": changes_latest["snapshot"]["digest"]},
    }
    agent_index = emit(
        AGENT_INDEX_FILE,
        {
            "schema_version": SCHEMA_VERSION,
            "doctrine": DOCTRINE,
            "observation_input": observation_input,
            "guarantees": GUARANTEES,
            "counts": {"vendors": len(vendor_index_rows), "sources": len(flat_rows)},
            "exports": exports_map,
            "vendor_export_template": VENDOR_EXPORT_TEMPLATE,
            "vendor_exports": vendor_exports,
            "not_advice": True,
        },
    )

    return {
        "observation_input": observation_input,
        "vendors": len(vendor_index_rows),
        "sources": len(flat_rows),
        "observations": len(observation_rows),
        "changes": len(change_rows),
        "agent_index_digest": agent_index["snapshot"]["digest"],
    }


def resolve_commit_sha(value: str | None) -> str:
    if value:
        return value
    env = os.environ.get("GITHUB_SHA")
    if env:
        return env
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-agent-export")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build the agent export tree")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--commit-sha", default=None)
    build.add_argument("--generated-at", default=None)
    build.add_argument("--latest-observations", type=Path, default=None)
    build.add_argument("--freshness-report", type=Path, default=None)
    build.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    args = parser.parse_args()

    summary = build_agent_exports(
        out_dir=args.out,
        commit_sha=resolve_commit_sha(args.commit_sha),
        generated_at=args.generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        latest_observations=load_optional_json(args.latest_observations),
        freshness_report=load_optional_json(args.freshness_report),
        ledger_dir=args.ledger_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
