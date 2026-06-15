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


def verified_scope(source_record: dict[str, Any]) -> str:
    """How far content verification reached for this source.

    A public_landing_gated_docs source is, by classification, only
    landing-page-content-verified — its gated child documents are never
    inspected. An explicit record value wins; otherwise non-gated public
    sources are full_content.
    """
    explicit = source_record.get("verified_scope")
    if explicit in ("full_content", "landing_page_only"):
        return explicit
    if source_record.get("access_class") == "public_landing_gated_docs":
        return "landing_page_only"
    return "full_content"


def source_row(source_record: dict[str, Any], observation: dict[str, Any] | None) -> dict[str, Any]:
    canonical_confidence = (source_record.get("canonical_confidence") or {}).get("class")
    retrieval = source_record.get("retrieval") or {}
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
        "verified_scope": verified_scope(source_record),
        # Doctrine guarantee: OpenVA never observes gated child documents.
        "gated_child_content_observed": False,
    }


def vendor_export_payload(
    vendor: dict[str, Any],
    sources: list[dict[str, Any]],
    observations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = [
        source_row(source, observations.get(str(source.get("source_id"))))
        for source in sorted(sources, key=lambda record: str(record.get("source_id") or ""))
    ]
    return {
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
        document = emit(rel_path, vendor_export_payload(vendor, sources_by_vendor.get(vendor_id, []), observations))
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
