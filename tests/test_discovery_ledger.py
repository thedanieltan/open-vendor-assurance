import copy

import pytest

from tools.openva.discovery_ledger import append_events


def event(event_id="a" * 32):
    return {
        "schema_version": "0.1.0",
        "discovery_event_id": event_id,
        "candidate_id": "example-dpa-123",
        "vendor_id": "example",
        "source_type": "dpa",
        "origin": "source_discovery",
        "candidate_url": "https://example.test/dpa",
        "evidence_digest": "sha256:" + "b" * 64,
        "classification": "strong_same_authority_canonical_url",
        "reason_codes": ["strong_same_authority_canonical_url"],
        "retry_after": None,
        "supersedes": None,
        "discovered_at": "2026-06-14T00:00:00Z",
        "discovery_run_id": "run-1",
        "policy_version": "source_discovery_registry_0.2.0",
        "not_advice": True,
    }


def test_discovery_ledger_rejects_duplicate_event_id(tmp_path):
    ledger = tmp_path / "maintenance/discovery-events"
    append_events([event()], ledger)

    with pytest.raises(ValueError, match="duplicate_existing_event_id"):
        append_events([event()], ledger)


def test_discovery_ledger_rejects_invalid_event(tmp_path):
    invalid = copy.deepcopy(event())
    invalid["evidence_digest"] = "md5:bad"

    with pytest.raises(ValueError, match="evidence_digest_invalid"):
        append_events([invalid], tmp_path / "maintenance/discovery-events")


def test_discovery_ledger_enforces_max_append_count(tmp_path):
    with pytest.raises(ValueError, match="too_many_discovery_events"):
        append_events([event("a" * 32), event("b" * 32)], tmp_path / "events", max_append_count=1)
