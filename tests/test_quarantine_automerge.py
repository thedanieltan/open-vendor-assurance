"""WP38a quarantine automerge gate tests (negative fixtures)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import yaml

from tools.openva import quarantine_automerge as qa

NOW = datetime(2026, 6, 25, 0, 0, 0, tzinfo=UTC)
SOURCE_PATH = "data/vendors/acme/sources/acme-dpa.yaml"
DECISION_PATH = "maintenance/machine-decisions/2026-06.ndjson"
GENERATED = "indexes/sources.json"
LABELS = [qa.MARKER_LABEL, qa.QUARANTINE_LABEL]
PATHS = [SOURCE_PATH, DECISION_PATH, GENERATED]


def base_source(**overrides) -> dict:
    record = {
        "schema_version": "0.1.0",
        "source_id": "acme-dpa",
        "vendor_id": "acme",
        "source_type": "dpa",
        "source_url": "https://acme.com/dpa",
        "review_state": "validated",
    }
    record.update(overrides)
    return record


def head_source(**overrides) -> dict:
    record = base_source(review_state="quarantined")
    record["quarantine"] = {
        "reason": "persistent_not_found",
        "quarantined_by": "quarantine-controller",
        "quarantined_at": "2026-06-20T00:00:00Z",
        "decision_id": "acme-dpa-quarantine",
        "reversal": {"method": "revert_quarantine", "reference": "revert", "reversal_decision_id": None},
    }
    record.update(overrides)
    return record


def decision_line(**overrides) -> str:
    record = {
        "decision_id": "acme-dpa-quarantine",
        "decision": "quarantine",
        "subject_id": "acme-dpa",
        "deciding_bot": "quarantine-controller",
        "discovery_bot": "source-observation-ledger",
        "not_before": "2026-06-20T00:00:00Z",
        "not_advice": True,
    }
    record.update(overrides)
    return json.dumps(record)


def make_loader(*, base=None, head=None, decision=None, base_has_source=True):
    base = base if base is not None else base_source()
    head = head if head is not None else head_source()
    decision = decision if decision is not None else decision_line()

    def loader(ref: str, path: str) -> str:
        if path == SOURCE_PATH:
            if ref == "BASE":
                if not base_has_source:
                    raise subprocess.CalledProcessError(128, ["git", "show"])
                return yaml.safe_dump(base)
            return yaml.safe_dump(head)
        if path == DECISION_PATH:
            return decision
        raise subprocess.CalledProcessError(128, ["git", "show"])

    return loader


def check(paths=PATHS, labels=LABELS, **loader_kwargs):
    return qa.check_quarantine_automerge(paths, labels, "BASE", "HEAD", loader=make_loader(**loader_kwargs), now=NOW)


def test_accepts_valid_status_only_quarantine():
    result = check()
    assert result.eligible, result.reasons
    assert result.source_id == "acme-dpa"


def test_rejects_not_before_in_future():
    result = check(decision=decision_line(not_before="2026-06-30T00:00:00Z"))
    assert not result.eligible
    assert any("not_before_not_passed" in r for r in result.reasons)


def test_rejects_source_absent_at_base():
    result = check(base_has_source=False)
    assert not result.eligible
    assert any("source_absent_at_base" in r for r in result.reasons)


def test_rejects_base_already_quarantined():
    result = check(base=base_source(review_state="quarantined"))
    assert not result.eligible
    assert any("base_already_quarantined" in r for r in result.reasons)


def test_rejects_head_not_quarantined():
    result = check(head=head_source(review_state="validated"))
    assert not result.eligible
    assert any("head_review_state_not_quarantined" in r for r in result.reasons)


def test_rejects_non_status_field_change():
    result = check(head=head_source(source_url="https://acme.com/changed"))
    assert not result.eligible
    assert any("non_status_field_changed:source_url" in r for r in result.reasons)


def test_rejects_other_vendor_file_change():
    result = check(paths=PATHS + ["data/vendors/acme/vendor.yaml"])
    assert not result.eligible
    assert any("non_source_vendor_path" in r for r in result.reasons)


def test_rejects_disallowed_path():
    result = check(paths=PATHS + ["tools/openva/validate.py"])
    assert not result.eligible
    assert any("disallowed_path" in r for r in result.reasons)


def test_rejects_two_sources():
    result = check(paths=[SOURCE_PATH, "data/vendors/acme/sources/acme-security.yaml", DECISION_PATH])
    assert not result.eligible
    assert any("expected_exactly_one_source" in r for r in result.reasons)


def test_requires_both_labels():
    result = check(labels=[qa.MARKER_LABEL])
    assert not result.eligible
    assert any("missing_label:automerge:quarantine" in r for r in result.reasons)


def test_rejects_separation_of_duty_violation():
    result = check(decision=decision_line(discovery_bot="quarantine-controller"))
    assert not result.eligible
    assert any("separation_of_duty:deciding_bot == discovery_bot" in r for r in result.reasons)


def test_rejects_wrong_decision_kind():
    result = check(decision=decision_line(decision="promote"))
    assert not result.eligible
    assert any("unexpected_decision" in r for r in result.reasons)


def test_rejects_missing_decision_record():
    result = check(paths=[SOURCE_PATH, GENERATED])
    assert not result.eligible
    assert any("missing_quarantine_decision_record" in r for r in result.reasons)


def test_rejects_head_reversal_not_revert_quarantine():
    bad = head_source()
    bad["quarantine"]["reversal"]["method"] = "remove"
    result = check(head=bad)
    assert not result.eligible
    assert any("head_reversal_method_not_revert_quarantine" in r for r in result.reasons)
