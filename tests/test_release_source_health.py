from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.openva.release_source_health import (
    LoadedReport,
    build_release_source_health_readiness,
    load_optional_json,
    main,
)


NOW = datetime(2026, 5, 24, 8, 0, tzinfo=UTC)


def loaded(path: str, data: dict | None) -> LoadedReport:
    if data is None:
        return LoadedReport(path, False, None, None, None)
    return LoadedReport(path, True, data.get("report_type"), data.get("generated_at"), data)


def verification_report(**status_counts: int) -> dict:
    sources = []
    for status, count in status_counts.items():
        sources.extend(
            {
                "source_id": f"{status}-{index}",
                "verification_status": status,
            }
            for index in range(count)
        )
    return {
        "report_type": "source_verification_report",
        "generated_at": "2026-05-24T07:00:00Z",
        "summary": {"source_count": len(sources)},
        "breakdowns": {"verification_statuses": status_counts},
        "sources": sources,
    }


def confirmed_p0_report(count: int) -> dict:
    return {
        "report_type": "confirmed_p0_source_refinement_scan",
        "generated_at": "2026-05-24T07:30:00Z",
        "summary": {"confirmed_p0_count": count},
        "confirmed_p0": [{} for _ in range(count)],
    }


def test_release_source_health_ready_when_artifacts_are_clean_and_fresh():
    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", verification_report(ok=3, redirected=1)),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
    )

    assert report["status"] == "ready"
    assert report["summary"]["failure_count"] == 0
    assert report["summary"]["warning_count"] == 0
    assert report["summary"]["confirmed_p0_count"] == 0


def test_release_source_health_blocks_on_confirmed_p0_count():
    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", verification_report(ok=3)),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(2)),
        now=NOW,
    )

    assert report["status"] == "blocked"
    assert report["failures"][0]["code"] == "confirmed_p0_sources_present"
    assert report["failures"][0]["count"] == 2


def test_release_source_health_warns_on_ambiguous_source_statuses():
    report = build_release_source_health_readiness(
        loaded(
            "source-verification-report.json",
            verification_report(ok=2, bot_protected=1, possible_mismatch=3),
        ),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
    )

    codes = {warning["code"] for warning in report["warnings"]}
    assert report["status"] == "warning"
    assert "source_status_warning:bot_protected" in codes
    assert "source_status_warning:possible_mismatch" in codes


def test_release_source_health_warns_when_verification_artifact_is_missing():
    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", None),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
    )

    assert report["status"] == "warning"
    assert report["warnings"][0]["code"] == "missing_source_verification_report"
    assert "source health artifact unavailable" in report["warnings"][0]["message"]


def test_release_source_health_enforcement_fails_when_verification_artifact_is_missing():
    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", None),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
        enforce=True,
    )

    assert report["status"] == "blocked"
    assert report["failures"][0]["code"] == "missing_source_verification_report"
    assert "source health artifact unavailable" in report["failures"][0]["message"]
    assert report["policy"]["mode"] == "enforce"


def test_release_source_health_enforcement_fails_when_verification_artifact_is_invalid():
    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", {"report_type": "not_source_verification"}),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
        enforce=True,
    )

    assert report["status"] == "blocked"
    assert report["failures"][0]["code"] == "unexpected_source_verification_report_type"


def test_release_source_health_warns_on_stale_verification_artifact():
    stale = verification_report(ok=1)
    stale["generated_at"] = (NOW - timedelta(hours=200)).isoformat().replace("+00:00", "Z")

    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", stale),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
    )

    assert report["status"] == "warning"
    assert any(warning["code"] == "stale_source_verification_report" for warning in report["warnings"])


def test_release_source_health_enforcement_keeps_ambiguous_statuses_warning_only():
    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", verification_report(ok=1, bot_protected=2)),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
        enforce=True,
    )

    assert report["status"] == "warning"
    assert report["failures"] == []
    assert report["warnings"][0]["code"] == "source_status_warning:bot_protected"


def test_release_source_health_enforcement_keeps_stale_verification_warning_only():
    stale = verification_report(ok=1)
    stale["generated_at"] = (NOW - timedelta(hours=200)).isoformat().replace("+00:00", "Z")

    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", stale),
        loaded("confirmed-p0-repair-candidates.json", confirmed_p0_report(0)),
        now=NOW,
        enforce=True,
    )

    assert report["status"] == "warning"
    assert report["failures"] == []
    assert any(warning["code"] == "stale_source_verification_report" for warning in report["warnings"])


def test_release_source_health_warns_when_confirmed_p0_scan_is_missing():
    report = build_release_source_health_readiness(
        loaded("source-verification-report.json", verification_report(ok=1)),
        loaded("confirmed-p0-repair-candidates.json", None),
        now=NOW,
    )

    assert report["status"] == "warning"
    assert any(warning["code"] == "missing_confirmed_p0_scan" for warning in report["warnings"])


def test_load_optional_json_handles_missing_path(tmp_path: Path):
    report = load_optional_json(tmp_path / "missing.json")

    assert report.present is False
    assert report.data is None


def test_cli_writes_report_artifacts_and_report_only_returns_zero(tmp_path: Path):
    verification = tmp_path / "source-verification-report.json"
    p0 = tmp_path / "confirmed-p0-repair-candidates.json"
    output = tmp_path / "release-source-health-readiness.json"
    summary = tmp_path / "release-source-health-summary.md"
    verification.write_text(
        '{"report_type":"source_verification_report","generated_at":"2026-05-24T07:00:00Z","summary":{"source_count":1},"breakdowns":{"verification_statuses":{"ok":1}}}\n',
        encoding="utf-8",
    )
    p0.write_text(
        '{"report_type":"confirmed_p0_source_refinement_scan","summary":{"confirmed_p0_count":1}}\n',
        encoding="utf-8",
    )

    assert main([
        "check",
        "--source-verification-report",
        str(verification),
        "--confirmed-p0-scan",
        str(p0),
        "--output-json",
        str(output),
        "--summary-md",
        str(summary),
        "--report-only",
    ]) == 0
    assert output.is_file()
    assert summary.is_file()
    assert "confirmed_p0_count" in output.read_text(encoding="utf-8")


def test_cli_enforce_returns_nonzero_when_confirmed_p0_count_blocks(tmp_path: Path):
    verification = tmp_path / "source-verification-report.json"
    p0 = tmp_path / "confirmed-p0-repair-candidates.json"
    output = tmp_path / "release-source-health-readiness.json"
    summary = tmp_path / "release-source-health-summary.md"
    verification.write_text(
        '{"report_type":"source_verification_report","generated_at":"2026-05-24T07:00:00Z","summary":{"source_count":1},"breakdowns":{"verification_statuses":{"ok":1}}}\n',
        encoding="utf-8",
    )
    p0.write_text(
        '{"report_type":"confirmed_p0_source_refinement_scan","summary":{"confirmed_p0_count":1}}\n',
        encoding="utf-8",
    )

    assert main([
        "check",
        "--source-verification-report",
        str(verification),
        "--confirmed-p0-scan",
        str(p0),
        "--output-json",
        str(output),
        "--summary-md",
        str(summary),
        "--enforce",
    ]) == 1
    assert output.is_file()
    assert summary.is_file()
