from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva.observation_report import human_review_queue, render_markdown, report_payload, write_report


def observation(source_id: str, result: str, vendor_id: str = "vendor-a", http_status: int | None = 200) -> dict:
    return {
        "schema_version": "0.1.0",
        "observation_id": f"{source_id}-2026-05-14",
        "vendor_id": vendor_id,
        "source_id": source_id,
        "artifact_id": None,
        "observed_at": "2026-05-14T00:00:00Z",
        "result": result,
        "http_status": http_status,
        "final_url": f"https://example.com/{source_id}",
        "access_class": "public_web",
        "hashes": {
            "raw_sha256": "sha256:TBD",
            "normalized_text_sha256": "sha256:TBD",
            "etag": None,
            "last_modified": None,
        },
        "storage": {
            "raw_document_stored": False,
            "extracted_text_stored": False,
            "screenshot_stored": False,
        },
        "notes": "test observation",
    }


def test_human_review_queue_filters_ambiguous_results():
    observations = [
        observation("ok-source", "ok"),
        observation("bot-source", "bot_protected", http_status=403),
        observation("large-source", "size_limited"),
        observation("failed-source", "fetch_failed", http_status=None),
        observation("bad-source", "quarantined", http_status=None),
    ]

    queue = human_review_queue(observations)

    assert [item["source_id"] for item in queue] == [
        "bad-source",
        "bot-source",
        "failed-source",
        "large-source",
    ]
    assert all(item["result"] != "ok" for item in queue)


def test_report_payload_counts_results_and_review_queue():
    payload = report_payload(
        [
            observation("ok-a", "ok"),
            observation("ok-b", "ok"),
            observation("bot", "bot_protected", http_status=403),
        ],
        generated_at="2026-05-14T00:00:00Z",
    )

    assert payload["total_sources"] == 3
    assert payload["counts"] == {"bot_protected": 1, "ok": 2}
    assert payload["human_review_required_count"] == 1
    assert payload["human_review_queue"][0]["source_id"] == "bot"


def test_render_markdown_includes_review_queue_table():
    payload = report_payload([observation("bot", "bot_protected", http_status=403)], generated_at="2026-05-14T00:00:00Z")

    markdown = render_markdown(payload)

    assert "# OpenVA Observation Report" in markdown
    assert "Human review required: 1" in markdown
    assert "| vendor-a | bot | bot_protected | 403 | https://example.com/bot | 2026-05-14T00:00:00Z |" in markdown
    assert "not legal, compliance" in markdown


def test_render_markdown_handles_empty_review_queue():
    payload = report_payload([observation("ok", "ok")], generated_at="2026-05-14T00:00:00Z")

    markdown = render_markdown(payload)

    assert "Human review required: 0" in markdown
    assert "No ambiguous observation results were reported." in markdown


def test_write_report_accepts_observe_emit_yaml_output(tmp_path: Path):
    observations_path = tmp_path / "observations.txt"
    observations_path.write_text(
        "OpenVA observation summary\nmode: dry-run\n---\n"
        + yaml.safe_dump([observation("bot", "bot_protected", http_status=403)], sort_keys=False),
        encoding="utf-8",
    )
    markdown_out = tmp_path / "report.md"
    json_out = tmp_path / "report.json"

    assert write_report(observations_path, markdown_out=markdown_out, json_out=json_out) == 0

    assert "bot_protected" in markdown_out.read_text(encoding="utf-8")
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["human_review_required_count"] == 1
