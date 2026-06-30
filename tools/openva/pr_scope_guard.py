"""PR work-package scope guard.

Assert that every path a PR changes falls within its declared work package's allowed
globs, so an unrelated ancestor branch's commits cannot silently enter a PR via a
squash/rebase. This is the guard required by WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01
after PR #400 inherited the legal-entity commit and bundled it without independent
review of that change set.

The matching/manifest logic is pure (``out_of_scope_paths``) and unit-tested; the CLI
wraps it with a git diff. A PR declares its work package with exactly one
``Work-Package: WP-...`` line in its body; CI passes that body via
``--declaration-file`` (the only authoritative declaration mechanism — PR title and
labels are NOT used):

    python -m tools.openva.pr_scope_guard --declaration-file pr_body.txt --base origin/main

For local/test use a work package may be passed directly with ``--work-package``.

Globs use ``fnmatch`` case-sensitive semantics where ``*`` spans ``/`` (so ``dir/*``
matches everything beneath ``dir/``).
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "docs" / "operations" / "contracts" / "work-package-scope.yaml"

# The scope-policy machinery is governed SOLELY by this work package. Its exact
# allowed_paths are exclusive: no OTHER declared work package may change them, even if one
# of its broad globs (e.g. another package's `.github/workflows/*`, `docs/operations/*`,
# or `tools/openva/*`) would otherwise match. This keeps the policy that judges every PR
# un-editable under an unrelated declaration, without having to narrow every broad glob.
POLICY_WORK_PACKAGE = "WP-PR-SCOPE-POLICY-01"

# A PR declares its work package with a single `Work-Package: WP-...` line in its body.
_DECLARATION_RE = re.compile(r"^\s*Work-Package:\s*(WP-[A-Z0-9][A-Z0-9-]*)\s*$", re.MULTILINE)


class DeclarationError(ValueError):
    """The PR did not declare exactly one work package."""


def declared_work_package(text: str) -> str:
    """Parse exactly one `Work-Package: WP-...` declaration from a PR body.

    Fails closed: zero or multiple distinct declarations raise DeclarationError, so a PR
    can neither skip the guard (no declaration) nor straddle work packages (several)."""
    found: list[str] = []
    for match in _DECLARATION_RE.finditer(text or ""):
        if match.group(1) not in found:
            found.append(match.group(1))
    if len(found) != 1:
        raise DeclarationError(
            f"a PR must declare exactly one 'Work-Package: WP-...' line (found {len(found)}: {found})"
        )
    return found[0]


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def allowed_globs(manifest: dict[str, Any], work_package: str) -> list[str]:
    """Allowed globs for a work package = the shared set + that package's allowed_paths.

    Raises KeyError if the work package is not declared in the manifest (an undeclared
    package must declare its scope before the guard will pass)."""
    work_packages = manifest.get("work_packages") or {}
    if work_package not in work_packages:
        raise KeyError(work_package)
    shared = list(manifest.get("shared_allowed") or [])
    declared = list((work_packages[work_package] or {}).get("allowed_paths") or [])
    return shared + declared


def policy_exclusive_paths(manifest: dict[str, Any]) -> set[str]:
    """Exact paths reserved to POLICY_WORK_PACKAGE (the scope-policy machinery).

    Returns an empty set if that work package is absent (e.g. in unit-test fixtures), so
    the exclusivity rule only bites when the real scope-policy package is present."""
    work_packages = manifest.get("work_packages") or {}
    policy = work_packages.get(POLICY_WORK_PACKAGE) or {}
    return set(policy.get("allowed_paths") or [])


def out_of_scope_paths(changed_paths: list[str], work_package: str, manifest: dict[str, Any]) -> list[str]:
    """Paths a work package may not change (sorted, deterministic).

    A path is allowed (in scope) if, in order:
      1. it is listed EXACTLY in the work package's allowed globs — a deliberate, reviewed
         grant, e.g. the reconciliation lane's explicit `work-package-scope.yaml`; else
      2. it is a scope-policy file and the declared package is not POLICY_WORK_PACKAGE —
         then it is OUT of scope: a broad glob (another package's `.github/workflows/*`,
         `docs/operations/*`, `tools/openva/*`, ...) must not reach the policy that judges
         the PR; else
      3. it matches one of the work package's allowed globs.

    Only step 2 is new behaviour; an exact grant (step 1) still wins, so documented
    carve-outs are preserved while glob-reach into the scope-policy machinery is blocked."""
    globs = allowed_globs(manifest, work_package)
    explicit = set(globs)
    exclusive = set() if work_package == POLICY_WORK_PACKAGE else policy_exclusive_paths(manifest)

    def allowed(path: str) -> bool:
        if path in explicit:
            return True
        if path in exclusive:
            return False
        return any(fnmatch.fnmatchcase(path, glob) for glob in globs)

    return sorted(path for path in changed_paths if not allowed(path))


def scope_policy_operational_freshness_exemption(
    changed_paths: list[str],
    work_package: str,
    manifest: dict[str, Any],
) -> bool:
    """Return true only for a pure, valid scope-policy control-plane PR.

    This is intentionally narrower than the scope guard itself. It exists only to avoid a
    trusted-base deadlock where the scope-policy PR cannot land because unrelated
    operational source freshness is stale. The PR must still be a valid
    WP-PR-SCOPE-POLICY-01 change, and every changed path must be one of the exclusive
    scope-policy files.
    """
    if work_package != POLICY_WORK_PACKAGE:
        return False
    changed = [path for path in changed_paths if path]
    if not changed:
        return False
    if out_of_scope_paths(changed, work_package, manifest):
        return False
    exclusive = policy_exclusive_paths(manifest)
    return set(changed).issubset(exclusive)


def changed_paths_from_git(base: str = "origin/main") -> list[str]:
    merge_base = subprocess.run(
        ["git", "merge-base", base, "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--name-only", merge_base, "HEAD"], capture_output=True, text=True, check=True
    ).stdout
    return [line.strip() for line in diff.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pr_scope_guard",
        description="Assert a PR's changed paths stay within its declared work-package scope.",
    )
    parser.add_argument("--work-package", help="The declared work-package id (must exist in the manifest).")
    parser.add_argument(
        "--declaration-file",
        help="Path to a file (the PR body) carrying a single 'Work-Package: WP-...' line; "
        "fails closed on zero or multiple declarations. This is how CI derives the work package.",
    )
    parser.add_argument("--base", default="origin/main", help="Base ref to diff against (default: origin/main).")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Path to the work-package-scope manifest.")
    parser.add_argument(
        "--changed-path",
        action="append",
        default=None,
        help="Explicit changed path (repeatable); overrides the git diff (for testing/CI).",
    )
    parser.add_argument(
        "--changed-paths-file",
        help="Path to a newline-separated list of changed paths; overrides the git diff (for CI).",
    )
    parser.add_argument(
        "--check-policy-only-operational-freshness-exemption",
        action="store_true",
        help=(
            "Exit 0 only when the declaration and changed paths qualify for the narrow "
            "scope-policy operational freshness exclusion."
        ),
    )
    args = parser.parse_args(argv)

    if args.declaration_file:
        try:
            work_package = declared_work_package(Path(args.declaration_file).read_text(encoding="utf-8"))
        except DeclarationError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    elif args.work_package:
        work_package = args.work_package
    else:
        print("provide --work-package or --declaration-file", file=sys.stderr)
        return 2

    manifest = load_manifest(args.manifest)
    if args.changed_paths_file is not None:
        changed = [line.strip() for line in Path(args.changed_paths_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    elif args.changed_path is not None:
        changed = args.changed_path
    else:
        changed = changed_paths_from_git(args.base)
    try:
        if args.check_policy_only_operational_freshness_exemption:
            return 0 if scope_policy_operational_freshness_exemption(changed, work_package, manifest) else 1
        violations = out_of_scope_paths(changed, work_package, manifest)
    except KeyError:
        print(
            f"unknown work package {work_package!r}: declare its allowed_paths in {args.manifest} "
            "before opening the PR",
            file=sys.stderr,
        )
        return 2

    if violations:
        print(
            f"{len(violations)} changed path(s) outside the declared scope of {work_package}:",
            file=sys.stderr,
        )
        for path in violations:
            print(f"  - {path}", file=sys.stderr)
        print(
            "If these belong to another work package, split them into their own PR -- do not let an "
            "ancestor branch's commits bleed in (see PR #400).",
            file=sys.stderr,
        )
        return 1

    print(f"all {len(changed)} changed path(s) within scope of {work_package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
