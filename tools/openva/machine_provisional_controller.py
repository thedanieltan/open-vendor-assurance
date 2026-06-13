"""WP36b not_before controller helper.

Decides whether an open machine-provisional materialization PR has passed its
not_before delay and may be cleared for the automerge lane. The candidate-
promotion controller calls `ready --ref <pr-head> --now <iso>` and applies the
automerge:machine-provisional label when this prints `true`.

Reading the decision record from the PR head (rather than trusting a label or
PR body) keeps the delay enforcement honest: the not_before timestamp lives in
the committed, append-only machine decision record.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from typing import Any, Callable

DECISION_DIR = "maintenance/machine-decisions"


def git_ls_tree(ref: str, path: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ref, path], text=True, encoding="utf-8"
    )
    return [line.strip() for line in out.splitlines() if line.strip().endswith(".ndjson")]


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True, encoding="utf-8")


def decisions_at_ref(
    ref: str,
    *,
    ls_tree: Callable[[str, str], list[str]] = git_ls_tree,
    show: Callable[[str, str], str] = git_show,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in ls_tree(ref, DECISION_DIR):
        for line in show(ref, path).splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def ready_for_automerge(decisions: list[dict[str, Any]], now: datetime) -> bool:
    """True iff there is at least one materialize_provisional decision and every
    such decision's not_before has passed."""
    materializations = [d for d in decisions if d.get("decision") == "materialize_provisional"]
    if not materializations:
        return False
    for decision in materializations:
        not_before = decision.get("not_before")
        if not not_before:
            return False
        try:
            not_before_dt = datetime.fromisoformat(str(not_before).replace("Z", "+00:00"))
        except ValueError:
            return False
        if now < not_before_dt:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-machine-provisional-controller")
    parser.add_argument("command", choices=["ready"])
    parser.add_argument("--ref", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    try:
        decisions = decisions_at_ref(args.ref)
    except subprocess.CalledProcessError:
        decisions = []
    print("true" if ready_for_automerge(decisions, now) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
