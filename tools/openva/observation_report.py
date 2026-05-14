from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

AMBIGUOUS_RESULTS = {"bot_protected", "size_limited", "fetch_failed", "quarantined"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_observations(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if "\n---\n" in text:
        text = text.split("\n---\n", 1)[1]
    data = yaml.safe_load(text) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a YAML list of observations")
    observations: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: each observation must be a mapping")
        observations.append(item)
    return observations


def human_review_queue(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue = []
    for observation in observations:
        if observation.get("result") in AMBIGUOUS_RESULTS:
            queue.append(
                {
                    "vendor_id": observation.get("vendor_id"),
                    "source_id": observation.get("source_id"),
                    "result": observation.get("result"),
                    "http_status": observation.get("http_status"),
                    "final_url": observation.get("final_url"),
                    "observed_at": observation.get("observed_at"),
                    "notes": observation.get("notes"),
                }
            )
    return sorted(queue, key=lambda item: (str(item.get("vendor_id")), str(item.get("source_id"))))


def report_payload(observations: list[dict[str, Any]], *, generated_at: str | None = None) -> dict[str, Any]:
    counts = Counter(str(observation.get("result")) for observation in observations)
    queue = human_review_queue(observations)
    return {
        "schema_version": "0.1.0",
        "generated_at": generated_at or now_iso(),
        "total_sources": len(observations),
        "counts": dict(sorted(counts.items())),
        "human_review_required_count": len(queue),
        "human_review_queue": queue,
    }


def markdown_table_row(values: list[Any]) -> str:
    return "| " + " | ".join("" if value is None else str(value).replace("|", "\\|") for value in values) + " |"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Observation Report",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "This report is produced from public-source observation dry-run output. It is operational metadata only and is not legal, compliance, procurement, audit, security, KYC, AML, or vendor-risk advice.",
        "",
        "## Summary",
        "",
        "| Result | Count |",
        "|---|---:|",
    ]
    for result, count in payload["counts"].items():
        lines.append(markdown_table_row([result, count]))

    lines.extend(
        [
            "",
            f"Total sources observed: {payload['total_sources']}",
            f"Human review required: {payload['human_review_required_count']}",
            "",
            "## Human review queue",
            "",
        ]
    )

    queue = payload["human_review_queue"]
    if not queue:
        lines.append("No ambiguous observation results were reported.")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "| Vendor | Source | Result | HTTP | Final URL | Observed at |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for item in queue:
        lines.append(
            markdown_table_row(
                [
                    item.get("vendor_id"),
                    item.get("source_id"),
                    item.get("result"),
                    item.get("http_status"),
                    item.get("final_url"),
                    item.get("observed_at"),
                ]
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(observations_path: Path, *, markdown_out: Path, json_out: Path) -> int:
    observations = load_observations(observations_path)
    payload = report_payload(observations)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text(render_markdown(payload), encoding="utf-8")
    json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {markdown_out}")
    print(f"Wrote {json_out}")
    print(f"Human review required: {payload['human_review_required_count']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-observation-report")
    parser.add_argument("observations", type=Path, help="YAML output from observe --dry-run --emit-yaml")
    parser.add_argument("--markdown-out", type=Path, default=Path("reports/observation-report.md"))
    parser.add_argument("--json-out", type=Path, default=Path("reports/observation-report.json"))
    args = parser.parse_args()
    return write_report(args.observations, markdown_out=args.markdown_out, json_out=args.json_out)


if __name__ == "__main__":
    raise SystemExit(main())
