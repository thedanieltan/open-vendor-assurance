"""WP38b rollback automerge gate tests (negative fixtures)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import yaml

from tools.openva import rollback_automerge as ra

NOW = datetime(2026, 6, 25, 0, 0, 0, tzinfo=UTC)
DECISION_PATH = "maintenance/machine-decisions/2026-06.ndjson"
GENERATED = "indexes/vendors.json"
LABELS = [ra.MARKER_LABEL, ra.ROLLBACK_LABEL]


def rollback_record(rolled_back="promote", **overrides) -> dict:
    record = {
        "decision_id": "newco-promotion-rollback",
        "decision": "rollback",
        "subject_type": "vendor",
        "subject_id": "newco",
        "deciding_bot": "rollback-controller",
        "discovery_bot": "quorum-promotion-decider",
        "not_before": "2026-06-20T00:00:00Z",
        "evidence": {"rolled_back_decision": rolled_back},
        "not_advice": True,
    }
    record.update(overrides)
    return record


def make_loader(*, files: dict[tuple[str, str], str]):
    def loader(ref: str, path: str) -> str:
        key = (ref, path)
        if key not in files:
            raise subprocess.CalledProcessError(128, ["git", "show"])
        return files[key]
    return loader


def promotion_files(*, base_decisions=None, head_decisions=None, base_vendor=None, head_vendor=None):
    base_decisions = base_decisions if base_decisions is not None else []
    head_decisions = head_decisions if head_decisions is not None else [rollback_record()]
    base_vendor = base_vendor if base_vendor is not None else {"vendor_id": "newco", "catalog_status": "active", "machine_decision_id": "newco-promotion", "reversal": {"method": "revert_promotion"}}
    head_vendor = head_vendor if head_vendor is not None else {"vendor_id": "newco", "catalog_status": "machine_provisional", "machine_decision_id": "newco-vendor-materialization", "reversal": {"method": "remove"}}
    files = {
        ("BASE", DECISION_PATH): "\n".join(json.dumps(d) for d in base_decisions),
        ("HEAD", DECISION_PATH): "\n".join(json.dumps(d) for d in head_decisions),
        ("BASE", "data/vendors/newco/vendor.yaml"): yaml.safe_dump(base_vendor),
        ("HEAD", "data/vendors/newco/vendor.yaml"): yaml.safe_dump(head_vendor),
    }
    return files


PROMOTION_PATHS = ["data/vendors/newco/vendor.yaml", DECISION_PATH, GENERATED]


def check(paths, files, labels=LABELS):
    return ra.check_rollback_automerge(paths, labels, "BASE", "HEAD", loader=make_loader(files=files), now=NOW)


def test_accepts_valid_promotion_rollback():
    result = check(PROMOTION_PATHS, promotion_files())
    assert result.eligible, result.reasons
    assert result.subject_id == "newco"


def test_rejects_reverser_equals_author():
    result = check(PROMOTION_PATHS, promotion_files(head_decisions=[rollback_record(discovery_bot="rollback-controller")]))
    assert not result.eligible
    assert any("reverser == author" in r for r in result.reasons)


def test_rejects_not_before_future():
    result = check(PROMOTION_PATHS, promotion_files(head_decisions=[rollback_record(not_before="2026-06-30T00:00:00Z")]))
    assert not result.eligible
    assert any("not_before_not_passed" in r for r in result.reasons)


def test_rejects_decision_history_rewrite():
    # base has a prior decision line that head drops -> history rewritten.
    prior = {"decision_id": "other", "decision": "promote"}
    files = promotion_files(base_decisions=[prior], head_decisions=[rollback_record()])
    result = check(PROMOTION_PATHS, files)
    assert not result.eligible
    assert any("decision_history_rewritten" in r for r in result.reasons)


def test_accepts_append_only_decisions():
    prior = {"decision_id": "other", "decision": "promote"}
    files = promotion_files(base_decisions=[prior], head_decisions=[prior, rollback_record()])
    result = check(PROMOTION_PATHS, files)
    assert result.eligible, result.reasons


def test_rejects_promotion_head_not_machine_provisional():
    files = promotion_files(head_vendor={"vendor_id": "newco", "catalog_status": "active", "machine_decision_id": "x", "reversal": {"method": "remove"}})
    result = check(PROMOTION_PATHS, files)
    assert not result.eligible
    assert any("head_not_machine_provisional" in r for r in result.reasons)


def test_rejects_non_status_field_change_in_promotion_rollback():
    files = promotion_files(head_vendor={"vendor_id": "newco-renamed", "catalog_status": "machine_provisional", "machine_decision_id": "x", "reversal": {"method": "remove"}})
    result = check(PROMOTION_PATHS, files)
    assert not result.eligible
    assert any("non_status_field_changed:vendor_id" in r for r in result.reasons)


def test_requires_both_labels():
    result = check(PROMOTION_PATHS, promotion_files(), labels=[ra.MARKER_LABEL])
    assert not result.eligible
    assert any("missing_label:automerge:rollback" in r for r in result.reasons)


def test_rejects_disallowed_path():
    result = check(PROMOTION_PATHS + ["tools/openva/validate.py"], promotion_files())
    assert not result.eligible
    assert any("disallowed_path" in r for r in result.reasons)


def test_rejects_missing_rollback_decision():
    files = promotion_files(head_decisions=[])
    result = check(PROMOTION_PATHS, files)
    assert not result.eligible
    assert any("expected_exactly_one_rollback_decision" in r for r in result.reasons)


# --- materialization rollback (vendor removal) ---
def test_accepts_materialization_rollback_when_vendor_removed():
    base_vendor = {"vendor_id": "newco", "catalog_status": "machine_provisional", "machine_generated": True}
    files = {
        ("BASE", DECISION_PATH): "",
        ("HEAD", DECISION_PATH): json.dumps(rollback_record(rolled_back="materialize_provisional", decision_id="newco-vendor-materialization-rollback")),
        ("BASE", "data/vendors/newco/vendor.yaml"): yaml.safe_dump(base_vendor),
        # HEAD vendor.yaml absent -> loader raises (removed).
    }
    result = check(["data/vendors/newco/vendor.yaml", DECISION_PATH, GENERATED], files)
    assert result.eligible, result.reasons


def test_rejects_materialization_rollback_when_vendor_still_present():
    base_vendor = {"vendor_id": "newco", "catalog_status": "machine_provisional", "machine_generated": True}
    files = {
        ("BASE", DECISION_PATH): "",
        ("HEAD", DECISION_PATH): json.dumps(rollback_record(rolled_back="materialize_provisional", decision_id="newco-vendor-materialization-rollback")),
        ("BASE", "data/vendors/newco/vendor.yaml"): yaml.safe_dump(base_vendor),
        ("HEAD", "data/vendors/newco/vendor.yaml"): yaml.safe_dump(base_vendor),
    }
    result = check(["data/vendors/newco/vendor.yaml", DECISION_PATH, GENERATED], files)
    assert not result.eligible
    assert any("vendor_still_present_at_head" in r for r in result.reasons)


# --- quarantine rollback ---
def test_accepts_quarantine_rollback():
    spath = "data/vendors/acme/sources/acme-dpa.yaml"
    base_source = {"source_id": "acme-dpa", "review_state": "quarantined", "quarantine": {"prior_review_state": "validated"}}
    head_source = {"source_id": "acme-dpa", "review_state": "validated"}
    files = {
        ("BASE", DECISION_PATH): "",
        ("HEAD", DECISION_PATH): json.dumps(rollback_record(rolled_back="quarantine", subject_type="source", subject_id="acme-dpa", discovery_bot="quarantine-controller", decision_id="acme-dpa-quarantine-rollback")),
        ("BASE", spath): yaml.safe_dump(base_source),
        ("HEAD", spath): yaml.safe_dump(head_source),
    }
    result = check([spath, DECISION_PATH, GENERATED], files)
    assert result.eligible, result.reasons


def test_rejects_quarantine_rollback_still_quarantined():
    spath = "data/vendors/acme/sources/acme-dpa.yaml"
    base_source = {"source_id": "acme-dpa", "review_state": "quarantined", "quarantine": {"prior_review_state": "validated"}}
    head_source = {"source_id": "acme-dpa", "review_state": "quarantined", "quarantine": {"prior_review_state": "validated"}}
    files = {
        ("BASE", DECISION_PATH): "",
        ("HEAD", DECISION_PATH): json.dumps(rollback_record(rolled_back="quarantine", subject_type="source", subject_id="acme-dpa", discovery_bot="quarantine-controller", decision_id="acme-dpa-quarantine-rollback")),
        ("BASE", spath): yaml.safe_dump(base_source),
        ("HEAD", spath): yaml.safe_dump(head_source),
    }
    result = check([spath, DECISION_PATH, GENERATED], files)
    assert not result.eligible
    assert any("head_still_quarantined" in r for r in result.reasons)
