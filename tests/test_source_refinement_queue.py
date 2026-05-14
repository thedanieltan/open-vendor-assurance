from __future__ import annotations

import json
from pathlib import Path

from tools.openva.source_refinement_queue import refinement_payload, render_markdown, write_queue


def report(items: list[dict]) -> dict:
    return {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-14T00:00:00Z",
        "total_sources": 4,
        "counts": {"ok": 1, "bot_protected": 1, "fetch_failed": 1, "size_limited": 1},
        "human_review_required_count": len(items),
        "human_review_queue": items,
    }


def item(vendor_id: str, source_id: str, result: str, http_status: int | None = None) -> dict:
    return {
        "vendor_id": vendor_id,
        "source_id": source_id,
        "result": result,
        "http_status": http_status,
        "final_url": f"https://example.com/{source_id}",
        "observed_at": "2026-05-14T00:00:00Z",
        "notes": "test note",
    }


def test_refinement_payload_filters_and_counts_human_review_items():
    payload = refinement_payload(
        report(
            [
                item("vendor-a", "ok-source", "ok", 200),
                item("vendor-b", "bot-source", "bot_protected", 403),
                item("vendor-c", "failed-source", "fetch_failed", None),
                item("vendor-d", "large-source", "size_limited", 200),
                item("vendor-e", "bad-source", "quarantined", None),
            ]
        ),
        generated_at="2026-05-14T01:00:00Z",
    )

    assert payload["generated_at"] == "2026-05-14T01:00:00Z"
    assert payload["observation_report_generated_at"] == "2026-05-14T00:00:00Z"
    assert payload["human_review_required_count"] == 4
    assert payload["counts"] == {
        "bot_protected": 1,
        "fetch_failed": 1,
        "quarantined": 1,
        "size_limited": 1,
    }
    assert payload["guarantees"] == {
        "does_not_mutate_catalog": True,
        "does_not_write_observations": True,
        "does_not_bypass_access_controls": True,
        "does_not_make_advisory_claims": True,
    }


def test_render_markdown_includes_boundaries_and_suggested_actions():
    payload = refinement_payload(
        report([item("vendor-b", "bot-source", "bot_protected", 403)]),
        generated_at="2026-05-14T01:00:00Z",
    )

    markdown = render_markdown(payload)

    assert "# OpenVA Source Refinement Queue" in markdown
    assert "Human review required: 1" in markdown
    assert "vendor-b" in markdown
    assert "bot-source" in markdown
    assert "Do not bypass anti-bot controls" in markdown
    assert "Do not write ambiguous observations by default" in markdown
    assert "not legal, compliance" in markdown


def test_render_markdown_handles_empty_queue():
    payload = refinement_payload(report([]), generated_at="2026-05-14T01:00:00Z")

    markdown = render_markdown(payload)

    assert "Human review required: 0" in markdown
    assert "No source-refinement items were produced." in markdown


def test_write_queue_outputs_markdown_and_json(tmp_path: Path):
    report_path = tmp_path / "observation-report.json"
    markdown_out = tmp_path / "queue.md"
    json_out = tmp_path / "queue.json"
    report_path.write_text(json.dumps(report([item("vendor-b", "bot-source", "bot_protected", 403)])), encoding="utf-8")

    assert write_queue(report_path, markdown_out=markdown_out, json_out=json_out) == 0

    assert "bot-source" in markdown_out.read_text(encoding="utf-8")
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["human_review_required_count"] == 1
    assert payload["items"][0]["suggested_action"].startswith("Manual review")
