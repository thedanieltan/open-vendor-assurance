from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HUMAN_REVIEW_RESULTS = {"bot_protected", "size_limited", "fetch_failed", "quarantined"}

SUGGESTED_ACTIONS = {
    "bot_protected": "Manual review: confirm whether the source remains public for humans. If appropriate, look for a clearer public vendor-controlled trust, legal, security, DPA, or subprocessor page. Do not bypass anti-bot controls.",
    "size_limited": "Manual review: confirm whether a more specific public vendor-controlled page or document landing page can replace the oversized source. Do not hash partial content.",
    "fetch_failed": "Manual review: check whether the failure is transient. If repeated, look for a more stable public vendor-controlled source URL.",
    "quarantined": "Manual review: source or redirect failed URL-safety checks. Do not fetch or trust output until a safe public source URL is identified.",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    queue = data.get("human_review_queue", [])
    if not isinstance(queue, list):
        raise ValueError(f"{path}: human_review_queue must be a list")
    return data


def queue_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for item in report.get("human_review_queue", []):
        if not isinstance(item, dict):
            continue
        result = str(item.get("result"))
        if result not in HUMAN_REVIEW_RESULTS:
            continue
        items.append(
            {
                "vendor_id": item.get("vendor_id"),
                "source_id": item.get("source_id"),
                "result": result,
                "http_status": item.get("http_status"),
                "final_url": item.get("final_url"),
                "observed_at": item.get("observed_at"),
                "suggested_action": SUGGESTED_ACTIONS[result],
                "notes": item.get("notes"),
            }
        )
    return sorted(items, key=lambda entry: (str(entry.get("result")), str(entry.get("vendor_id")), str(entry.get("source_id"))))


def refinement_payload(report: dict[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    items = queue_items(report)
    counts = Counter(item["result"] for item in items)
    return {
        "schema_version": "0.1.0",
        "generated_at": generated_at or now_iso(),
        "observation_report_generated_at": report.get("generated_at"),
        "total_observed_sources": report.get("total_sources"),
        "human_review_required_count": len(items),
        "counts": dict(sorted(counts.items())),
        "items": items,
        "guarantees": {
            "does_not_mutate_catalog": True,
            "does_not_write_observations": True,
            "does_not_bypass_access_controls": True,
            "does_not_make_advisory_claims": True,
        },
    }


def markdown_row(values: list[Any]) -> str:
    return "| " + " | ".join("" if value is None else str(value).replace("|", "\\|") for value in values) + " |"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Source Refinement Queue",
        "",
        f"Generated: {payload['generated_at']}",
        f"Observation report generated: {payload.get('observation_report_generated_at') or '-'}",
        "",
        "This queue is operational metadata only. It is not legal, compliance, procurement, audit, security, KYC, AML, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        f"Total observed sources: {payload.get('total_observed_sources') or '-'}",
        f"Human review required: {payload['human_review_required_count']}",
        "",
        "| Result | Count |",
        "|---|---:|",
    ]
    for result, count in payload["counts"].items():
        lines.append(markdown_row([result, count]))

    lines.extend(["", "## Review queue", ""])
    if not payload["items"]:
        lines.append("No source-refinement items were produced.")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "| Vendor | Source | Result | HTTP | Final URL | Suggested action |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for item in payload["items"]:
        lines.append(
            markdown_row(
                [
                    item.get("vendor_id"),
                    item.get("source_id"),
                    item.get("result"),
                    item.get("http_status"),
                    item.get("final_url"),
                    item.get("suggested_action"),
                ]
            )
        )

    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- Do not bypass anti-bot controls, CAPTCHAs, login gates, customer portals, or access controls.",
            "- Do not write ambiguous observations by default.",
            "- Do not treat queue items as vendor risk, compliance, security, procurement, KYC, AML, or audit findings.",
            "- Use queue items only to decide whether a public source URL needs maintainer review or a source metadata PR.",
            "",
        ]
    )
    return "\n".join(lines)


def write_queue(report_path: Path, *, markdown_out: Path, json_out: Path) -> int:
    report = load_report(report_path)
    payload = refinement_payload(report)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text(render_markdown(payload), encoding="utf-8")
    json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {markdown_out}")
    print(f"Wrote {json_out}")
    print(f"Source refinement items: {payload['human_review_required_count']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-refinement-queue")
    parser.add_argument("observation_report_json", type=Path)
    parser.add_argument("--markdown-out", type=Path, default=Path("reports/source-refinement-queue.md"))
    parser.add_argument("--json-out", type=Path, default=Path("reports/source-refinement-queue.json"))
    args = parser.parse_args()
    return write_queue(args.observation_report_json, markdown_out=args.markdown_out, json_out=args.json_out)


if __name__ == "__main__":
    raise SystemExit(main())
