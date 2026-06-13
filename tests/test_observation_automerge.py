"""WP35.5 observation-automerge lane tests: plan filtering + append-only check
with negative fixtures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools.openva import observation_automerge as oa


def row(record_id: str, source_id: str, observed_at: str, *, event_type: str = "first_observed") -> dict:
    return {
        "schema_version": "0.1.0",
        "ledger_record_id": record_id,
        "vendor_id": "example-vendor",
        "source_id": source_id,
        "source_url": "https://vendor.example/privacy",
        "observed_at": observed_at,
        "run_id": "100",
        "event_type": event_type,
        "change_class": "none" if event_type == "first_observed" else "material_possible",
        "observation_id": f"{source_id}-{observed_at[:10]}-100",
        "source_health_status": "reachable",
        "review_signal": {"required": False},
        "not_advice": True,
    }


def ndjson(rows: list[dict]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def write_ledger(tmp_path: Path, rows: list[dict], month: str = "2026-06") -> Path:
    ledger = tmp_path / "events"
    ledger.mkdir()
    (ledger / f"{month}.ndjson").write_text(ndjson(rows), encoding="utf-8")
    return ledger


# --------------------------- plan --------------------------- #
def test_plan_filters_already_committed_rows(tmp_path):
    committed = row("rec-a", "src-a", "2026-06-01T00:00:00Z")
    ledger = write_ledger(tmp_path, [committed])
    delta = tmp_path / "delta.ndjson"
    fresh = row("rec-b", "src-b", "2026-06-02T00:00:00Z")
    delta.write_text(ndjson([committed, fresh]), encoding="utf-8")
    out_delta, out_sum = tmp_path / "f.ndjson", tmp_path / "s.json"
    code = oa.run_plan(delta, ledger, out_delta, out_sum)
    assert code == 0
    summary = json.loads(out_sum.read_text())
    assert summary["new_row_count"] == 1
    assert [json.loads(l)["ledger_record_id"] for l in out_delta.read_text().splitlines()] == ["rec-b"]


def test_plan_zero_new_rows_is_clean(tmp_path):
    committed = row("rec-a", "src-a", "2026-06-01T00:00:00Z")
    ledger = write_ledger(tmp_path, [committed])
    delta = tmp_path / "delta.ndjson"
    delta.write_text(ndjson([committed]), encoding="utf-8")
    code = oa.run_plan(delta, ledger, tmp_path / "f.ndjson", tmp_path / "s.json")
    assert code == 0
    assert json.loads((tmp_path / "s.json").read_text())["new_row_count"] == 0


def test_plan_rejects_out_of_order(tmp_path):
    committed = row("rec-a", "src-a", "2026-06-10T00:00:00Z")
    ledger = write_ledger(tmp_path, [committed])
    delta = tmp_path / "delta.ndjson"
    delta.write_text(ndjson([row("rec-old", "src-a", "2026-06-01T00:00:00Z")]), encoding="utf-8")
    code = oa.run_plan(delta, ledger, tmp_path / "f.ndjson", tmp_path / "s.json")
    assert code == 1
    assert any("out_of_order" in r for r in json.loads((tmp_path / "s.json").read_text())["reasons"])


def test_plan_rejects_schema_invalid_row(tmp_path):
    ledger = write_ledger(tmp_path, [])
    delta = tmp_path / "delta.ndjson"
    bad = row("rec-b", "src-b", "2026-06-02T00:00:00Z")
    del bad["not_advice"]  # required field
    delta.write_text(ndjson([bad]), encoding="utf-8")
    code = oa.run_plan(delta, ledger, tmp_path / "f.ndjson", tmp_path / "s.json")
    assert code == 1
    assert any("schema" in r for r in json.loads((tmp_path / "s.json").read_text())["reasons"])


# --------------------------- check --------------------------- #
LABELS = [oa.AUTOMERGE_OBSERVATION_LABEL, oa.OBSERVATION_LEDGER_LABEL]
PATH = "maintenance/source-observations/events/2026-06.ndjson"


def loader_for(base: str | None, head: str):
    def loader(ref: str, path: str) -> str:
        if ref == "BASE":
            if base is None:
                raise subprocess.CalledProcessError(128, ["git", "show"])
            return base
        return head
    return loader


def test_check_accepts_clean_append():
    base = ndjson([row("rec-a", "src-a", "2026-06-01T00:00:00Z")])
    head = base + ndjson([row("rec-b", "src-b", "2026-06-02T00:00:00Z")])
    result = oa.check_observation_automerge([PATH], LABELS, "BASE", "HEAD", loader=loader_for(base, head))
    assert result.eligible, result.reasons
    assert result.appended_rows == 1


def test_check_accepts_new_monthly_shard_with_no_base():
    head = ndjson([row("rec-b", "src-b", "2026-07-01T00:00:00Z")])
    result = oa.check_observation_automerge(
        ["maintenance/source-observations/events/2026-07.ndjson"], LABELS, "BASE", "HEAD",
        loader=loader_for(None, head),
    )
    assert result.eligible, result.reasons
    assert result.appended_rows == 1


def test_check_rejects_modified_existing_line():
    base = ndjson([row("rec-a", "src-a", "2026-06-01T00:00:00Z")])
    tampered = ndjson([row("rec-a", "src-a", "2026-06-09T00:00:00Z")])  # same id, changed line
    result = oa.check_observation_automerge([PATH], LABELS, "BASE", "HEAD", loader=loader_for(base, tampered))
    assert not result.eligible
    assert any("not_append_only" in r for r in result.reasons)


def test_check_rejects_non_ledger_path():
    head = ndjson([row("rec-b", "src-b", "2026-06-02T00:00:00Z")])
    result = oa.check_observation_automerge(
        ["data/vendors/example-vendor/vendor.yaml"], LABELS, "BASE", "HEAD", loader=loader_for("", head),
    )
    assert not result.eligible
    assert any("disallowed_path" in r for r in result.reasons)


def test_check_requires_both_labels():
    base = ""
    head = ndjson([row("rec-b", "src-b", "2026-06-02T00:00:00Z")])
    result = oa.check_observation_automerge([PATH], [oa.OBSERVATION_LEDGER_LABEL], "BASE", "HEAD", loader=loader_for(base, head))
    assert not result.eligible
    assert any("missing_label:automerge:observation" in r for r in result.reasons)


def test_check_rejects_schema_invalid_new_row():
    bad = row("rec-b", "src-b", "2026-06-02T00:00:00Z")
    del bad["not_advice"]
    head = ndjson([bad])
    result = oa.check_observation_automerge([PATH], LABELS, "BASE", "HEAD", loader=loader_for("", head))
    assert not result.eligible
    assert any("schema" in r for r in result.reasons)


def test_check_enforces_row_cap():
    head = ndjson([row(f"rec-{i}", f"src-{i}", "2026-06-02T00:00:00Z") for i in range(5)])
    result = oa.check_observation_automerge([PATH], LABELS, "BASE", "HEAD", loader=loader_for("", head), max_appended_rows=3)
    assert not result.eligible
    assert any("appended_row_limit_exceeded" in r for r in result.reasons)


def test_is_ledger_event_path():
    assert oa.is_ledger_event_path("maintenance/source-observations/events/2026-06.ndjson")
    assert not oa.is_ledger_event_path("maintenance/source-observations/events/notes.txt")
    assert not oa.is_ledger_event_path("maintenance/source-observations/2026-06.ndjson")
