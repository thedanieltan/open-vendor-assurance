"""Durable, idempotent orchestration for vendor breadth replenishment.

``vendor_breadth_mesh`` owns provider parsing and identity normalization. This
module owns the persisted projection semantics used by scheduled automation:

* replaying the same provider signal is a byte-stable no-op;
* demand is accumulated only from distinct signal ids, never workflow retries;
* material corrections to an existing signal may update country/context without
  creating a second observation;
* queue, candidate, and metrics files retain their exact prior bytes when their
  semantic content has not changed.

All outputs remain noncanonical. Existing source discovery and admission controls
remain authoritative.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from tools.openva.source_verification import ROOT, display_path
from tools.openva.vendor_breadth_mesh import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    directory_signals,
    entity_country,
    entity_key,
    load_json,
    normalize_country,
    normalize_domain,
    normalize_name,
    now_iso,
    observation_projection,
    parse_directory_spec,
    queue_and_candidate_report,
    read_rows,
    relationship_report_signals,
    resolver_demand_signals,
)


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _observed_at(signal: dict[str, Any]) -> str:
    return str(signal.get("observed_at") or now_iso())


def _entity_from_signal(signal: dict[str, Any]) -> dict[str, Any]:
    observed_at = _observed_at(signal)
    country = normalize_country(signal.get("country_observed"))
    return {
        "entity_key": entity_key(signal),
        "display_name": normalize_name(signal.get("display_name_observed")),
        "domain": normalize_domain(signal.get("domain_observed")),
        "countries": [country] if country else [],
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
        "observations": [],
        "not_advice": True,
    }


def _material_observation_fields(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        key: observation.get(key)
        for key in (
            "provider",
            "provider_record_id",
            "source_kind",
            "source_url",
            "demand_count",
            "country_observed",
            "relationship_context",
        )
    }


def _upsert_signal(entity: dict[str, Any], signal: dict[str, Any]) -> bool:
    """Return True only when the persisted entity meaningfully changes."""

    observation = observation_projection(signal)
    signal_id = str(observation.get("signal_id") or "")
    if not signal_id:
        return False
    observations = entity.setdefault("observations", [])
    prior = next(
        (
            row
            for row in observations
            if isinstance(row, dict) and str(row.get("signal_id") or "") == signal_id
        ),
        None,
    )
    changed = False
    if prior is None:
        observation["observation_count"] = 1
        observation["last_seen_at"] = observation["observed_at"]
        observations.append(observation)
        changed = True
    else:
        # A workflow retry or repeated directory crawl must not inflate demand or
        # observation counts. Only material corrections are applied in place.
        for key, value in _material_observation_fields(observation).items():
            if value in (None, "", []):
                continue
            if prior.get(key) != value:
                prior[key] = value
                changed = True
        if changed:
            prior["last_seen_at"] = max(
                str(prior.get("last_seen_at") or prior.get("observed_at") or ""),
                str(observation.get("observed_at") or ""),
            )

    country = normalize_country(signal.get("country_observed"))
    countries = entity.setdefault("countries", [])
    if country and country not in countries:
        countries.append(country)
        countries.sort()
        changed = True
    domain = normalize_domain(signal.get("domain_observed"))
    if domain and not entity.get("domain"):
        entity["domain"] = domain
        changed = True
    name = normalize_name(signal.get("display_name_observed"))
    if name and (not entity.get("display_name") or len(name) > len(str(entity.get("display_name") or ""))):
        entity["display_name"] = name
        changed = True
    if changed:
        entity["last_seen_at"] = max(str(entity.get("last_seen_at") or ""), _observed_at(signal))
    return changed


def _finalize_entity(entity: dict[str, Any]) -> dict[str, Any]:
    row = _clone(entity)
    row["countries"] = sorted({value for value in row.get("countries", []) or [] if value})
    row["observations"] = sorted(
        [value for value in row.get("observations", []) or [] if isinstance(value, dict)],
        key=lambda value: (str(value.get("provider") or ""), str(value.get("signal_id") or "")),
    )
    providers = sorted(
        {str(value.get("provider") or "") for value in row["observations"] if value.get("provider")}
    )
    row["provider_count"] = len(providers)
    row["providers"] = providers
    row["signal_count"] = len(row["observations"])
    # Distinct signal ids are observations. Duplicate workflow processing does not
    # create another observation and therefore cannot inflate these counters.
    row["observation_count"] = len(row["observations"])
    row["demand_count"] = sum(
        max(1, int(value.get("demand_count") or 1)) for value in row["observations"]
    )
    return row


def merge_ledger_idempotent(
    existing: dict[str, Any] | None,
    signals: Iterable[dict[str, Any]],
    *,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    entities: dict[str, dict[str, Any]] = {}
    if isinstance(existing, dict):
        for value in existing.get("entities", []) or []:
            if isinstance(value, dict) and value.get("entity_key"):
                entities[str(value["entity_key"])] = _clone(value)

    changed = existing is None
    for signal in signals:
        if not isinstance(signal, dict) or signal.get("not_advice") is not True:
            continue
        key = entity_key(signal)
        entity = entities.get(key)
        if entity is None:
            entity = _entity_from_signal(signal)
            entities[key] = entity
            changed = True
        if _upsert_signal(entity, signal):
            changed = True

    rows = [_finalize_entity(entities[key]) for key in sorted(entities)]
    timestamp = (
        generated_at
        or (now_iso() if changed else str((existing or {}).get("generated_at") or now_iso()))
    )
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp,
        "report_type": "vendor_breadth_signal_ledger",
        "policy_version": POLICY_VERSION,
        "summary": {
            "entity_count": len(rows),
            "signal_count": sum(int(row["signal_count"]) for row in rows),
            "observation_count": sum(int(row["observation_count"]) for row in rows),
            "provider_count": len(
                {provider for row in rows for provider in row.get("providers", [])}
            ),
            "catalog_vendor_count_cap": None,
        },
        "entities": rows,
        "posture": {
            "append_safe": True,
            "replay_idempotent": True,
            "signals_are_catalog_facts": False,
            "canonical_mutation_performed": False,
            "personal_identifiers_retained": False,
            "non_advisory": True,
        },
    }
    return ledger, changed


def _without_generated_at(value: dict[str, Any]) -> dict[str, Any]:
    copy = _clone(value)
    copy.pop("generated_at", None)
    return copy


def stabilize_projection(
    new: dict[str, Any],
    existing: dict[str, Any] | None,
    *,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    if isinstance(existing, dict) and _without_generated_at(new) == _without_generated_at(existing):
        return _clone(existing), False
    output = _clone(new)
    output["generated_at"] = generated_at or now_iso()
    return output, True


def cumulative_metrics(ledger: dict[str, Any], queue: dict[str, Any]) -> dict[str, Any]:
    entities = [value for value in ledger.get("entities", []) or [] if isinstance(value, dict)]
    queue_items = [value for value in queue.get("items", []) or [] if isinstance(value, dict)]
    provider_entity_counts: Counter[str] = Counter()
    provider_signal_counts: Counter[str] = Counter()
    source_kind_counts: Counter[str] = Counter()
    for entity in entities:
        for provider in entity.get("providers", []) or []:
            provider_entity_counts[str(provider)] += 1
        for observation in entity.get("observations", []) or []:
            if not isinstance(observation, dict):
                continue
            provider_signal_counts[str(observation.get("provider") or "unknown")] += 1
            source_kind_counts[str(observation.get("source_kind") or "unknown")] += 1
    state_counts = Counter(str(value.get("state") or "unknown") for value in queue_items)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": str(ledger.get("generated_at") or now_iso()),
        "report_type": "vendor_breadth_provider_metrics",
        "summary": {
            "entity_count": len(entities),
            "signal_count": int((ledger.get("summary") or {}).get("signal_count") or 0),
            "observation_count": int(
                (ledger.get("summary") or {}).get("observation_count") or 0
            ),
            "provider_count": int((ledger.get("summary") or {}).get("provider_count") or 0),
            "provider_entity_counts": dict(sorted(provider_entity_counts.items())),
            "provider_signal_counts": dict(sorted(provider_signal_counts.items())),
            "source_kind_counts": dict(sorted(source_kind_counts.items())),
            "queue_state_counts": dict(sorted(state_counts.items())),
            "ready_for_source_discovery_count": int(
                (queue.get("summary") or {}).get("ready_for_source_discovery_count") or 0
            ),
            "catalog_vendor_count_cap": None,
        },
        "posture": {
            "cumulative": True,
            "replay_idempotent": True,
            "non_advisory": True,
        },
    }


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return load_json(path)


def collect_signals(
    *,
    resolver_events: Path | None = None,
    directory_feeds: Iterable[str] = (),
    relationship_reports: Iterable[Path] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if resolver_events:
        rows, rejected = resolver_demand_signals(read_rows(resolver_events))
        signals.extend(rows)
        skipped.extend(rejected)
    for specification in directory_feeds:
        provider, source_url, path = parse_directory_spec(specification)
        rows, rejected = directory_signals(
            read_rows(path),
            provider=provider,
            provider_source_url=source_url,
        )
        signals.extend(rows)
        skipped.extend(rejected)
    for path in relationship_reports:
        signals.extend(relationship_report_signals(load_json(path)))
    return signals, skipped


def build_replenishment(
    *,
    signals: Iterable[dict[str, Any]],
    existing_ledger: dict[str, Any] | None,
    existing_queue: dict[str, Any] | None,
    existing_candidates: dict[str, Any] | None,
    existing_metrics: dict[str, Any] | None,
    root: Path = ROOT,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, bool]]:
    timestamp = generated_at or now_iso()
    ledger, ledger_changed = merge_ledger_idempotent(
        existing_ledger,
        signals,
        generated_at=timestamp,
    )
    queue_raw, candidates_raw = queue_and_candidate_report(ledger, root=root)
    queue, queue_changed = stabilize_projection(
        queue_raw,
        existing_queue,
        generated_at=timestamp,
    )
    candidates, candidates_changed = stabilize_projection(
        candidates_raw,
        existing_candidates,
        generated_at=timestamp,
    )
    metrics_raw = cumulative_metrics(ledger, queue)
    metrics, metrics_changed = stabilize_projection(
        metrics_raw,
        existing_metrics,
        generated_at=timestamp,
    )
    return ledger, queue, candidates, metrics, {
        "ledger": ledger_changed,
        "queue": queue_changed,
        "candidates": candidates_changed,
        "metrics": metrics_changed,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-vendor-breadth-replenishment")
    parser.add_argument("build", nargs="?")
    parser.add_argument("--resolver-events", type=Path)
    parser.add_argument("--directory-feed", action="append", default=[])
    parser.add_argument("--relationship-report", action="append", type=Path, default=[])
    parser.add_argument("--existing-ledger", type=Path)
    parser.add_argument("--existing-queue", type=Path)
    parser.add_argument("--existing-candidates", type=Path)
    parser.add_argument("--existing-metrics", type=Path)
    parser.add_argument("--ledger-output", type=Path, required=True)
    parser.add_argument("--queue-output", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--metrics-output", type=Path, required=True)
    parser.add_argument("--run-report-output", type=Path)
    parser.add_argument("--generated-at")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    signals, skipped = collect_signals(
        resolver_events=args.resolver_events,
        directory_feeds=args.directory_feed,
        relationship_reports=args.relationship_report,
    )
    ledger, queue, candidates, metrics, changes = build_replenishment(
        signals=signals,
        existing_ledger=_load_optional(args.existing_ledger),
        existing_queue=_load_optional(args.existing_queue),
        existing_candidates=_load_optional(args.existing_candidates),
        existing_metrics=_load_optional(args.existing_metrics),
        root=args.root,
        generated_at=args.generated_at,
    )
    for path, value in (
        (args.ledger_output, ledger),
        (args.queue_output, queue),
        (args.candidate_output, candidates),
        (args.metrics_output, metrics),
    ):
        write_json(path, value)
    if args.run_report_output:
        write_json(
            args.run_report_output,
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": args.generated_at or now_iso(),
                "report_type": "vendor_breadth_replenishment_run",
                "summary": {
                    "input_signal_count": len(signals),
                    "skipped_input_count": len(skipped),
                    "changed_outputs": sorted(key for key, changed in changes.items() if changed),
                    "unchanged_outputs": sorted(key for key, changed in changes.items() if not changed),
                    "catalog_vendor_count_cap": None,
                },
                "skipped": skipped,
                "posture": {
                    "canonical_mutation_performed": False,
                    "replay_idempotent": True,
                    "non_advisory": True,
                },
            },
        )
    print(
        json.dumps(
            {
                **ledger["summary"],
                **queue["summary"],
                "changed_outputs": sorted(key for key, changed in changes.items() if changed),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
