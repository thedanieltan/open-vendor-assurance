"""WP38a source quarantine: eligibility, decision record, status-only apply."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import yaml

from tools.openva import machine_decisions as md
from tools.openva import source_quarantine as sq
from tools.openva.indexes import ROOT

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
DECISION_SCHEMA = json.loads((ROOT / "schemas" / "openva" / "machine-decision-record.schema.json").read_text(encoding="utf-8"))
SOURCE_SCHEMA = json.loads((ROOT / "schemas" / "openva" / "source-reference.schema.json").read_text(encoding="utf-8"))
THRESHOLDS = sq.load_thresholds()


def failed_event(source_id="acme-dpa", http=404, health="unreachable", observed_at="2026-06-10T00:00:00Z") -> dict:
    return {
        "source_id": source_id,
        "vendor_id": "acme",
        "event_type": "first_observed",
        "change_class": "none",
        "observed_at": observed_at,
        "http_status": http,
        "source_health_status": health,
    }


def source(**overrides) -> dict:
    record = {
        "schema_version": "0.1.0",
        "source_id": "acme-dpa",
        "vendor_id": "acme",
        "source_type": "dpa",
        "title_native": "Acme DPA",
        "source_url": "https://acme.com/dpa",
        "source_language": "en",
        "source_authority_class": "vendor_published",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "review_state": "validated",
        "provenance": {"publisher": "vendor", "collected_at": "2026-06-01T00:00:00Z", "observer": "agent", "confidence": "medium"},
        "not_advice": True,
    }
    record.update(overrides)
    return record


def three_failures(source_id="acme-dpa", http=404):
    return [
        failed_event(source_id, http, observed_at="2026-06-08T00:00:00Z"),
        failed_event(source_id, http, observed_at="2026-06-09T00:00:00Z"),
        failed_event(source_id, http, observed_at="2026-06-10T00:00:00Z"),
    ]


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
def test_eligible_after_repeated_404():
    result = sq.quarantine_eligibility(source(), three_failures(), THRESHOLDS)
    assert result.eligible, result.reasons
    assert result.quarantine_reason == "persistent_not_found"


def test_eligible_gone_reason_on_410():
    result = sq.quarantine_eligibility(source(), three_failures(http=410), THRESHOLDS)
    assert result.eligible
    assert result.quarantine_reason == "persistent_gone"


def test_ineligible_with_too_few_failures():
    result = sq.quarantine_eligibility(source(), three_failures()[:2], THRESHOLDS)
    assert not result.eligible
    assert any("insufficient_failed_observations" in r for r in result.reasons)


def test_ineligible_when_recovered():
    events = three_failures()[:2] + [failed_event(http=200, health="reachable", observed_at="2026-06-11T00:00:00Z")]
    result = sq.quarantine_eligibility(source(), events, THRESHOLDS)
    assert not result.eligible
    assert any("latest_observation_not_failed" in r for r in result.reasons)


def test_gated_source_is_record_only_never_quarantined():
    events = three_failures()[:2] + [failed_event(http=403, health="gated", observed_at="2026-06-11T00:00:00Z")]
    result = sq.quarantine_eligibility(source(), events, THRESHOLDS)
    assert not result.eligible
    assert any("record_only_health:gated" in r for r in result.reasons)


def test_bot_protected_source_is_record_only():
    events = three_failures()[:2] + [failed_event(http=403, health="bot_protected", observed_at="2026-06-11T00:00:00Z")]
    result = sq.quarantine_eligibility(source(), events, THRESHOLDS)
    assert not result.eligible
    assert any("record_only_health:bot_protected" in r for r in result.reasons)


def test_already_quarantined_is_ineligible():
    result = sq.quarantine_eligibility(source(review_state="quarantined"), three_failures(), THRESHOLDS)
    assert not result.eligible
    assert any("already_quarantined" in r for r in result.reasons)


# --------------------------------------------------------------------------- #
# Decision record + status-only transition
# --------------------------------------------------------------------------- #
def test_build_quarantine_decision_is_schema_valid_and_separation_clean():
    result = sq.quarantine_eligibility(source(), three_failures(), THRESHOLDS)
    decision = sq.build_quarantine_decision(source(), result, thresholds=THRESHOLDS, now=NOW)
    jsonschema.validate(decision, DECISION_SCHEMA)
    assert decision["decision_type"] == "quarantine"
    assert decision["decision"] == "quarantine"
    assert decision["subject_type"] == "source"
    assert decision["deciding_bot"] != decision["discovery_bot"]
    assert decision["reversal"]["method"] == "revert_quarantine"
    assert md.separation_of_duty_violation(decision) is None


def test_status_only_transition_keeps_other_fields_and_validates():
    result = sq.quarantine_eligibility(source(), three_failures(), THRESHOLDS)
    decision = sq.build_quarantine_decision(source(), result, thresholds=THRESHOLDS, now=NOW)
    updated = sq.apply_status_only_quarantine(source(), decision, "persistent_not_found", NOW)
    changed = {k for k in set(source()) | set(updated) if source().get(k) != updated.get(k)}
    assert changed <= sq.STATUS_ONLY_FIELDS
    assert updated["review_state"] == "quarantined"
    assert updated["quarantine"]["reversal"]["method"] == "revert_quarantine"
    assert updated["source_url"] == "https://acme.com/dpa"
    jsonschema.validate(updated, SOURCE_SCHEMA)  # quarantined source is schema-valid


# --------------------------------------------------------------------------- #
# Full prepare -> apply on a temp catalog
# --------------------------------------------------------------------------- #
def _build_temp_catalog(tmp_path: Path):
    spath = tmp_path / "data/vendors/acme/sources/acme-dpa.yaml"
    spath.parent.mkdir(parents=True, exist_ok=True)
    spath.write_text(yaml.safe_dump(source(), sort_keys=False), encoding="utf-8")
    ledger_dir = tmp_path / "maintenance/source-observations/events"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "2026-06.ndjson").write_text("\n".join(json.dumps(e) for e in three_failures()) + "\n", encoding="utf-8")
    decisions_dir = tmp_path / "maintenance/machine-decisions"
    decisions_dir.mkdir(parents=True)
    return spath, ledger_dir, decisions_dir


def test_prepare_and_apply_quarantine_status_only(tmp_path):
    spath, ledger_dir, decisions_dir = _build_temp_catalog(tmp_path)
    prepared = sq.prepare_quarantine("acme-dpa", root=tmp_path, now=NOW, ledger_dir=ledger_dir)
    assert prepared.quarantinable, prepared.eligibility.reasons

    report = sq.apply_quarantine(prepared, root=tmp_path, decisions_dir=decisions_dir, now=NOW, rebuild=False)
    assert report["source_id"] == "acme-dpa"
    assert report["quarantine_reason"] == "persistent_not_found"

    updated = yaml.safe_load(spath.read_text(encoding="utf-8"))
    assert updated["review_state"] == "quarantined"
    assert updated["quarantine"]["decision_id"] == "acme-dpa-quarantine"
    assert updated["source_url"] == "https://acme.com/dpa"
    jsonschema.validate(updated, SOURCE_SCHEMA)

    assert md.validate_committed(decisions_dir) == []
    records = [r for r in md.load_decisions(decisions_dir) if r["decision"] == "quarantine"]
    assert len(records) == 1


def test_apply_refuses_already_quarantined(tmp_path):
    spath, ledger_dir, decisions_dir = _build_temp_catalog(tmp_path)
    prepared = sq.prepare_quarantine("acme-dpa", root=tmp_path, now=NOW, ledger_dir=ledger_dir)
    # Flip the on-disk source to quarantined before applying.
    rec = yaml.safe_load(spath.read_text(encoding="utf-8"))
    rec["review_state"] = "quarantined"
    spath.write_text(yaml.safe_dump(rec, sort_keys=False), encoding="utf-8")
    try:
        sq.apply_quarantine(prepared, root=tmp_path, decisions_dir=decisions_dir, now=NOW, rebuild=False)
        assert False, "apply should refuse an already-quarantined source"
    except ValueError as exc:
        assert "already quarantined" in str(exc)


def test_apply_refuses_duplicate_quarantine_decision_before_source_mutation(tmp_path):
    spath, ledger_dir, decisions_dir = _build_temp_catalog(tmp_path)
    prepared = sq.prepare_quarantine("acme-dpa", root=tmp_path, now=NOW, ledger_dir=ledger_dir)
    assert prepared.decision is not None
    md.append_decisions([prepared.decision], decisions_dir)
    before = spath.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate decision_id"):
        sq.apply_quarantine(prepared, root=tmp_path, decisions_dir=decisions_dir, now=NOW, rebuild=False)

    assert spath.read_text(encoding="utf-8") == before
