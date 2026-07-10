from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.vendor_breadth_mesh import signal_record
from tools.openva.vendor_breadth_replenishment import (
    build_replenishment,
    merge_ledger_idempotent,
)


def signal(
    record_id: str,
    *,
    country: str = "SG",
    demand_count: int = 1,
    context: str | None = None,
):
    value = signal_record(
        name="Acme Cloud",
        domain="acme.example",
        country=country,
        provider="resolver_demand",
        provider_record_id=record_id,
        source_url=None,
        observed_at="2026-07-10T10:00:00Z",
        demand_count=demand_count,
        relationship_context=context,
        source_kind="resolver_demand",
    )
    assert value is not None
    return value


def test_replaying_same_signal_is_byte_stable_and_does_not_inflate_demand() -> None:
    first, first_changed = merge_ledger_idempotent(
        None,
        [signal("evt-1", demand_count=3)],
        generated_at="2026-07-10T10:00:00Z",
    )
    replay, replay_changed = merge_ledger_idempotent(
        first,
        [signal("evt-1", demand_count=3)],
        generated_at="2026-07-11T10:00:00Z",
    )

    assert first_changed is True
    assert replay_changed is False
    assert replay == first
    assert replay["entities"][0]["signal_count"] == 1
    assert replay["entities"][0]["observation_count"] == 1
    assert replay["entities"][0]["demand_count"] == 3
    assert replay["generated_at"] == "2026-07-10T10:00:00Z"


def test_distinct_resolver_event_accumulates_real_demand() -> None:
    first, _ = merge_ledger_idempotent(
        None,
        [signal("evt-1", demand_count=2)],
        generated_at="2026-07-10T10:00:00Z",
    )
    second, changed = merge_ledger_idempotent(
        first,
        [signal("evt-2", demand_count=4)],
        generated_at="2026-07-11T10:00:00Z",
    )

    entity = second["entities"][0]
    assert changed is True
    assert entity["signal_count"] == 2
    assert entity["observation_count"] == 2
    assert entity["demand_count"] == 6
    assert second["generated_at"] == "2026-07-11T10:00:00Z"


def test_material_correction_updates_existing_signal_without_duplication() -> None:
    first, _ = merge_ledger_idempotent(
        None,
        [signal("evt-1", country="SG")],
        generated_at="2026-07-10T10:00:00Z",
    )
    corrected_signal = signal("evt-1", country="US", context="Corrected headquarters evidence")
    corrected_signal["observed_at"] = "2026-07-11T10:00:00Z"

    second, changed = merge_ledger_idempotent(
        first,
        [corrected_signal],
        generated_at="2026-07-11T10:00:00Z",
    )

    entity = second["entities"][0]
    observation = entity["observations"][0]
    assert changed is True
    assert entity["signal_count"] == 1
    assert entity["observation_count"] == 1
    assert entity["countries"] == ["SG", "US"]
    assert observation["country_observed"] == "US"
    assert observation["relationship_context"] == "Corrected headquarters evidence"


def test_all_persisted_projections_are_exact_noops_on_replay(tmp_path: Path) -> None:
    first = build_replenishment(
        signals=[signal("evt-1")],
        existing_ledger=None,
        existing_queue=None,
        existing_candidates=None,
        existing_metrics=None,
        root=tmp_path,
        generated_at="2026-07-10T10:00:00Z",
    )
    ledger, queue, candidates, metrics, first_changes = first
    replay = build_replenishment(
        signals=[signal("evt-1")],
        existing_ledger=ledger,
        existing_queue=queue,
        existing_candidates=candidates,
        existing_metrics=metrics,
        root=tmp_path,
        generated_at="2026-07-11T10:00:00Z",
    )
    replay_ledger, replay_queue, replay_candidates, replay_metrics, replay_changes = replay

    assert first_changes == {"ledger": True, "queue": True, "candidates": True, "metrics": True}
    assert replay_changes == {"ledger": False, "queue": False, "candidates": False, "metrics": False}
    assert replay_ledger == ledger
    assert replay_queue == queue
    assert replay_candidates == candidates
    assert replay_metrics == metrics


def test_catalog_change_reclassifies_queue_even_when_ledger_is_unchanged(tmp_path: Path) -> None:
    ledger, queue, candidates, metrics, _ = build_replenishment(
        signals=[signal("evt-1")],
        existing_ledger=None,
        existing_queue=None,
        existing_candidates=None,
        existing_metrics=None,
        root=tmp_path,
        generated_at="2026-07-10T10:00:00Z",
    )
    assert queue["items"][0]["state"] == "ready_for_source_discovery"
    assert len(candidates["vendor_candidates"]) == 1

    vendor_path = tmp_path / "data" / "vendors" / "acme" / "vendor.yaml"
    vendor_path.parent.mkdir(parents=True, exist_ok=True)
    vendor_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": "acme",
                "display_name": "Acme Cloud",
                "official_domains": ["acme.example"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    replay_ledger, replay_queue, replay_candidates, replay_metrics, changes = build_replenishment(
        signals=[signal("evt-1")],
        existing_ledger=ledger,
        existing_queue=queue,
        existing_candidates=candidates,
        existing_metrics=metrics,
        root=tmp_path,
        generated_at="2026-07-11T10:00:00Z",
    )

    assert replay_ledger == ledger
    assert replay_queue["items"][0]["state"] == "already_catalogued"
    assert replay_candidates["vendor_candidates"] == []
    assert changes["ledger"] is False
    assert changes["queue"] is True
    assert changes["candidates"] is True
    assert changes["metrics"] is True
    assert replay_metrics["summary"]["queue_state_counts"] == {"already_catalogued": 1}


def test_metrics_are_cumulative_and_catalog_uncapped(tmp_path: Path) -> None:
    _, queue, _, metrics, _ = build_replenishment(
        signals=[signal("evt-1")],
        existing_ledger=None,
        existing_queue=None,
        existing_candidates=None,
        existing_metrics=None,
        root=tmp_path,
        generated_at="2026-07-10T10:00:00Z",
    )

    assert metrics["summary"]["entity_count"] == 1
    assert metrics["summary"]["signal_count"] == 1
    assert metrics["summary"]["provider_signal_counts"] == {"resolver_demand": 1}
    assert metrics["summary"]["queue_state_counts"] == {"ready_for_source_discovery": 1}
    assert metrics["summary"]["catalog_vendor_count_cap"] is None
    assert queue["summary"]["catalog_vendor_count_cap"] is None
