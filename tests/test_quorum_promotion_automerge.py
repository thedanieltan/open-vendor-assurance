"""WP37 quorum-promotion automerge gate tests (negative fixtures)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import yaml

from tools.openva import quorum_promotion_automerge as qp

NOW = datetime(2026, 6, 25, 0, 0, 0, tzinfo=UTC)
VENDOR_PATH = "data/vendors/newco/vendor.yaml"
DECISION_PATH = "maintenance/machine-decisions/2026-06.ndjson"
GENERATED = "indexes/vendors.json"
LABELS = [qp.MARKER_LABEL, qp.QUORUM_PROMOTION_LABEL]
PATHS = [VENDOR_PATH, DECISION_PATH, GENERATED]


def base_vendor(**overrides) -> dict:
    record = {
        "vendor_id": "newco",
        "display_name": "NewCo",
        "official_domains": ["newco.com"],
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": "newco-vendor-materialization",
        "reversal": {"method": "remove", "reference": "revert materialization", "reversal_decision_id": None},
    }
    record.update(overrides)
    return record


def head_vendor(**overrides) -> dict:
    record = base_vendor(
        catalog_status="active",
        machine_decision_id="newco-promotion",
        reversal={"method": "revert_promotion", "reference": "revert promotion", "reversal_decision_id": None},
    )
    record.update(overrides)
    return record


def decision_line(**overrides) -> str:
    record = {
        "decision_id": "newco-promotion",
        "decision": "promote",
        "subject_id": "newco",
        "deciding_bot": "quorum-promotion-decider",
        "discovery_bot": "catalog-growth-discovery",
        "supporting_bots": ["quorum-identity-resolver", "quorum-source-verifier"],
        "not_before": "2026-06-20T00:00:00Z",  # past relative to NOW
        "not_advice": True,
    }
    record.update(overrides)
    return json.dumps(record)


def make_loader(*, base=None, head=None, decision=None, base_has_vendor=True):
    base = base if base is not None else base_vendor()
    head = head if head is not None else head_vendor()
    decision = decision if decision is not None else decision_line()

    def loader(ref: str, path: str) -> str:
        if path == VENDOR_PATH:
            if ref == "BASE":
                if not base_has_vendor:
                    raise subprocess.CalledProcessError(128, ["git", "show"])
                return yaml.safe_dump(base)
            return yaml.safe_dump(head)
        if path == DECISION_PATH:
            return decision
        raise subprocess.CalledProcessError(128, ["git", "show"])

    return loader


def check(paths=PATHS, labels=LABELS, **loader_kwargs):
    return qp.check_quorum_promotion_automerge(paths, labels, "BASE", "HEAD", loader=make_loader(**loader_kwargs), now=NOW)


def test_accepts_valid_status_only_promotion():
    result = check()
    assert result.eligible, result.reasons
    assert result.vendor_id == "newco"


def test_rejects_not_before_in_future():
    result = check(decision=decision_line(not_before="2026-06-30T00:00:00Z"))
    assert not result.eligible
    assert any("not_before_not_passed" in r for r in result.reasons)


def test_rejects_vendor_absent_at_base():
    result = check(base_has_vendor=False)
    assert not result.eligible
    assert any("vendor_absent_at_base" in r for r in result.reasons)


def test_rejects_base_not_machine_provisional():
    result = check(base=base_vendor(catalog_status="active"))
    assert not result.eligible
    assert any("base_status_not_machine_provisional" in r for r in result.reasons)


def test_rejects_head_not_active():
    result = check(head=head_vendor(catalog_status="machine_provisional"))
    assert not result.eligible
    assert any("head_status_not_active" in r for r in result.reasons)


def test_rejects_non_status_field_change():
    result = check(head=head_vendor(display_name="NewCo Renamed"))
    assert not result.eligible
    assert any("non_status_field_changed:display_name" in r for r in result.reasons)


def test_rejects_source_file_change():
    paths = PATHS + ["data/vendors/newco/sources/newco-privacy.yaml"]
    result = check(paths=paths)
    assert not result.eligible
    assert any("non_status_only_vendor_path" in r for r in result.reasons)


def test_rejects_disallowed_path():
    result = check(paths=PATHS + ["tools/openva/validate.py"])
    assert not result.eligible
    assert any("disallowed_path" in r for r in result.reasons)


def test_rejects_two_vendors():
    result = check(paths=[VENDOR_PATH, "data/vendors/other/vendor.yaml", DECISION_PATH])
    assert not result.eligible
    assert any("expected_exactly_one_vendor" in r for r in result.reasons)


def test_requires_both_labels():
    result = check(labels=[qp.MARKER_LABEL])
    assert not result.eligible
    assert any("missing_label:automerge:quorum-promotion" in r for r in result.reasons)


def test_rejects_separation_of_duty_discovery_equals_deciding():
    result = check(decision=decision_line(discovery_bot="quorum-promotion-decider"))
    assert not result.eligible
    assert any("separation_of_duty:deciding_bot == discovery_bot" in r for r in result.reasons)


def test_rejects_deciding_sole_supporter():
    result = check(decision=decision_line(supporting_bots=["quorum-promotion-decider"]))
    assert not result.eligible
    assert any("sole supporter" in r for r in result.reasons)


def test_rejects_insufficient_independent_supporters():
    result = check(decision=decision_line(supporting_bots=["quorum-identity-resolver"]))
    assert not result.eligible
    assert any("insufficient_independent_supporting_bots" in r for r in result.reasons)


def test_rejects_wrong_decision_kind():
    result = check(decision=decision_line(decision="materialize_provisional"))
    assert not result.eligible
    assert any("unexpected_decision" in r for r in result.reasons)


def test_rejects_missing_decision_record():
    result = check(paths=[VENDOR_PATH, GENERATED])
    assert not result.eligible
    assert any("missing_promotion_decision_record" in r for r in result.reasons)


def test_rejects_head_reversal_not_revert_promotion():
    result = check(head=head_vendor(reversal={"method": "remove", "reference": "x", "reversal_decision_id": None}))
    assert not result.eligible
    assert any("head_reversal_method_not_revert_promotion" in r for r in result.reasons)
