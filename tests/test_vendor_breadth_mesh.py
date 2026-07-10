from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva.vendor_breadth_mesh import (
    directory_signals,
    infer_country,
    merge_ledger,
    normalize_domain,
    queue_and_candidate_report,
    relationship_report_signals,
    resolver_demand_signals,
    signal_record,
)


def write_vendor(root: Path, vendor_id: str, domain: str, name: str | None = None) -> None:
    path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "display_name": name or vendor_id.title(),
                "official_domains": [domain],
                "previous_domains": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_normalizes_domains_and_rejects_non_vendor_hosts() -> None:
    assert normalize_domain("https://www.Example.COM/legal") == "example.com"
    assert normalize_domain("127.0.0.1") is None
    assert normalize_domain("https://github.com/example") is None
    assert normalize_domain("invalid") is None


def test_country_inference_recognizes_relationship_context() -> None:
    assert infer_country("Infrastructure provider located in Singapore") == "SG"
    assert infer_country("Hosting services — Frankfurt, Germany") == "DE"
    assert infer_country("No location stated") is None


def test_resolver_demand_only_emits_identity_gaps_without_personal_fields() -> None:
    events = [
        {
            "event_id": "evt-1",
            "observed_at": "2026-07-10T10:00:00Z",
            "query": {
                "vendor_name": "Acme Cloud",
                "domain": "acme.example",
                "country": "Singapore",
                "requester_email": "should-not-survive@example.com",
            },
            "resolution": {
                "resolution_status": "not_found",
                "vendor": {"vendor_id": None, "display_name": None, "official_domain": None},
            },
        },
        {
            "event_id": "evt-2",
            "query": {"vendor_name": "Known Vendor"},
            "resolution": {
                "resolution_status": "catalog_current",
                "vendor": {"vendor_id": "known", "display_name": "Known Vendor", "official_domain": "known.example"},
            },
        },
    ]

    signals, skipped = resolver_demand_signals(events)

    assert len(signals) == 1
    assert signals[0]["display_name_observed"] == "Acme Cloud"
    assert signals[0]["domain_observed"] == "acme.example"
    assert signals[0]["country_observed"] == "SG"
    assert signals[0]["source_url"] is None
    assert "requester_email" not in json.dumps(signals)
    assert skipped == [{"index": 1, "reason": "resolver_match_already_identified"}]


def test_public_directory_provider_accepts_json_like_rows() -> None:
    rows = [
        {
            "id": "acme",
            "name": "Acme Cloud",
            "website": "https://acme.example",
            "country": "United States",
            "listing_url": "https://directory.example/vendors/acme",
        },
        {
            "id": "generic",
            "name": "Learn more",
            "website": "https://ignored.example",
        },
    ]

    signals, skipped = directory_signals(
        rows,
        provider="public_ecosystem_directory",
        provider_source_url="https://directory.example/vendors",
        observed_at="2026-07-10T10:00:00Z",
    )

    assert len(signals) == 1
    assert signals[0]["source_kind"] == "public_directory"
    assert signals[0]["country_observed"] == "US"
    assert signals[0]["source_url"] == "https://directory.example/vendors/acme"
    assert skipped == [{"index": 1, "reason": "invalid_directory_identity"}]


def test_relationship_aggregate_report_is_rehydrated_as_provider_signals() -> None:
    report = {
        "generated_at": "2026-07-10T10:00:00Z",
        "vendor_candidates": [
            {
                "candidate_vendor_id": "cloudco",
                "display_name_candidate": "CloudCo",
                "official_domain_candidate": "cloudco.example",
                "headquarters_country_candidate": "Ireland",
                "providers": ["subprocessor_graph", "trust_center_graph"],
                "source_urls": [
                    "https://customer.example/subprocessors",
                    "https://customer.example/trust",
                ],
                "signal_count": 2,
                "demand_count": 3,
            }
        ],
    }

    signals = relationship_report_signals(report)

    assert len(signals) == 2
    assert {signal["provider"] for signal in signals} == {"subprocessor_graph", "trust_center_graph"}
    assert {signal["country_observed"] for signal in signals} == {"IE"}
    assert all(signal["domain_observed"] == "cloudco.example" for signal in signals)


def test_ledger_deduplicates_signal_retries_and_accumulates_demand() -> None:
    first = signal_record(
        name="Acme Cloud",
        domain="acme.example",
        country="SG",
        provider="resolver_demand",
        provider_record_id="evt-1",
        source_url=None,
        observed_at="2026-07-10T10:00:00Z",
        demand_count=2,
        source_kind="resolver_demand",
    )
    assert first is not None

    ledger = merge_ledger(None, [first])
    ledger = merge_ledger(ledger, [first])

    entity = ledger["entities"][0]
    assert ledger["summary"]["entity_count"] == 1
    assert entity["signal_count"] == 1
    assert entity["observation_count"] == 2
    assert entity["demand_count"] == 4
    assert ledger["summary"]["catalog_vendor_count_cap"] is None
    assert ledger["posture"]["personal_identifiers_retained"] is False


def test_queue_retains_incomplete_identity_and_only_projects_ready_candidates(tmp_path: Path) -> None:
    ready = signal_record(
        name="Ready Cloud",
        domain="ready.example",
        country="Singapore",
        provider="directory",
        provider_record_id="ready",
        source_url="https://directory.example/ready",
        observed_at="2026-07-10T10:00:00Z",
        source_kind="public_directory",
    )
    no_country = signal_record(
        name="Countryless Cloud",
        domain="countryless.example",
        country=None,
        provider="relationship_graph",
        provider_record_id="countryless",
        source_url="https://customer.example/subprocessors",
        observed_at="2026-07-10T10:00:00Z",
        source_kind="relationship_graph",
    )
    no_domain = signal_record(
        name="Domainless Platform",
        domain=None,
        country="US",
        provider="resolver_demand",
        provider_record_id="domainless",
        source_url=None,
        observed_at="2026-07-10T10:00:00Z",
        source_kind="resolver_demand",
    )
    assert ready and no_country and no_domain

    ledger = merge_ledger(None, [ready, no_country, no_domain])
    queue, candidates = queue_and_candidate_report(ledger, root=tmp_path)

    states = {row["display_name_candidate"]: row["state"] for row in queue["items"]}
    assert states == {
        "Ready Cloud": "ready_for_source_discovery",
        "Countryless Cloud": "needs_country",
        "Domainless Platform": "needs_domain",
    }
    assert [row["display_name_candidate"] for row in candidates["vendor_candidates"]] == ["Ready Cloud"]
    assert candidates["report_type"] == "vendor_candidate_discovery_report"
    assert candidates["summary"]["catalog_vendor_count_cap"] is None


def test_queue_detects_current_catalog_collisions(tmp_path: Path) -> None:
    write_vendor(tmp_path, "existing", "existing.example", "Existing Vendor")
    signal = signal_record(
        name="Existing Vendor",
        domain="existing.example",
        country="SG",
        provider="directory",
        provider_record_id="existing",
        source_url="https://directory.example/existing",
        observed_at="2026-07-10T10:00:00Z",
        source_kind="public_directory",
    )
    assert signal

    queue, candidates = queue_and_candidate_report(merge_ledger(None, [signal]), root=tmp_path)

    assert queue["items"][0]["state"] == "already_catalogued"
    assert "catalog_identity_collision" in queue["items"][0]["reason_codes"]
    assert candidates["vendor_candidates"] == []


def test_country_conflicts_remain_in_resolution_queue(tmp_path: Path) -> None:
    sg = signal_record(
        name="Conflicted Cloud",
        domain="conflict.example",
        country="SG",
        provider="directory-a",
        provider_record_id="a",
        source_url="https://a.example/conflict",
        observed_at="2026-07-10T10:00:00Z",
        source_kind="public_directory",
    )
    us = signal_record(
        name="Conflicted Cloud",
        domain="conflict.example",
        country="US",
        provider="directory-b",
        provider_record_id="b",
        source_url="https://b.example/conflict",
        observed_at="2026-07-10T10:00:00Z",
        source_kind="public_directory",
    )
    assert sg and us

    queue, candidates = queue_and_candidate_report(merge_ledger(None, [sg, us]), root=tmp_path)

    assert queue["items"][0]["state"] == "needs_country"
    assert queue["items"][0]["reason_codes"] == ["country_conflict"]
    assert candidates["vendor_candidates"] == []


def test_breadth_projection_has_no_vendor_ceiling(tmp_path: Path) -> None:
    signals = []
    for index in range(1_501):
        signal = signal_record(
            name=f"Vendor {index}",
            domain=f"vendor-{index}.example",
            country="SG",
            provider="directory",
            provider_record_id=str(index),
            source_url=f"https://directory.example/vendors/{index}",
            observed_at="2026-07-10T10:00:00Z",
            source_kind="public_directory",
        )
        assert signal
        signals.append(signal)

    queue, candidates = queue_and_candidate_report(merge_ledger(None, signals), root=tmp_path)

    assert queue["summary"]["queue_count"] == 1_501
    assert queue["summary"]["ready_for_source_discovery_count"] == 1_501
    assert candidates["summary"]["candidate_vendor_count"] == 1_501
    assert candidates["summary"]["catalog_vendor_count_cap"] is None
