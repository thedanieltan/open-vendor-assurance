"""WP37 quorum promotion: eligibility, decision record, and status-only apply."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import yaml

from tools.openva import bot_quorum as q
from tools.openva import machine_decisions as md
from tools.openva import quorum_promotion as qp
from tools.openva.indexes import ROOT

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
OBSERVED_AT = "2026-06-12T00:00:00Z"
DECISION_SCHEMA = json.loads((ROOT / "schemas" / "openva" / "machine-decision-record.schema.json").read_text(encoding="utf-8"))
THRESHOLDS = qp.load_thresholds()


def healthy_event(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "vendor_id": "newco",
        "event_type": "first_observed",
        "change_class": "none",
        "observed_at": OBSERVED_AT,
        "source_health_status": "ok",
        "review_signal": {"required": False, "reason": "first_observation"},
    }


def clean_subject(**overrides) -> q.PromotionSubject:
    kwargs = dict(
        vendor={
            "vendor_id": "newco",
            "display_name": "NewCo",
            "catalog_status": "machine_provisional",
            "official_domains": ["newco.com"],
            "public_entrypoints": ["https://newco.com"],
            "reversal": {"method": "remove", "reference": "revert materialization", "reversal_decision_id": None},
        },
        sources=[
            {"source_id": "newco-privacy", "source_type": "privacy_notice", "source_url": "https://newco.com/privacy"},
            {"source_id": "newco-security", "source_type": "security_page", "source_url": "https://newco.com/security"},
        ],
        events=[healthy_event("newco-privacy"), healthy_event("newco-security")],
        materialization_decision={
            "decision_id": "newco-vendor-materialization",
            "decision": "materialize_provisional",
            "deciding_bot": "strict-growth-materializer",
            "discovery_bot": "catalog-growth-discovery",
        },
        other_vendor_domains={"other.com"},
        other_vendor_names={"other co"},
        match_index_items=[{"vendor_id": "other", "official_domains": ["other.com"], "display_name": "Other Co"}],
        now=NOW,
        thresholds=THRESHOLDS,
    )
    kwargs.update(overrides)
    return q.PromotionSubject(**kwargs)


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
def test_clean_subject_is_eligible():
    result = qp.promotion_eligibility(clean_subject())
    assert result.eligible, result.reasons


def test_too_young_is_ineligible():
    young = clean_subject(events=[
        {**healthy_event("newco-privacy"), "observed_at": "2026-06-19T00:00:00Z"},
        {**healthy_event("newco-security"), "observed_at": "2026-06-19T00:00:00Z"},
    ])
    result = qp.promotion_eligibility(young)
    assert not result.eligible
    assert any("stable_observation_age_too_low" in r for r in result.reasons)


def test_insufficient_observations_is_ineligible():
    result = qp.promotion_eligibility(clean_subject(events=[healthy_event("newco-privacy")]))
    assert not result.eligible
    assert any("insufficient_successful_observations" in r for r in result.reasons)


def test_open_challenge_is_ineligible():
    subject = clean_subject()
    subject.events[0]["change_class"] = "material_confirmed"
    result = qp.promotion_eligibility(subject)
    assert not result.eligible
    assert any("open_material_change" in r for r in result.reasons)


def test_insufficient_roles_is_ineligible():
    subject = clean_subject(
        sources=[
            {"source_id": "newco-privacy", "source_type": "privacy_notice", "source_url": "https://newco.com/privacy"},
            {"source_id": "newco-privacy2", "source_type": "privacy_notice", "source_url": "https://newco.com/privacy2"},
        ],
    )
    result = qp.promotion_eligibility(subject)
    assert not result.eligible
    assert any("insufficient_useful_source_roles" in r for r in result.reasons)


# --------------------------------------------------------------------------- #
# Decision record
# --------------------------------------------------------------------------- #
def test_build_promotion_decision_is_schema_valid_and_separation_clean():
    subject = clean_subject()
    result = q.run_quorum(subject, release_gate_decision="pass")
    assert result.promote
    decision = qp.build_promotion_decision(subject, result, now=NOW)
    jsonschema.validate(decision, DECISION_SCHEMA)
    assert decision["decision"] == "promote"
    assert decision["decision_type"] == "promotion"
    assert decision["deciding_bot"] != decision["discovery_bot"]
    assert decision["deciding_bot"] not in decision["supporting_bots"]
    assert len(decision["supporting_bots"]) >= 2
    assert decision["reversal"]["method"] == "revert_promotion"
    assert md.separation_of_duty_violation(decision) is None


# --------------------------------------------------------------------------- #
# Status-only transition
# --------------------------------------------------------------------------- #
def test_status_only_transition_changes_only_lifecycle_fields():
    vendor = {
        "vendor_id": "newco",
        "display_name": "NewCo",
        "official_domains": ["newco.com"],
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": "newco-vendor-materialization",
        "reversal": {"method": "remove", "reference": "x", "reversal_decision_id": None},
        "notes": "kept",
    }
    updated = qp.apply_status_only_transition(vendor, "newco-promotion", "newco")
    changed = {k for k in set(vendor) | set(updated) if vendor.get(k) != updated.get(k)}
    assert changed <= qp.STATUS_ONLY_FIELDS
    assert updated["catalog_status"] == "active"
    assert updated["machine_decision_id"] == "newco-promotion"
    assert updated["reversal"]["method"] == "revert_promotion"
    assert updated["display_name"] == "NewCo"
    assert updated["notes"] == "kept"


# --------------------------------------------------------------------------- #
# Full prepare -> apply on a temp catalog
# --------------------------------------------------------------------------- #
def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False) if not str(path).endswith(".json") else json.dumps(data), encoding="utf-8")


def _build_temp_catalog(tmp_path: Path) -> tuple[Path, Path, Path]:
    vendor = {
        "schema_version": "0.1.0",
        "vendor_id": "newco",
        "display_name": "NewCo",
        "legal_name": None,
        "headquarters_country": "US",
        "official_domains": ["newco.com"],
        "public_entrypoints": ["https://newco.com"],
        "source_policy": {"public_sources_only": True, "gated_materials_excluded": True, "raw_documents_mirrored_by_default": False},
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": "newco-vendor-materialization",
        "reversal": {"method": "remove", "reference": "revert materialization", "reversal_decision_id": None},
    }
    _write(tmp_path / "data/vendors/newco/vendor.yaml", vendor)
    _write(tmp_path / "data/vendors/newco/sources/newco-privacy.yaml", {"source_id": "newco-privacy", "vendor_id": "newco", "source_type": "privacy_notice", "source_url": "https://newco.com/privacy"})
    _write(tmp_path / "data/vendors/newco/sources/newco-security.yaml", {"source_id": "newco-security", "vendor_id": "newco", "source_type": "security_page", "source_url": "https://newco.com/security"})
    # A second, unrelated vendor for identity/duplicate checks.
    _write(tmp_path / "data/vendors/other/vendor.yaml", {**vendor, "vendor_id": "other", "display_name": "Other Co", "official_domains": ["other.com"], "public_entrypoints": ["https://other.com"], "catalog_status": "active"})

    decisions_dir = tmp_path / "maintenance/machine-decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "2026-06.ndjson").write_text(
        json.dumps({
            "schema_version": "0.1.0",
            "decision_id": "newco-vendor-materialization",
            "decision_type": "vendor_materialization",
            "subject_type": "vendor",
            "subject_id": "newco",
            "decision": "materialize_provisional",
            "deciding_bot": "strict-growth-materializer",
            "supporting_bots": [],
            "discovery_bot": "catalog-growth-discovery",
            "evidence": {"official_domain": "newco.com"},
            "counter_evidence": [],
            "thresholds": {"required_score": 1.0, "actual_score": 1.0, "results": {}},
            "source_queue_reference": "strict_growth",
            "candidate_digest": "sha256:" + "a" * 64,
            "created_at": "2026-06-12T00:00:00Z",
            "not_before": "2026-06-14T00:00:00Z",
            "reversal": {"method": "remove", "reference": "revert", "reversal_decision_id": None},
            "not_advice": True,
        }) + "\n",
        encoding="utf-8",
    )

    ledger_dir = tmp_path / "maintenance/source-observations/events"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "2026-06.ndjson").write_text(
        json.dumps(healthy_event("newco-privacy")) + "\n" + json.dumps(healthy_event("newco-security")) + "\n",
        encoding="utf-8",
    )

    match_index = tmp_path / "indexes/vendor-match-index.json"
    match_index.parent.mkdir(parents=True)
    match_index.write_text(json.dumps({"items": [{"vendor_id": "other", "official_domains": ["other.com"], "display_name": "Other Co"}]}), encoding="utf-8")
    return decisions_dir, ledger_dir, match_index


def test_prepare_and_apply_promotion_status_only(tmp_path):
    decisions_dir, ledger_dir, match_index = _build_temp_catalog(tmp_path)
    prepared = qp.prepare_promotion(
        "newco",
        release_gate_decision="pass",
        root=tmp_path,
        now=NOW,
        ledger_dir=ledger_dir,
        decisions_dir=decisions_dir,
        match_index_path=match_index,
    )
    assert prepared.promotable, prepared.reasons

    report = qp.apply_promotion(prepared, root=tmp_path, decisions_dir=decisions_dir, rebuild=False)
    assert report["vendor_id"] == "newco"

    promoted = yaml.safe_load((tmp_path / "data/vendors/newco/vendor.yaml").read_text(encoding="utf-8"))
    assert promoted["catalog_status"] == "active"
    assert promoted["machine_decision_id"] == "newco-promotion"
    assert promoted["reversal"]["method"] == "revert_promotion"
    # display_name and other fields untouched (status-only).
    assert promoted["display_name"] == "NewCo"

    # The committed promotion decision is valid and separation-clean.
    assert md.validate_committed(decisions_dir) == []
    promote_records = [r for r in md.load_decisions(decisions_dir) if r["decision"] == "promote"]
    assert len(promote_records) == 1


def test_apply_refuses_non_provisional_vendor(tmp_path):
    decisions_dir, ledger_dir, match_index = _build_temp_catalog(tmp_path)
    prepared = qp.prepare_promotion(
        "newco", release_gate_decision="pass", root=tmp_path, now=NOW,
        ledger_dir=ledger_dir, decisions_dir=decisions_dir, match_index_path=match_index,
    )
    # Flip the on-disk vendor to active before applying -> apply must refuse.
    vendor_path = tmp_path / "data/vendors/newco/vendor.yaml"
    vendor = yaml.safe_load(vendor_path.read_text(encoding="utf-8"))
    vendor["catalog_status"] = "active"
    vendor_path.write_text(yaml.safe_dump(vendor, sort_keys=False), encoding="utf-8")
    try:
        qp.apply_promotion(prepared, root=tmp_path, decisions_dir=decisions_dir, rebuild=False)
        assert False, "apply should refuse a non-provisional vendor"
    except ValueError as exc:
        assert "machine_provisional" in str(exc)
