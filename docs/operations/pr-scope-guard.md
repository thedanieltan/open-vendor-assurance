# PR work-package scope guard

A guard that compares a PR's changed paths against its **declared work package's**
allowed paths, so an unrelated ancestor branch's commits cannot silently enter a PR.

## Why

PR #400 (candidate-activation) was branched on top of an in-flight legal-entity
commit (`26b2922`). Its squash merge therefore bundled the legal-entity export +
matching change set into the candidate-activation work package, where it landed on
`main` without independent review of *that* change set. The fix for the symptom was
[the legal-entity ratification](legal-entity-export-ratification.md); this guard
addresses the *mechanism* so it cannot recur silently.

## How it works

- **Manifest:** [`contracts/work-package-scope.yaml`](contracts/work-package-scope.yaml)
  maps each work package to its `allowed_paths` globs, plus a `shared_allowed` set any
  PR may touch. Globs are `fnmatch` case-sensitive where `*` spans `/` (so `dir/*`
  matches everything beneath `dir/`).
- **Tool:** `tools/openva/pr_scope_guard.py`. The matching logic
  (`out_of_scope_paths`) is pure and unit-tested; the CLI wraps it with a `git diff`.
- A path that matches **no** allowed glob for the declared work package is a
  violation. An **undeclared** work package fails closed (exit 2) — add its
  `allowed_paths` to the manifest before opening the PR.

## Usage

The PR declares its work package (e.g. from the PR title or a label); CI passes it:

```bash
python -m tools.openva.pr_scope_guard --work-package WP-OPENVA-AI-NATIVE-DISTRIBUTION-LEGAL-ENTITY --base origin/main
```

Exit codes: `0` in scope, `1` out-of-scope paths found, `2` unknown work package.
For tests/CI you can pass explicit paths instead of diffing: repeat `--changed-path`.

## Adding a work package

Add an entry under `work_packages:` in the manifest with a one-line `description` and
the `allowed_paths` globs the work package may touch. Keep scopes **disjoint** between
unrelated work packages — that disjointness is what makes ancestor-bleed detectable.

## CI integration

Run the CLI as a required check on pull requests, passing the PR's declared work
package. Because the guard fails closed on an undeclared work package, every core-lane
PR must name its work package and keep its changes within that scope (or extend the
manifest in the same PR when the scope legitimately grows).
