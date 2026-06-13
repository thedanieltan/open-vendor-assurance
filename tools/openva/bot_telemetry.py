"""WP39 operational telemetry.

Operational COUNTS only, computed from committed state (the decision store, the
catalog, the observation ledger, and the reproducibility audit). It carries no
scores, rankings, recommendations, or vendor-risk signals — telemetry reports
what the machine quorum did, never a judgement about any vendor.

Surfaces: provisional / promoted / challenged / quarantined / rollback counts,
decisions-by-bot, separation-of-duty failures, deferred-or-rejected decisions,
and unresolved reproducibility defects.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.catalog_audit import audit_catalog
from tools.openva.indexes import ROOT
from tools.openva.machine_decisions import DEFAULT_DECISIONS_DIR, load_decisions, validate_committed

LEDGER_DIR = ROOT / "maintenance" / "source-observations" / "events"


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def latest_event_per_source(ledger_dir: Path) -> dict[str, dict[str, Any]]:
    from tools.openva.observation_ledger import load_ledger_baseline

    return load_ledger_baseline(ledger_dir)


def build_telemetry(
    root: Path = ROOT,
    decisions_dir: Path = DEFAULT_DECISIONS_DIR,
    ledger_dir: Path = LEDGER_DIR,
) -> dict[str, Any]:
    decisions = load_decisions(decisions_dir)
    by_decision = Counter(str(r.get("decision")) for r in decisions)
    by_bot = Counter(str(r.get("deciding_bot")) for r in decisions if r.get("deciding_bot"))

    provisional = promoted = 0
    for path in (root / "data" / "vendors").glob("*/vendor.yaml"):
        vendor = load_yaml(path)
        if vendor.get("catalog_status") == "machine_provisional":
            provisional += 1
        elif vendor.get("catalog_status") == "active" and vendor.get("machine_generated") is True:
            promoted += 1

    quarantined_sources = sum(
        1 for path in (root / "data" / "vendors").glob("*/sources/*.yaml")
        if load_yaml(path).get("review_state") == "quarantined"
    )

    # Open challenges: sources whose latest committed observation still flags review.
    challenged = sum(
        1 for event in latest_event_per_source(ledger_dir).values()
        if (event.get("review_signal") or {}).get("required") is True
    )

    sod_failures = sum(1 for reason in validate_committed(decisions_dir) if "separation_of_duty" in reason)
    audit = audit_catalog(root=root, decisions_dir=decisions_dir)

    return {
        "schema_version": "0.1.0",
        "report_type": "bot_operational_telemetry",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "non_advisory": True,
        "carries_scores_or_rankings": False,
        "counts": {
            "provisional_vendors": provisional,
            "promoted_vendors": promoted,
            "quarantined_sources": quarantined_sources,
            "open_challenged_sources": challenged,
            "rollback_decisions": by_decision.get("rollback", 0),
            "deferred_or_rejected_decisions": by_decision.get("defer", 0) + by_decision.get("reject", 0),
            "separation_of_duty_failures": sod_failures,
            "unresolved_reproducibility_defects": len(audit.findings),
            "decisions_total": len(decisions),
        },
        "decisions_by_type": dict(sorted(by_decision.items())),
        "decisions_by_deciding_bot": dict(sorted(by_bot.items())),
        "not_advice": True,
    }


def render_markdown(telemetry: dict[str, Any]) -> str:
    lines = [
        "## Bot Operational Telemetry",
        "",
        "Operational counts only; not legal, compliance, procurement, security, or vendor-risk advice. "
        "No scores, rankings, or recommendations.",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
    ]
    for key, value in telemetry["counts"].items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines += ["", "### Decisions by deciding bot", "", "| Bot | Decisions |", "| --- | ---: |"]
    for bot, count in telemetry["decisions_by_deciding_bot"].items():
        lines.append(f"| `{bot}` | {count} |")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-bot-telemetry")
    parser.add_argument("command", choices=["build"])
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args(argv)

    telemetry = build_telemetry(decisions_dir=args.decisions_dir)
    if args.out_json:
        args.out_json.write_text(json.dumps(telemetry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = render_markdown(telemetry)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
