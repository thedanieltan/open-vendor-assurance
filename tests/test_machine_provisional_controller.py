"""WP36b not_before controller + candidate-promotion workflow wiring tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.openva import machine_provisional_controller as ctl

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
WORKFLOW = Path(".github/workflows/candidate-promotion-pr.yml")


def materialize(not_before: str) -> dict:
    return {"decision": "materialize_provisional", "not_before": not_before}


def test_ready_when_not_before_passed():
    assert ctl.ready_for_automerge([materialize("2026-06-15T00:00:00Z")], NOW) is True


def test_not_ready_when_not_before_in_future():
    assert ctl.ready_for_automerge([materialize("2026-06-25T00:00:00Z")], NOW) is False


def test_not_ready_without_materialization_decision():
    assert ctl.ready_for_automerge([{"decision": "promote", "not_before": "2026-06-15T00:00:00Z"}], NOW) is False
    assert ctl.ready_for_automerge([], NOW) is False


def test_not_ready_when_any_materialization_still_delayed():
    decisions = [materialize("2026-06-15T00:00:00Z"), materialize("2026-06-25T00:00:00Z")]
    assert ctl.ready_for_automerge(decisions, NOW) is False


def test_not_ready_when_not_before_missing_or_unparseable():
    assert ctl.ready_for_automerge([{"decision": "materialize_provisional"}], NOW) is False
    assert ctl.ready_for_automerge([materialize("not-a-date")], NOW) is False


def test_decisions_at_ref_reads_all_ndjson(monkeypatch):
    import json

    files = {"maintenance/machine-decisions/2026-06.ndjson": json.dumps(materialize("2026-06-15T00:00:00Z"))}
    decisions = ctl.decisions_at_ref(
        "ref",
        ls_tree=lambda ref, path: list(files),
        show=lambda ref, path: files[path],
    )
    assert len(decisions) == 1 and decisions[0]["decision"] == "materialize_provisional"


# --- workflow wiring ---
def test_candidate_promotion_wires_machine_provisional_lane():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "machine-provisional-from-queue" in text
    assert "python -m tools.openva.missing_vendor_bridge build" in text
    # The decision record must be committed.
    assert "git add maintenance/machine-decisions" in text
    # Marker label on materialization; automerge label only via the controller.
    assert "--add-label machine-provisional" in text
    assert "--add-label automerge:machine-provisional" in text
    assert "python -m tools.openva.machine_provisional_controller ready" in text
