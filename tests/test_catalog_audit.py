"""WP39 catalog reproducibility audit tests (all four defect classes)."""

from __future__ import annotations

import json

import yaml

from tools.openva import catalog_audit as ca


def _vendor(tmp, vendor_id="ghost", **overrides):
    record = {
        "vendor_id": vendor_id,
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": f"{vendor_id}-vendor-materialization",
        "reversal": {"method": "remove", "reference": "revert", "reversal_decision_id": None},
    }
    record.update(overrides)
    path = tmp / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record), encoding="utf-8")
    return path


def _source(tmp, vendor_id="acme", source_id="acme-dpa", **overrides):
    record = {
        "source_id": source_id,
        "vendor_id": vendor_id,
        "review_state": "quarantined",
        "quarantine": {
            "reason": "persistent_not_found", "quarantined_by": "quarantine-controller",
            "quarantined_at": "2026-06-20T00:00:00Z", "decision_id": f"{source_id}-quarantine",
            "reversal": {"method": "revert_quarantine", "reference": "revert", "reversal_decision_id": None},
        },
    }
    record.update(overrides)
    path = tmp / "data" / "vendors" / vendor_id / "sources" / f"{source_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record), encoding="utf-8")
    return path


def _decisions(tmp, *records):
    d = tmp / "maintenance" / "machine-decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-06.ndjson").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return d


def materialize(vendor_id="ghost"):
    return {"decision_id": f"{vendor_id}-vendor-materialization", "decision": "materialize_provisional", "subject_type": "vendor", "subject_id": vendor_id}


def promote(vendor_id="ghost"):
    return {"decision_id": f"{vendor_id}-promotion", "decision": "promote", "subject_type": "vendor", "subject_id": vendor_id}


def quarantine(source_id="acme-dpa"):
    return {"decision_id": f"{source_id}-quarantine", "decision": "quarantine", "subject_type": "source", "subject_id": source_id}


def test_clean_when_decision_present_and_reversible(tmp_path):
    _vendor(tmp_path)
    d = _decisions(tmp_path, materialize())
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert report.clean, report.findings
    assert report.machine_vendors == 1


def test_missing_decision_detected(tmp_path):
    _vendor(tmp_path)
    d = _decisions(tmp_path)  # empty
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert any(f["defect"] == "missing" for f in report.findings)


def test_non_reversible_detected(tmp_path):
    _vendor(tmp_path, reversal={})
    d = _decisions(tmp_path, materialize())
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert any(f["defect"] == "non_reversible" for f in report.findings)


def test_contradictory_status_detected(tmp_path):
    # active machine vendor linked to a materialization (not a promotion) decision.
    _vendor(tmp_path, catalog_status="active")
    d = _decisions(tmp_path, materialize())
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert any(f["defect"] == "contradictory" for f in report.findings)


def test_orphan_decision_detected(tmp_path):
    # A promotion decision whose vendor does not exist and was not rolled back.
    (tmp_path / "data" / "vendors").mkdir(parents=True)
    d = _decisions(tmp_path, promote("nowhere"))
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert any(f["defect"] == "orphan" for f in report.findings)


def test_rolled_back_decision_is_not_orphan(tmp_path):
    (tmp_path / "data" / "vendors").mkdir(parents=True)
    rollback = {"decision_id": "nowhere-vendor-materialization-rollback", "decision": "rollback",
                "subject_type": "vendor", "subject_id": "nowhere",
                "evidence": {"rolled_back_decision_id": "nowhere-vendor-materialization"}}
    d = _decisions(tmp_path, materialize("nowhere"), rollback)
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert not any(f["defect"] == "orphan" for f in report.findings), report.findings


def test_quarantined_source_reproducible(tmp_path):
    _source(tmp_path)
    d = _decisions(tmp_path, quarantine())
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert report.clean, report.findings
    assert report.machine_sources == 1


def test_quarantined_source_missing_decision_detected(tmp_path):
    _source(tmp_path)
    d = _decisions(tmp_path)
    report = ca.audit_catalog(root=tmp_path, decisions_dir=d)
    assert any(f["defect"] == "missing" and f["subject_type"] == "source" for f in report.findings)
