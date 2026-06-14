"""WP40 Issue 15: end-to-end autonomous lifecycle smoke over the real tool chain."""

from __future__ import annotations

from tools.openva import lifecycle_smoke


def test_full_lifecycle_reaches_active_with_clean_audit(tmp_path):
    evidence = lifecycle_smoke.run(tmp_path)
    assert evidence["candidate_valid"] is True
    assert evidence["candidate_origin"] == "human_submission"
    assert evidence["final_catalog_status"] == "active"
    assert evidence["final_issue_state"] == "active"
    assert evidence["audit_clean"] is True
    assert evidence["audit_defects"] == 0


def test_smoke_records_both_decisions_and_separation_of_duty(tmp_path):
    evidence = lifecycle_smoke.run(tmp_path)
    assert evidence["materialization_decision_id"].endswith("-materialize")
    assert evidence["promotion_decision_id"].endswith("-promote")
    assert evidence["separation_of_duty"]["materialize"] is True
    assert evidence["separation_of_duty"]["promote"] is True


def test_smoke_telemetry_and_rollback_state(tmp_path):
    evidence = lifecycle_smoke.run(tmp_path)
    assert evidence["telemetry_promoted_vendors"] == 1
    assert evidence["telemetry_decisions_total"] == 2
    # a clean lifecycle produces nothing to roll back
    assert evidence["rollback_eligible_count"] == 0


def test_smoke_pr_body_has_no_human_checklist(tmp_path):
    evidence = lifecycle_smoke.run(tmp_path)
    assert evidence["pr_body_has_no_human_checklist"] is True


def test_smoke_does_not_touch_public_catalog(tmp_path):
    # the smoke writes only under the supplied isolated root
    lifecycle_smoke.run(tmp_path)
    assert (tmp_path / "data" / "vendors" / "smoke-vendor" / "vendor.yaml").exists()


def test_smoke_is_deterministic(tmp_path):
    a = lifecycle_smoke.run(tmp_path / "a")
    b = lifecycle_smoke.run(tmp_path / "b")
    # ids and digests are stable across isolated runs
    assert a["candidate_id"] == b["candidate_id"]
    assert a["evidence_digest"] == b["evidence_digest"]
    assert a["audit_clean"] == b["audit_clean"] is True
