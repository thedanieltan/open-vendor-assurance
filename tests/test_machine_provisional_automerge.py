"""WP36b machine-provisional automerge gate tests (negative fixtures)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

from tools.openva import machine_provisional_automerge as mp

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
VENDOR_PATH = "data/vendors/okta/vendor.yaml"
DECISION_PATH = "maintenance/machine-decisions/2026-06.ndjson"
GENERATED = "indexes/vendors.json"
LABELS = [mp.MARKER_LABEL, mp.MACHINE_PROVISIONAL_LABEL]


def vendor_yaml(**overrides) -> str:
    record = {
        "vendor_id": "okta",
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": "okta-vendor-materialization",
        "reversal": {"method": "remove", "reference": "revert", "reversal_decision_id": None},
    }
    record.update(overrides)
    import yaml

    return yaml.safe_dump(record)


def decision_line(**overrides) -> str:
    record = {
        "decision_id": "okta-vendor-materialization",
        "subject_id": "okta",
        "decision": "materialize_provisional",
        "deciding_bot": "strict-growth-materializer",
        "discovery_bot": "catalog-growth-discovery",
        "not_before": "2026-06-15T00:00:00Z",  # past relative to NOW
        "not_advice": True,
    }
    record.update(overrides)
    return json.dumps(record)


def make_loader(*, base_has_vendor=False, vendor_text=None, decision_text=None):
    vendor_text = vendor_text if vendor_text is not None else vendor_yaml()
    decision_text = decision_text if decision_text is not None else decision_line()

    def loader(ref: str, path: str) -> str:
        if ref == "BASE":
            if path == VENDOR_PATH and not base_has_vendor:
                raise subprocess.CalledProcessError(128, ["git", "show"])
            return vendor_yaml()  # base copy if it exists
        if path == VENDOR_PATH:
            return vendor_text
        if path == DECISION_PATH:
            return decision_text
        raise subprocess.CalledProcessError(128, ["git", "show"])

    return loader


PATHS = [VENDOR_PATH, DECISION_PATH, GENERATED]


def test_accepts_valid_new_provisional_vendor():
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert result.eligible, result.reasons
    assert result.vendor_id == "okta"


def test_rejects_not_before_in_future():
    loader = make_loader(decision_text=decision_line(not_before="2026-06-25T00:00:00Z"))
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)
    assert not result.eligible
    assert any("not_before_not_passed" in r for r in result.reasons)


def test_rejects_existing_vendor_modification():
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=make_loader(base_has_vendor=True), now=NOW)
    assert not result.eligible
    assert any("vendor_already_exists" in r for r in result.reasons)


def test_rejects_non_provisional_status():
    loader = make_loader(vendor_text=vendor_yaml(catalog_status="active"))
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)
    assert not result.eligible
    assert any("catalog_status_not_machine_provisional" in r for r in result.reasons)


def test_rejects_disallowed_path():
    paths = PATHS + ["tools/openva/validate.py"]
    result = mp.check_machine_provisional_automerge(paths, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("disallowed_path" in r for r in result.reasons)


def test_rejects_two_vendors():
    paths = [VENDOR_PATH, "data/vendors/auth0/vendor.yaml", DECISION_PATH]
    result = mp.check_machine_provisional_automerge(paths, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("expected_exactly_one_new_vendor" in r for r in result.reasons)


def test_requires_both_labels():
    result = mp.check_machine_provisional_automerge(PATHS, [mp.MARKER_LABEL], "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("missing_label:automerge:machine-provisional" in r for r in result.reasons)


def test_rejects_separation_of_duty_violation():
    loader = make_loader(decision_text=decision_line(deciding_bot="same", discovery_bot="same"))
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)
    assert not result.eligible
    assert any("separation_of_duty" in r for r in result.reasons)


def test_rejects_missing_decision_record():
    paths = [VENDOR_PATH, GENERATED]  # no decision ndjson
    result = mp.check_machine_provisional_automerge(paths, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("missing_machine_decision_record" in r for r in result.reasons)
