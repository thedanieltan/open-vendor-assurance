"""Fail-closed documentation-truth guard for architecture decision records.

WP-OPENVA-TRUTH-RECONCILIATION-01.

Architecture decision records name the work package they belong to. If that reference drifts
from the enforced scope manifest (a renamed or never-declared work package), the record misleads
anyone — especially a fork — trying to trace a decision back to the change that governs it. Two
of the three ADRs had already drifted (`WP-OPENVA-CAPABILITY-CONTRACT`,
`WP-OPENVA-RESOLVER-UNIFICATION`) before this guard existed.

`check` fails closed when any `docs/architecture/adr/ADR-*.md`:
  * has no `Work package: WP-...` line, or more than one; or
  * names a work package that is not declared in
    `docs/operations/contracts/work-package-scope.yaml`.

It intentionally does NOT require every work package to have an ADR — ADRs are written only for
decisions that warrant one — only that any ADR that cites a work package cites a real one.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "docs" / "architecture" / "adr"
SCOPE_MANIFEST = ROOT / "docs" / "operations" / "contracts" / "work-package-scope.yaml"

_WORK_PACKAGE_RE = re.compile(r"^Work package:\s*(WP-[A-Z0-9][A-Z0-9-]*?)\.?\s*$", re.MULTILINE)


def declared_work_packages() -> set[str]:
    manifest = yaml.safe_load(SCOPE_MANIFEST.read_text(encoding="utf-8"))
    return set((manifest.get("work_packages") or {}).keys())


def adr_paths() -> list[Path]:
    return sorted(ADR_DIR.glob("ADR-*.md"))


def _display(path: Path) -> Path | str:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path.name


def check() -> list[str]:
    problems: list[str] = []
    declared = declared_work_packages()
    for path in adr_paths():
        text = path.read_text(encoding="utf-8")
        matches = _WORK_PACKAGE_RE.findall(text)
        rel = _display(path)
        if len(matches) != 1:
            problems.append(
                f"{rel}: expected exactly one 'Work package: WP-...' line (found {len(matches)})"
            )
            continue
        work_package = matches[0]
        if work_package not in declared:
            problems.append(
                f"{rel}: references work package {work_package!r}, which is not declared in "
                f"{SCOPE_MANIFEST.relative_to(ROOT)}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenVA documentation-truth guard")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    parser.parse_args(argv)
    problems = check()
    if problems:
        print("Documentation truth FAILED:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print(f"Documentation truth: all {len(adr_paths())} ADR(s) cite a declared work package.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
