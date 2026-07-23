"""Every architecture decision record cites a declared work package.

WP-OPENVA-TRUTH-RECONCILIATION-01.
"""

from __future__ import annotations

from pathlib import Path

from tools.openva import doc_truth

ROOT = Path(__file__).resolve().parents[1]


def test_all_adrs_cite_a_declared_work_package():
    assert doc_truth.check() == []


def test_there_is_at_least_one_adr_to_check():
    # Guard against the glob silently matching nothing (vacuous pass).
    assert doc_truth.adr_paths()


def test_fails_closed_on_an_undeclared_work_package(tmp_path, monkeypatch):
    adr = tmp_path / "ADR-9999-example.md"
    adr.write_text(
        "# ADR-9999: Example\n\nWork package: WP-DOES-NOT-EXIST-01.\n", encoding="utf-8"
    )
    monkeypatch.setattr(doc_truth, "ADR_DIR", tmp_path)
    problems = doc_truth.check()
    assert any("WP-DOES-NOT-EXIST-01" in p and "not declared" in p for p in problems)


def test_fails_closed_when_an_adr_omits_its_work_package(tmp_path, monkeypatch):
    adr = tmp_path / "ADR-9998-example.md"
    adr.write_text("# ADR-9998: Example\n\nNo work-package line here.\n", encoding="utf-8")
    monkeypatch.setattr(doc_truth, "ADR_DIR", tmp_path)
    problems = doc_truth.check()
    assert any("ADR-9998" in p and "exactly one" in p for p in problems)
