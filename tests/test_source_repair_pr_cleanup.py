from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tools.openva.source_repair_pr_cleanup import build_cleanup_report, main


NOW = datetime(2026, 5, 25, tzinfo=UTC)


def pr(
    number: int,
    *,
    title: str = "Catalog: repair confirmed P0 sources",
    branch: str = "agent-source-repair-123",
    author: str = "github-actions[bot]",
    created_at: str = "2026-04-01T00:00:00Z",
    comments: list[dict] | None = None,
    reviews: list[dict] | None = None,
) -> dict:
    return {
        "number": number,
        "title": title,
        "url": f"https://github.example/pr/{number}",
        "headRefName": branch,
        "author": {"login": author},
        "createdAt": created_at,
        "updatedAt": created_at,
        "comments": comments or [],
        "reviews": reviews or [],
        "latestReviews": [],
    }


def test_stale_generated_repair_pr_older_than_30_days_is_eligible_for_closure():
    report = build_cleanup_report([pr(12)], now=NOW, generated_at="2026-05-25T00:00:00Z")

    assert report["summary"] == {
        "scanned_pr_count": 1,
        "closed_pr_count": 1,
        "skipped_pr_count": 0,
    }
    assert report["closed_prs"][0]["number"] == 12
    assert report["closed_prs"][0]["reason"] == "stale_generated_repair_pr"


def test_fresh_pr_is_not_closed():
    report = build_cleanup_report([pr(12, created_at="2026-05-10T00:00:00Z")], now=NOW)

    assert report["summary"]["closed_pr_count"] == 0
    assert report["skipped_prs"][0]["reason"] == "fresh_repair_pr"


def test_human_authored_pr_is_not_closed():
    report = build_cleanup_report([pr(12, author="maintainer")], now=NOW)

    assert report["summary"]["closed_pr_count"] == 0
    assert report["skipped_prs"][0]["reason"] == "human_authored_pr"


def test_non_repair_pr_is_not_closed():
    report = build_cleanup_report([pr(12, title="Docs: update source trust runbook")], now=NOW)

    assert report["summary"]["closed_pr_count"] == 0
    assert report["skipped_prs"][0]["reason"] == "non_repair_title"


def test_generated_repair_pr_with_human_activity_is_not_closed():
    report = build_cleanup_report(
        [
            pr(
                12,
                comments=[
                    {
                        "author": {"login": "maintainer"},
                        "createdAt": "2026-05-01T00:00:00Z",
                    }
                ],
            )
        ],
        now=NOW,
    )

    assert report["summary"]["closed_pr_count"] == 0
    assert report["skipped_prs"][0]["reason"] == "human_activity_detected"


def test_cleanup_report_schema_is_stable_and_has_guardrail_posture():
    report = build_cleanup_report([pr(12), pr(13, title="Catalog: add vendor")], now=NOW)

    assert set(report) == {
        "schema_version",
        "generated_at",
        "report_type",
        "stale_days",
        "posture",
        "summary",
        "closed_prs",
        "skipped_prs",
    }
    assert report["report_type"] == "source_repair_stale_pr_cleanup"
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "non_advisory": True,
    }
    text = json.dumps(report, sort_keys=True)
    assert "eligible" not in text
    assert "eligible_for_automerge" not in text
    assert "tool_recommendation" not in text


def test_cleanup_cli_writes_json_and_markdown(tmp_path: Path):
    prs_json = tmp_path / "prs.json"
    output = tmp_path / "source-repair-stale-pr-cleanup.json"
    markdown = tmp_path / "source-repair-stale-pr-cleanup.md"
    prs_json.write_text(json.dumps([pr(12), pr(13, created_at="2026-05-20T00:00:00Z")]), encoding="utf-8")

    assert main([
        "build",
        "--prs-json",
        str(prs_json),
        "--output",
        str(output),
        "--markdown-output",
        str(markdown),
        "--now",
        "2026-05-25T00:00:00Z",
    ]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["closed_pr_count"] == 1
    assert "# OpenVA Stale Source Repair PR Cleanup" in markdown.read_text(encoding="utf-8")
