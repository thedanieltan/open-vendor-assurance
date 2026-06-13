"""WP38b Level-5 rollback: inverse application + reverser-not-author."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import yaml

from tools.openva import machine_decisions as md
from tools.openva import rollback as rb
from tools.openva.indexes import ROOT

NOW = datetime(2026, 6, 25, 0, 0, 0, tzinfo=UTC)
DECISION_SCHEMA = json.loads((ROOT / "schemas" / "openva" / "machine-decision-record.schema.json").read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _decisions(tmp_path: Path, *records: dict) -> Path:
    decisions_dir = tmp_path / "maintenance/machine-decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "2026-06.ndjson").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return decisions_dir


def promote_decision(**overrides) -> dict:
    record = {
        "schema_version": "0.1.0", "decision_id": "newco-promotion", "decision_type": "promotion",
        "subject_type": "vendor", "subject_id": "newco", "decision": "promote",
        "deciding_bot": "quorum-promotion-decider", "supporting_bots": ["quorum-identity-resolver", "quorum-source-verifier"],
        "discovery_bot": "catalog-growth-discovery",
        "evidence": {"materialization_decision_id": "newco-vendor-materialization"},
        "counter_evidence": [], "thresholds": {"required_score": 1.0, "actual_score": 1.0, "results": {}},
        "source_queue_reference": "machine_provisional:newco", "candidate_digest": "sha256:" + "a" * 64,
        "created_at": "2026-06-12T00:00:00Z", "not_before": "2026-06-14T00:00:00Z",
        "reversal": {"method": "revert_promotion", "reference": "x", "reversal_decision_id": None}, "not_advice": True,
    }
    record.update(overrides)
    return record


def materialize_decision(**overrides) -> dict:
    record = promote_decision(
        decision_id="newco-vendor-materialization", decision_type="vendor_materialization",
        decision="materialize_provisional", deciding_bot="strict-growth-materializer", supporting_bots=[],
        evidence={"official_domain": "newco.com"},
        reversal={"method": "remove", "reference": "x", "reversal_decision_id": None},
    )
    record.update(overrides)
    return record


def quarantine_decision(**overrides) -> dict:
    record = promote_decision(
        decision_id="acme-dpa-quarantine", decision_type="quarantine", subject_type="source",
        subject_id="acme-dpa", decision="quarantine", deciding_bot="quarantine-controller", supporting_bots=[],
        discovery_bot="source-observation-ledger", evidence={"quarantine_reason": "persistent_not_found"},
        source_queue_reference="observation:acme-dpa",
        reversal={"method": "revert_quarantine", "reference": "x", "reversal_decision_id": None},
    )
    record.update(overrides)
    return record


def vendor(**overrides) -> dict:
    record = {
        "schema_version": "0.1.0", "vendor_id": "newco", "display_name": "NewCo", "legal_name": None,
        "headquarters_country": "US", "official_domains": ["newco.com"],
        "source_policy": {"public_sources_only": True, "gated_materials_excluded": True, "raw_documents_mirrored_by_default": False},
        "catalog_status": "active", "machine_generated": True, "machine_decision_id": "newco-promotion",
        "reversal": {"method": "revert_promotion", "reference": "x", "reversal_decision_id": None},
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------- #
# Decision build + separation of duty
# --------------------------------------------------------------------------- #
def test_rollback_decision_is_schema_valid_and_reverser_not_author():
    decision = rb.build_rollback_decision(promote_decision(), thresholds=rb.load_thresholds(), now=NOW)
    jsonschema.validate(decision, DECISION_SCHEMA)
    assert decision["decision_type"] == "rollback"
    assert decision["decision"] == "rollback"
    assert decision["deciding_bot"] == rb.ROLLBACK_BOT
    assert decision["discovery_bot"] == "quorum-promotion-decider"  # original author
    assert decision["deciding_bot"] != decision["discovery_bot"]
    assert decision["reversal"]["method"] == "reapply"
    assert md.separation_of_duty_violation(decision) is None


def test_rollback_refuses_to_revert_own_authored_state():
    target = promote_decision(deciding_bot=rb.ROLLBACK_BOT)
    with pytest.raises(ValueError, match="separation_of_duty"):
        rb.build_rollback_decision(target, thresholds=rb.load_thresholds(), now=NOW)


# --------------------------------------------------------------------------- #
# Inverse application on a temp catalog
# --------------------------------------------------------------------------- #
def test_rollback_promotion_restores_machine_provisional(tmp_path):
    _write(tmp_path / "data/vendors/newco/vendor.yaml", vendor())
    decisions_dir = _decisions(tmp_path, materialize_decision(), promote_decision())
    prepared = rb.prepare_rollback("newco-promotion", root=tmp_path, now=NOW, decisions_dir=decisions_dir)
    report = rb.apply_rollback(prepared, root=tmp_path, decisions_dir=decisions_dir, now=NOW, rebuild=False)
    assert report["subject_id"] == "newco"
    restored = yaml.safe_load((tmp_path / "data/vendors/newco/vendor.yaml").read_text(encoding="utf-8"))
    assert restored["catalog_status"] == "machine_provisional"
    assert restored["machine_decision_id"] == "newco-vendor-materialization"
    assert restored["reversal"]["method"] == "remove"
    assert md.validate_committed(decisions_dir) == []


def test_rollback_materialization_removes_vendor(tmp_path):
    _write(tmp_path / "data/vendors/newco/vendor.yaml", vendor(catalog_status="machine_provisional", machine_decision_id="newco-vendor-materialization"))
    _write(tmp_path / "data/vendors/newco/sources/newco-privacy.yaml", {"source_id": "newco-privacy", "vendor_id": "newco"})
    decisions_dir = _decisions(tmp_path, materialize_decision())
    prepared = rb.prepare_rollback("newco-vendor-materialization", root=tmp_path, now=NOW, decisions_dir=decisions_dir)
    report = rb.apply_rollback(prepared, root=tmp_path, decisions_dir=decisions_dir, now=NOW, rebuild=False)
    assert not (tmp_path / "data/vendors/newco").exists()
    assert any("newco" in p for p in report["affected_paths"])


def test_rollback_quarantine_restores_prior_review_state(tmp_path):
    src = {
        "schema_version": "0.1.0", "source_id": "acme-dpa", "vendor_id": "acme", "source_type": "dpa",
        "title_native": "Acme DPA", "source_url": "https://acme.com/dpa", "source_language": "en",
        "source_authority_class": "vendor_published", "access_class": "public_web", "rights_class": "metadata_only",
        "review_state": "quarantined",
        "quarantine": {"reason": "persistent_not_found", "quarantined_by": "quarantine-controller",
                       "quarantined_at": "2026-06-20T00:00:00Z", "prior_review_state": "validated",
                       "decision_id": "acme-dpa-quarantine",
                       "reversal": {"method": "revert_quarantine", "reference": "x", "reversal_decision_id": None}},
        "provenance": {"publisher": "vendor", "collected_at": "2026-06-01T00:00:00Z", "observer": "agent", "confidence": "medium"},
        "not_advice": True,
    }
    _write(tmp_path / "data/vendors/acme/sources/acme-dpa.yaml", src)
    decisions_dir = _decisions(tmp_path, quarantine_decision())
    prepared = rb.prepare_rollback("acme-dpa-quarantine", root=tmp_path, now=NOW, decisions_dir=decisions_dir)
    rb.apply_rollback(prepared, root=tmp_path, decisions_dir=decisions_dir, now=NOW, rebuild=False)
    restored = yaml.safe_load((tmp_path / "data/vendors/acme/sources/acme-dpa.yaml").read_text(encoding="utf-8"))
    assert restored["review_state"] == "validated"
    assert "quarantine" not in restored


def test_prepare_refuses_non_reversible_decision(tmp_path):
    decisions_dir = _decisions(tmp_path, promote_decision(decision="reject", decision_id="x-reject"))
    with pytest.raises(ValueError, match="not rollback-eligible"):
        rb.prepare_rollback("x-reject", root=tmp_path, now=NOW, decisions_dir=decisions_dir)


def test_prepare_refuses_double_rollback(tmp_path):
    _write(tmp_path / "data/vendors/newco/vendor.yaml", vendor())
    decisions_dir = _decisions(tmp_path, materialize_decision(), promote_decision())
    prepared = rb.prepare_rollback("newco-promotion", root=tmp_path, now=NOW, decisions_dir=decisions_dir)
    rb.apply_rollback(prepared, root=tmp_path, decisions_dir=decisions_dir, now=NOW, rebuild=False)
    with pytest.raises(ValueError, match="already rolled back"):
        rb.prepare_rollback("newco-promotion", root=tmp_path, now=NOW, decisions_dir=decisions_dir)
