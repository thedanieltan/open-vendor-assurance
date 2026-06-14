"""WP40C global work priority.

Deterministic ordering for when several lanes are eligible at once, plus a
capacity guard that reserves room for integrity and maintenance work
(rollback, quarantine, repair) so catalog growth can never starve them.

The ordering and reservations live in the machine-readable contract
``docs/operations/contracts/bot-work-priority.yaml``; this module only reads and
applies them. When resources are constrained, integrity and maintenance take
priority over growth.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT

CONTRACT_PATH = ROOT / "docs" / "operations" / "contracts" / "bot-work-priority.yaml"


@lru_cache(maxsize=8)
def load_contract(path: str = str(CONTRACT_PATH)) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def priority_order(contract: dict[str, Any] | None = None) -> list[str]:
    contract = contract or load_contract()
    rows = sorted(contract.get("priority", []), key=lambda r: r.get("rank", 999))
    return [str(r["work_class"]) for r in rows]


def rank(work_class: str, contract: dict[str, Any] | None = None) -> int:
    contract = contract or load_contract()
    for row in contract.get("priority", []):
        if str(row.get("work_class")) == work_class:
            return int(row.get("rank", 999))
    raise KeyError(f"unknown work_class: {work_class}")


def order_eligible(eligible: list[str], contract: dict[str, Any] | None = None) -> list[str]:
    """Return eligible work classes sorted by priority (highest first)."""
    contract = contract or load_contract()
    return sorted(dict.fromkeys(eligible), key=lambda wc: rank(wc, contract))


def select_next(eligible: list[str], contract: dict[str, Any] | None = None) -> str | None:
    """The single highest-priority eligible work class."""
    ordered = order_eligible(eligible, contract)
    return ordered[0] if ordered else None


def reserved_classes(contract: dict[str, Any] | None = None) -> list[str]:
    contract = contract or load_contract()
    return [str(c) for c in contract.get("reserved_for_integrity", [])]


def yields_to_reserved(work_class: str, contract: dict[str, Any] | None = None) -> bool:
    contract = contract or load_contract()
    return work_class in {str(c) for c in contract.get("yields_to_reserved_capacity", [])}


def lane_work_class(lane_id: str, contract: dict[str, Any] | None = None) -> str | None:
    contract = contract or load_contract()
    mapping = contract.get("lane_to_work_class", {})
    value = mapping.get(lane_id)
    return str(value) if value else None


def capacity_decision(
    work_class: str,
    *,
    total_pr_budget: int,
    open_prs_total: int,
    pending_integrity_work: bool,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide whether a work class may start given reserved integrity capacity.

    Growth/discovery (classes that ``yields_to_reserved_capacity``) defer when
    the only remaining budget is the slot reserved for pending integrity work.
    Integrity/maintenance classes themselves are never blocked by the reserve.
    """
    contract = contract or load_contract()
    free = total_pr_budget - open_prs_total
    if free <= 0:
        return {"decision": "defer", "reason": "no_free_pr_budget", "free": free}
    if yields_to_reserved(work_class, contract) and pending_integrity_work and free <= 1:
        return {
            "decision": "defer",
            "reason": "reserved_capacity_held_for_integrity_work",
            "free": free,
        }
    return {"decision": "allow", "reason": "capacity_available", "free": free}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-work-priority")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("order", help="print the global priority order")
    nxt = sub.add_parser("select", help="select the highest-priority eligible class")
    nxt.add_argument("eligible", nargs="+")
    args = parser.parse_args(argv)

    if args.command == "order":
        print(json.dumps(priority_order(), indent=2))
        return 0
    if args.command == "select":
        print(json.dumps({"next": select_next(args.eligible), "order": order_eligible(args.eligible)}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
