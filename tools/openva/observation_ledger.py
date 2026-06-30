"""WP32 Observation Ledger v2.

OpenVA does not version vendor truth. OpenVA observes vendor-published
sources and records source state, provenance, hashes, timestamps, and change
signals.

This module turns a source-verification report (the existing fetch pass) into
observation records, change events, and latest-state/freshness/review reports.
Per-run observation records and reports are artifacts. The durable ledger is a
compact, append-only set of monthly NDJSON event files under
``maintenance/source-observations/events/``; rows are appended only by the
``append`` command for reviewed-PR use. Workflows never commit ledger files.

Two axes stay separate: *can we reach it?* is ``source_health.status``;
*did it materially vary?* is ``change_class``/``event_type``.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.submission_verify import infer_retrieval_method

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "0.1.0"
DOCTRINE = (
    "OpenVA does not version vendor truth. OpenVA observes vendor-published "
    "sources and records source state, provenance, hashes, timestamps, and "
    "change signals."
)

DEFAULT_LEDGER_DIR = ROOT / "maintenance" / "source-observations" / "events"
DEFAULT_LATEST_INDEX = ROOT / "maintenance" / "source-observations" / "latest-observations.json"
DEFAULT_SLA_CONFIG = ROOT / "config" / "observation-sla.yaml"

TBD = "sha256:TBD"

HEALTH_STATUSES = ("reachable", "unreachable", "gated", "bot_protected", "redirected", "quarantined")
ACCESS_RESTRICTED_HEALTH = {"gated", "bot_protected"}

# verification_status -> source_health.status (reachability/access only;
# content variation is a change signal, never a health status).
HEALTH_BY_VERIFICATION_STATUS = {
    "ok": "reachable",
    "possible_mismatch": "reachable",
    "suspect_inferred_url": "reachable",
    "redirected": "redirected",
    "homepage_or_generic_redirect": "redirected",
    "gated_or_login_required": "gated",
    "forbidden_unknown": "gated",
    "bot_protected": "bot_protected",
    "unreachable": "unreachable",
    "not_found": "unreachable",
    "gone": "unreachable",
    "server_error": "unreachable",
    "client_error": "unreachable",
    "rate_limited": "unreachable",
    "soft_not_found": "unreachable",
}

CHANGE_CLASSES = ("none", "non_material", "material_possible", "material_confirmed", "access_changed", "redirect_changed")
EVENT_TYPES = (
    "first_observed",
    "access_changed",
    "redirect_changed",
    "material_confirmed",
    "material_possible",
    "non_material_change",
    "health_changed",
)

REVIEW_HEALTH = {"gated", "bot_protected", "unreachable", "quarantined"}
REVIEW_CHANGE_CLASSES = {"material_possible", "material_confirmed", "access_changed", "redirect_changed"}


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return cleaned or "unknown"


def parse_when(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def real_hash(value: str | None) -> str | None:
    if value and value != TBD:
        return value
    return None


def load_sla_config(path: Path = DEFAULT_SLA_CONFIG) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "default" not in data:
        raise ValueError(f"{path}: expected SLA config mapping with a default block")
    return data


def sla_for(source_type: str | None, sla_config: dict[str, Any]) -> dict[str, int]:
    overrides = sla_config.get("source_type_overrides") or {}
    chosen = overrides.get(str(source_type or ""), sla_config["default"])
    return {
        "stale_after_days": int(chosen["stale_after_days"]),
        "expired_after_days": int(chosen["expired_after_days"]),
    }


def health_for(verification_row: dict[str, Any], source_record: dict[str, Any] | None) -> str:
    if source_record and str(source_record.get("catalog_status") or "") == "quarantined":
        return "quarantined"
    status = str(verification_row.get("verification_status") or "")
    mapped = HEALTH_BY_VERIFICATION_STATUS.get(status)
    if mapped:
        return mapped
    http_status = verification_row.get("http_status")
    if isinstance(http_status, int) and 200 <= http_status < 300:
        return "reachable"
    return "unreachable"


def retrieval_method_for(verification_row: dict[str, Any], source_record: dict[str, Any] | None) -> str | None:
    if source_record:
        retrieval = source_record.get("retrieval") or {}
        method = retrieval.get("method")
        if method:
            return str(method)
    return infer_retrieval_method(
        verification_row.get("content_type"),
        verification_row.get("final_url"),
        None,
    )


def curated_baseline_hash(source_record: dict[str, Any] | None) -> str | None:
    if not source_record:
        return None
    change_detection = source_record.get("change_detection") or {}
    return real_hash(change_detection.get("baseline_normalized_text_sha256"))


def normalized_url(value: str | None) -> str:
    return str(value or "").rstrip("/")


def classify_change(
    *,
    previous: dict[str, Any] | None,
    health: str,
    final_url: str | None,
    raw_hash: str | None,
    normalized_hash: str | None,
    curated_baseline: str | None,
) -> tuple[str, bool | None]:
    """Return (change_class, material_change) with documented precedence:
    access_changed > redirect_changed > material_confirmed > material_possible
    > non_material > none."""
    material_change: bool | None
    if curated_baseline and normalized_hash:
        material_change = normalized_hash != curated_baseline
    elif curated_baseline or normalized_hash:
        material_change = None
    else:
        material_change = None

    if previous is None:
        return "none", material_change

    previous_health = str(previous.get("source_health_status") or "")
    if (previous_health in ACCESS_RESTRICTED_HEALTH) != (health in ACCESS_RESTRICTED_HEALTH):
        return "access_changed", material_change
    if normalized_url(previous.get("final_url")) != normalized_url(final_url):
        return "redirect_changed", material_change
    previous_normalized = real_hash(previous.get("normalized_text_sample_sha256"))
    # A change event fires when content MOVES this run, not while a known
    # divergence from the curated baseline persists (material_change stays
    # true in that case, but no repeat event is emitted).
    content_moved = bool(normalized_hash) and (previous_normalized is None or normalized_hash != previous_normalized)
    if curated_baseline and normalized_hash and normalized_hash != curated_baseline and content_moved:
        return "material_confirmed", True
    if not curated_baseline and previous_normalized and normalized_hash and normalized_hash != previous_normalized:
        return "material_possible", material_change
    previous_raw = real_hash(previous.get("raw_sample_sha256"))
    if (
        previous_raw
        and raw_hash
        and raw_hash != previous_raw
        and previous_normalized
        and normalized_hash
        and normalized_hash == previous_normalized
    ):
        return "non_material", material_change
    return "none", material_change


def event_type_for(
    *,
    previous: dict[str, Any] | None,
    change_class: str,
    health: str,
) -> str | None:
    """Event-type precedence: access_changed > redirect_changed >
    material_confirmed > material_possible > health_changed >
    non_material_change. First observation is always first_observed."""
    if previous is None:
        return "first_observed"
    if change_class in {"access_changed", "redirect_changed", "material_confirmed", "material_possible"}:
        return change_class
    previous_health = str(previous.get("source_health_status") or "")
    if previous_health and previous_health != health:
        return "health_changed"
    if change_class == "non_material":
        return "non_material_change"
    return None


def review_signal_for(change_class: str, health: str, first_observed: bool) -> dict[str, Any]:
    if change_class in REVIEW_CHANGE_CLASSES:
        return {"required": True, "reason": f"change_class_{change_class}"}
    if health in REVIEW_HEALTH:
        return {"required": True, "reason": f"source_health_{health}"}
    if first_observed:
        return {"required": False, "reason": "first_observation"}
    return {"required": False, "reason": None}


def source_records_by_id(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "data" / "vendors").glob("*/sources/*.yaml")):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(record, dict) and record.get("source_id"):
            records[str(record["source_id"])] = record
    return records


def ledger_files(ledger_dir: Path) -> list[Path]:
    if not ledger_dir.exists():
        return []
    return sorted(ledger_dir.glob("*.ndjson"))


def load_ledger_events(ledger_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in ledger_files(ledger_dir):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def load_ledger_baseline(ledger_dir: Path) -> dict[str, dict[str, Any]]:
    """Latest committed event per source. Events exist only when something
    changed, so this baseline reflects last-event state, not last-observation
    time; an optional latest-index baseline refines it."""
    baseline: dict[str, dict[str, Any]] = {}
    for event in load_ledger_events(ledger_dir):
        source_id = str(event.get("source_id") or "")
        if not source_id:
            continue
        current = baseline.get(source_id)
        if current is None or str(event.get("observed_at") or "") >= str(current.get("observed_at") or ""):
            baseline[source_id] = event
    return baseline


def merge_baselines(
    ledger_baseline: dict[str, dict[str, Any]],
    latest_index_baseline: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    merged = dict(ledger_baseline)
    for source_id, entry in (latest_index_baseline or {}).items():
        current = merged.get(source_id)
        if current is None or str(entry.get("observed_at") or "") >= str(current.get("observed_at") or ""):
            merged[source_id] = entry
    return merged


def baseline_from_latest_index(latest_index: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not latest_index:
        return {}
    validate_latest_index(latest_index)
    return {
        str(entry.get("source_id")): entry
        for entry in latest_index.get("sources", [])
        if entry.get("source_id")
    }


def validate_latest_index(latest_index: dict[str, Any]) -> None:
    if not isinstance(latest_index, dict):
        raise ValueError("latest observations index must be a JSON object")
    if latest_index.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("latest observations index schema_version mismatch")
    if latest_index.get("report_type") != "latest_observations_index":
        raise ValueError("latest observations index report_type mismatch")
    if latest_index.get("doctrine") != DOCTRINE or latest_index.get("not_advice") is not True:
        raise ValueError("latest observations index missing doctrine boundary")
    sources = latest_index.get("sources")
    if not isinstance(sources, list):
        raise ValueError("latest observations index sources must be a list")
    seen: set[str] = set()
    previous_key: tuple[str, str] | None = None
    required = {
        "source_id",
        "vendor_id",
        "source_url",
        "observed_at",
        "observation_id",
        "source_health_status",
        "change_class",
        "carried_forward",
    }
    for index, entry in enumerate(sources):
        if not isinstance(entry, dict):
            raise ValueError(f"latest observations index source {index} must be an object")
        missing = sorted(name for name in required if name not in entry)
        if missing:
            raise ValueError(f"latest observations index source {index} missing {', '.join(missing)}")
        source_id = str(entry.get("source_id") or "")
        if not source_id:
            raise ValueError(f"latest observations index source {index} missing source_id")
        if source_id in seen:
            raise ValueError(f"duplicate latest observation source_id: {source_id}")
        seen.add(source_id)
        observed_at = str(entry.get("observed_at") or "")
        if observed_at:
            parse_when(observed_at)
        key = (str(entry.get("vendor_id") or ""), source_id)
        if previous_key is not None and key < previous_key:
            raise ValueError("latest observations index sources must be sorted by vendor_id, source_id")
        previous_key = key


def load_latest_index(path: Path = DEFAULT_LATEST_INDEX) -> dict[str, Any] | None:
    if not path.exists():
        return None
    latest_index = json.loads(path.read_text(encoding="utf-8"))
    validate_latest_index(latest_index)
    return latest_index


def build_observation_records(
    verification_report: dict[str, Any],
    *,
    baseline: dict[str, dict[str, Any]],
    source_records: dict[str, dict[str, Any]],
    run_id: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Observation records for sources present in the verification report
    only (the verified shard). Sources absent from the run produce no records
    and no events; the latest index carries their prior state forward."""
    records: list[dict[str, Any]] = []
    run_slug = slug(run_id)
    date_part = observed_at[:10]
    rows = sorted(
        verification_report.get("sources", []),
        key=lambda row: (str(row.get("vendor_id") or ""), str(row.get("source_id") or "")),
    )
    for row in rows:
        source_id = str(row.get("source_id") or "")
        if not source_id:
            continue
        source_record = source_records.get(source_id)
        previous = baseline.get(source_id)
        health = health_for(row, source_record)
        raw_hash = real_hash(row.get("raw_sample_sha256"))
        normalized_hash = real_hash(row.get("normalized_text_sample_sha256"))
        change_class, material_change = classify_change(
            previous=previous,
            health=health,
            final_url=row.get("final_url"),
            raw_hash=raw_hash,
            normalized_hash=normalized_hash,
            curated_baseline=curated_baseline_hash(source_record),
        )
        first_observed = previous is None
        records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "observation_id": f"{slug(source_id)}-{date_part}-{run_slug}",
                "vendor_id": row.get("vendor_id"),
                "source_id": source_id,
                "source_url": row.get("source_url"),
                "observed_at": observed_at,
                "run_id": run_id,
                "verification_status": row.get("verification_status"),
                "http_status": row.get("http_status"),
                "final_url": row.get("final_url"),
                "retrieval_method": retrieval_method_for(row, source_record),
                "raw_sample_sha256": row.get("raw_sample_sha256"),
                "normalized_text_sample_sha256": row.get("normalized_text_sample_sha256"),
                "material_change": material_change,
                "change_class": change_class,
                "source_health": {"status": health},
                "previous_observation_id": (previous or {}).get("observation_id"),
                "first_observed": first_observed,
                "event_type": event_type_for(previous=previous, change_class=change_class, health=health),
                "review_signal": review_signal_for(change_class, health, first_observed),
                "not_advice": True,
            }
        )
    return records


def build_change_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for record in records:
        event_type = record.get("event_type")
        if not event_type:
            continue
        events.append(
            {
                "schema_version": SCHEMA_VERSION,
                "ledger_record_id": f"{record['observation_id']}-{slug(event_type)}",
                "vendor_id": record["vendor_id"],
                "source_id": record["source_id"],
                "source_url": record["source_url"],
                "observed_at": record["observed_at"],
                "run_id": record["run_id"],
                "event_type": event_type,
                "change_class": record["change_class"],
                "previous_observation_id": record["previous_observation_id"],
                "observation_id": record["observation_id"],
                "final_url": record["final_url"],
                "http_status": record["http_status"],
                "source_health_status": record["source_health"]["status"],
                "raw_sample_sha256": record["raw_sample_sha256"],
                "normalized_text_sample_sha256": record["normalized_text_sample_sha256"],
                "review_signal": record["review_signal"],
                "not_advice": True,
            }
        )
    return events


def latest_entry_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": record["source_id"],
        "vendor_id": record["vendor_id"],
        "source_url": record["source_url"],
        "observed_at": record["observed_at"],
        "observation_id": record["observation_id"],
        "final_url": record["final_url"],
        "http_status": record["http_status"],
        "source_health_status": record["source_health"]["status"],
        "change_class": record["change_class"],
        "retrieval_method": record["retrieval_method"],
        "raw_sample_sha256": record["raw_sample_sha256"],
        "normalized_text_sample_sha256": record["normalized_text_sample_sha256"],
        "review_signal": record["review_signal"],
        "carried_forward": False,
    }


def latest_entry_from_baseline(source_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "vendor_id": entry.get("vendor_id"),
        "source_url": entry.get("source_url"),
        "observed_at": entry.get("observed_at"),
        "observation_id": entry.get("observation_id"),
        "final_url": entry.get("final_url"),
        "http_status": entry.get("http_status"),
        "source_health_status": entry.get("source_health_status"),
        "change_class": entry.get("change_class"),
        "retrieval_method": entry.get("retrieval_method"),
        "raw_sample_sha256": entry.get("raw_sample_sha256"),
        "normalized_text_sample_sha256": entry.get("normalized_text_sample_sha256"),
        "review_signal": entry.get("review_signal"),
        "carried_forward": True,
    }


def build_latest_index(
    records: list[dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    *,
    generated_at: str,
) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {
        source_id: latest_entry_from_baseline(source_id, entry)
        for source_id, entry in baseline.items()
    }
    for record in records:
        entries[record["source_id"]] = latest_entry_from_record(record)
    ordered = sorted(entries.values(), key=lambda entry: (str(entry.get("vendor_id") or ""), str(entry.get("source_id") or "")))
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "latest_observations_index",
        "generated_at": generated_at,
        "doctrine": DOCTRINE,
        "summary": {
            "source_count": len(ordered),
            "observed_this_run": sum(1 for entry in ordered if not entry["carried_forward"]),
            "carried_forward": sum(1 for entry in ordered if entry["carried_forward"]),
        },
        "sources": ordered,
        "not_advice": True,
    }


def freshness_for(entry: dict[str, Any], sla_config: dict[str, Any], now: datetime, source_type: str | None) -> dict[str, Any]:
    observed_at = entry.get("observed_at")
    sla = sla_for(source_type, sla_config)
    if not observed_at:
        return {"status": "unknown", "observed_within_sla": False, "age_days": None, **sla}
    age_days = max(0, (now - parse_when(str(observed_at))).days)
    if age_days > sla["expired_after_days"]:
        status = "expired"
    elif age_days > sla["stale_after_days"]:
        status = "stale"
    else:
        status = "fresh"
    return {
        "status": status,
        "observed_within_sla": age_days <= sla["stale_after_days"],
        "age_days": age_days,
        **sla,
    }


def build_freshness_report(
    latest_index: dict[str, Any],
    sla_config: dict[str, Any],
    *,
    now: datetime,
    source_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    counts = {"fresh": 0, "stale": 0, "expired": 0, "unknown": 0}
    for entry in latest_index.get("sources", []):
        source_record = source_records.get(str(entry.get("source_id")))
        source_type = str(source_record.get("source_type")) if source_record else None
        freshness = freshness_for(entry, sla_config, now, source_type)
        counts[freshness["status"]] += 1
        rows.append(
            {
                "vendor_id": entry.get("vendor_id"),
                "source_id": entry.get("source_id"),
                "source_type": source_type,
                "observed_at": entry.get("observed_at"),
                "freshness": freshness,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "source_freshness_report",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "doctrine": DOCTRINE,
        "summary": counts,
        "sources": rows,
        "not_advice": True,
    }


def build_changed_report(records: list[dict[str, Any]], *, generated_at: str) -> dict[str, Any]:
    changed = [record for record in records if record["change_class"] != "none"]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "changed_since_last_observation",
        "generated_at": generated_at,
        "doctrine": DOCTRINE,
        "summary": {
            "changed_count": len(changed),
            "by_change_class": {
                change_class: sum(1 for record in changed if record["change_class"] == change_class)
                for change_class in CHANGE_CLASSES
                if any(record["change_class"] == change_class for record in changed)
            },
        },
        "sources": changed,
        "not_advice": True,
    }


def build_review_report(records: list[dict[str, Any]], *, generated_at: str) -> dict[str, Any]:
    flagged = [record for record in records if record["review_signal"]["required"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "sources_requiring_review",
        "generated_at": generated_at,
        "doctrine": DOCTRINE,
        "summary": {
            "review_required_count": len(flagged),
            "by_reason": {
                reason: sum(1 for record in flagged if record["review_signal"]["reason"] == reason)
                for reason in sorted({record["review_signal"]["reason"] for record in flagged})
            },
        },
        "sources": flagged,
        "not_advice": True,
    }


def month_key(observed_at: str) -> str:
    return str(observed_at)[:7]


def last_observed_per_source(ledger_dir: Path) -> dict[str, str]:
    last: dict[str, str] = {}
    for event in load_ledger_events(ledger_dir):
        source_id = str(event.get("source_id") or "")
        observed_at = str(event.get("observed_at") or "")
        if source_id and observed_at > last.get(source_id, ""):
            last[source_id] = observed_at
    return last


def append_ledger(delta: list[dict[str, Any]], ledger_dir: Path) -> list[Path]:
    """Append event rows to the monthly committed ledger files.

    Append-only discipline: existing lines are never rewritten or reordered;
    a delta row whose observed_at predates the last committed row for the
    same source is refused.
    """
    last = last_observed_per_source(ledger_dir)
    existing_ids = {str(event.get("ledger_record_id")) for event in load_ledger_events(ledger_dir)}
    for row in delta:
        source_id = str(row.get("source_id") or "")
        observed_at = str(row.get("observed_at") or "")
        if str(row.get("ledger_record_id")) in existing_ids:
            raise ValueError(f"duplicate ledger_record_id: {row.get('ledger_record_id')}")
        if source_id in last and observed_at < last[source_id]:
            raise ValueError(
                f"out-of-order append refused for {source_id}: {observed_at} predates {last[source_id]}"
            )
    touched: list[Path] = []
    ledger_dir.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[dict[str, Any]]] = {}
    for row in delta:
        by_month.setdefault(month_key(str(row["observed_at"])), []).append(row)
    for month, rows in sorted(by_month.items()):
        path = ledger_dir / f"{month}.ndjson"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        touched.append(path)
    return touched


def query_events(
    events: list[dict[str, Any]],
    *,
    changed_since: str | None = None,
    access_changed: bool = False,
    redirect_changed: bool = False,
    material_change: bool = False,
) -> list[dict[str, Any]]:
    rows = events
    if changed_since:
        rows = [event for event in rows if str(event.get("observed_at") or "") >= changed_since]
    if access_changed:
        rows = [event for event in rows if event.get("event_type") == "access_changed"]
    if redirect_changed:
        rows = [event for event in rows if event.get("event_type") == "redirect_changed"]
    if material_change:
        rows = [event for event in rows if event.get("event_type") in {"material_confirmed", "material_possible"}]
    return sorted(rows, key=lambda event: (str(event.get("observed_at") or ""), str(event.get("source_id") or "")))


def stale_sources(
    latest_index: dict[str, Any],
    sla_config: dict[str, Any],
    *,
    now: datetime,
    source_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    report = build_freshness_report(latest_index, sla_config, now=now, source_records=source_records)
    return [row for row in report["sources"] if row["freshness"]["status"] in {"stale", "expired", "unknown"}]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def build_outputs(
    verification_report: dict[str, Any],
    *,
    output_dir: Path,
    run_id: str,
    observed_at: str,
    now: datetime,
    root: Path = ROOT,
    ledger_dir: Path | None = None,
    baseline_index: dict[str, Any] | None = None,
    sla_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger_dir = ledger_dir if ledger_dir is not None else DEFAULT_LEDGER_DIR
    sla = sla_config or load_sla_config()
    source_records = source_records_by_id(root)
    baseline = merge_baselines(load_ledger_baseline(ledger_dir), baseline_from_latest_index(baseline_index))
    records = build_observation_records(
        verification_report,
        baseline=baseline,
        source_records=source_records,
        run_id=run_id,
        observed_at=observed_at,
    )
    events = build_change_events(records)
    latest = build_latest_index(records, baseline, generated_at=observed_at)
    freshness = build_freshness_report(latest, sla, now=now, source_records=source_records)
    changed = build_changed_report(records, generated_at=observed_at)
    review = build_review_report(records, generated_at=observed_at)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "observation-records.json", {
        "schema_version": SCHEMA_VERSION,
        "report_type": "observation_records",
        "generated_at": observed_at,
        "doctrine": DOCTRINE,
        "summary": {"record_count": len(records), "event_count": len(events)},
        "records": records,
        "not_advice": True,
    })
    write_json(output_dir / "latest-observations.json", latest)
    write_json(output_dir / "source-freshness-report.json", freshness)
    write_json(output_dir / "changed-since-last-observation.json", changed)
    write_json(output_dir / "sources-requiring-review.json", review)
    delta_path = output_dir / "observation-ledger-delta.ndjson"
    with delta_path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    return {
        "records": len(records),
        "events": len(events),
        "latest_sources": latest["summary"]["source_count"],
        "review_required": review["summary"]["review_required_count"],
        "freshness": freshness["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-observation-ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build observation records, reports, and a proposed ledger delta")
    build.add_argument("--verification-report", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--run-id", default="local")
    build.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    build.add_argument("--baseline", type=Path, default=None, help="Optional prior latest-observations.json")
    build.add_argument("--sla-config", type=Path, default=DEFAULT_SLA_CONFIG)

    append = subparsers.add_parser("append", help="Append a proposed delta to the committed ledger (reviewed-PR use only)")
    append.add_argument("--delta", type=Path, required=True)
    append.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)

    install_latest = subparsers.add_parser(
        "install-latest",
        help="Install a validated latest-observations index into committed derivative state",
    )
    install_latest.add_argument("--latest", type=Path, required=True)
    install_latest.add_argument("--out", type=Path, default=DEFAULT_LATEST_INDEX)

    query = subparsers.add_parser("query", help="Query the committed ledger and latest index")
    query.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    query.add_argument("--latest", type=Path, default=None, help="latest-observations.json for --stale-by-sla")
    query.add_argument("--sla-config", type=Path, default=DEFAULT_SLA_CONFIG)
    query.add_argument("--changed-since", default=None)
    query.add_argument("--stale-by-sla", action="store_true")
    query.add_argument("--access-changed", action="store_true")
    query.add_argument("--redirect-changed", action="store_true")
    query.add_argument("--material-change", action="store_true")

    args = parser.parse_args()
    now = datetime.now(UTC)

    if args.command == "build":
        verification_report = json.loads(args.verification_report.read_text(encoding="utf-8"))
        baseline_index = (
            json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
        )
        summary = build_outputs(
            verification_report,
            output_dir=args.output_dir,
            run_id=str(args.run_id),
            observed_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            now=now,
            ledger_dir=args.ledger_dir,
            baseline_index=baseline_index,
            sla_config=load_sla_config(args.sla_config),
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.command == "append":
        delta = [
            json.loads(line)
            for line in args.delta.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        touched = append_ledger(delta, args.ledger_dir)
        print(json.dumps({"appended": len(delta), "files": [path.as_posix() for path in touched]}, indent=2))
        return 0

    if args.command == "install-latest":
        latest_index = json.loads(args.latest.read_text(encoding="utf-8"))
        validate_latest_index(latest_index)
        write_json(args.out, latest_index)
        print(json.dumps({"installed": args.out.as_posix(), "sources": len(latest_index["sources"])}, indent=2))
        return 0

    if args.command == "query":
        if args.stale_by_sla:
            if not args.latest:
                parser.error("--stale-by-sla requires --latest")
            latest_index = json.loads(args.latest.read_text(encoding="utf-8"))
            rows = stale_sources(
                latest_index,
                load_sla_config(args.sla_config),
                now=now,
                source_records=source_records_by_id(),
            )
        else:
            rows = query_events(
                load_ledger_events(args.ledger_dir),
                changed_since=args.changed_since,
                access_changed=args.access_changed,
                redirect_changed=args.redirect_changed,
                material_change=args.material_change,
            )
        print(json.dumps({"count": len(rows), "rows": rows}, indent=2, sort_keys=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
