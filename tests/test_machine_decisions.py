"""WP36a machine-decision store + machine_provisional vendor schema tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from tools.openva import machine_decisions as md
from tools.openva.indexes import ROOT

VENDOR_SCHEMA = json.loads((ROOT / "schemas" / "openva" / "vendor-public-profile.schema.json").read_text(encoding="utf-8"))


def record(decision_id: str = "dec-okta-1", *, deciding: str = "materialization-gate", discovery: str = "queue-bridge") -> dict:
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "decision_type": "vendor_materialization",
        "subject_type": "vendor",
        "subject_id": "okta",
        "decision": "materialize_provisional",
        "deciding_bot": deciding,
        "discovery_bot": discovery,
        "supporting_bots": [],
        "evidence": {"official_domain": "okta.com"},
        "counter_evidence": [],
        "thresholds": {"required_score": 1.0, "actual_score": 1.0, "results": {"no_collision": True}},
        "source_queue_reference": "coverage-growth:missing_vendor:okta",
        "candidate_digest": "sha256:" + "a" * 64,
        "created_at": "2026-06-13T10:00:00Z",
        "not_before": "2026-06-15T10:00:00Z",
        "reversal": {"method": "remove", "reference": "revert the materialization PR", "reversal_decision_id": None},
        "not_advice": True,
    }


def test_append_and_validate_clean(tmp_path):
    touched = md.append_decisions([record()], tmp_path)
    assert touched and touched[0].name == "2026-06.ndjson"
    assert md.validate_committed(tmp_path) == []
    rows = md.load_decisions(tmp_path)
    assert [r["decision_id"] for r in rows] == ["dec-okta-1"]


def test_append_is_append_only_across_calls(tmp_path):
    md.append_decisions([record("dec-1")], tmp_path)
    md.append_decisions([record("dec-2")], tmp_path)
    assert [r["decision_id"] for r in md.load_decisions(tmp_path)] == ["dec-1", "dec-2"]


def test_duplicate_decision_id_refused(tmp_path):
    md.append_decisions([record("dec-1")], tmp_path)
    with pytest.raises(ValueError, match="duplicate decision_id"):
        md.append_decisions([record("dec-1")], tmp_path)


def test_separation_of_duty_deciding_equals_discovery_refused(tmp_path):
    bad = record(deciding="same-bot", discovery="same-bot")
    with pytest.raises(ValueError, match="separation_of_duty"):
        md.append_decisions([bad], tmp_path)


def test_separation_of_duty_sole_supporting_bot_refused(tmp_path):
    bad = record()
    bad["supporting_bots"] = [bad["deciding_bot"]]
    with pytest.raises(ValueError, match="separation_of_duty"):
        md.append_decisions([bad], tmp_path)


def test_schema_invalid_record_refused(tmp_path):
    bad = record()
    del bad["not_advice"]
    with pytest.raises(ValueError, match="schema"):
        md.append_decisions([bad], tmp_path)


def test_validate_committed_flags_corrupt_committed_row(tmp_path):
    # A row written outside the guarded append path is still caught by validate.
    (tmp_path / "2026-06.ndjson").write_text(json.dumps({"decision_id": "x", "not_advice": True}) + "\n", encoding="utf-8")
    reasons = md.validate_committed(tmp_path)
    assert reasons


# --- machine_provisional vendor schema ---
def _valid_vendor(**overrides) -> dict:
    vendor = {
        "schema_version": "0.1.0",
        "vendor_id": "okta",
        "display_name": "Okta",
        "legal_name": "Okta, Inc.",
        "headquarters_country": "US",
        "official_domains": ["okta.com"],
        "source_policy": {
            "public_sources_only": True,
            "gated_materials_excluded": True,
            "raw_documents_mirrored_by_default": False,
        },
        "catalog_status": "active",
    }
    vendor.update(overrides)
    return vendor


def test_machine_provisional_is_a_valid_catalog_status():
    vendor = _valid_vendor(
        catalog_status="machine_provisional",
        machine_generated=True,
        machine_decision_id="dec-okta-1",
        reversal={"method": "remove", "reference": "revert PR", "reversal_decision_id": None},
    )
    jsonschema.validate(vendor, VENDOR_SCHEMA)  # must not raise


def test_existing_active_vendor_still_validates():
    jsonschema.validate(_valid_vendor(), VENDOR_SCHEMA)
