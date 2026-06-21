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
  maps each work package to its `allowed_paths` globs. There is no globally-exempt
  set: `shared_allowed` is empty, and the scope-policy machinery itself is just
  another work package (`WP-PR-SCOPE-POLICY-01`). Globs are `fnmatch` case-sensitive
  where `*` spans `/` (so `dir/*` matches everything beneath `dir/`).
- **Tool:** `tools/openva/pr_scope_guard.py`. The matching logic
  (`out_of_scope_paths`) is pure and unit-tested; the CLI wraps it with a `git diff`.
- **Declaration:** the **only** authoritative mechanism is a single
  `Work-Package: WP-...` line in the **PR body**. The PR title and labels are not
  consulted. Zero or multiple distinct declarations fail closed (exit 2).
- A path that matches **no** allowed glob for the declared work package is a
  violation. An **undeclared** work package fails closed (exit 2) — add its
  `allowed_paths` to the manifest before opening the PR.
- **Trusted-base evaluation:** CI loads the guard *and* the manifest from the trusted
  base revision (`main`), not from the PR's own tree. A PR therefore cannot weaken or
  widen the policy that judges its own diff.

## Usage

In CI the work package is derived from the PR body's `Work-Package: WP-...` line,
passed via `--declaration-file`:

```bash
python -m tools.openva.pr_scope_guard --declaration-file pr_body.txt --base origin/main
```

For local or test runs you can name the work package directly with `--work-package`
(this bypasses the body-line parsing and is not how CI runs):

```bash
python -m tools.openva.pr_scope_guard --work-package WP-OPENVA-AI-NATIVE-DISTRIBUTION-LEGAL-ENTITY --base origin/main
```

Exit codes: `0` in scope, `1` out-of-scope paths found, `2` unknown work package or a
malformed/absent declaration. For tests/CI you can pass explicit paths instead of
diffing: repeat `--changed-path`, or pass a list with `--changed-paths-file`.

## Adding or widening a work package (non-circular process)

Because CI evaluates the manifest from the trusted base revision, **a PR cannot extend
its own scope manifest and simultaneously pass under that extension** — the guard never
sees the PR's edited manifest. Scope changes are therefore a two-PR process:

1. Open a dedicated scope-policy PR declaring `Work-Package: WP-PR-SCOPE-POLICY-01`.
2. Add (or widen) the work package's entry in
   [`contracts/work-package-scope.yaml`](contracts/work-package-scope.yaml) in that PR.
   Keep scopes **disjoint** between unrelated work packages — that disjointness is what
   makes ancestor-bleed detectable.
3. Independently review and merge that policy PR. Once merged it is part of the trusted
   base.
4. Only **then** open the implementation PR, declaring the newly-accepted work package.
   Its changes are now judged against a manifest that already (at base) grants the scope.

`WP-PR-SCOPE-POLICY-01` is the only work package allowed to touch the scope-policy
files (this manifest, the guard, this doc, the guard's tests, and the CI workflow plus
its ownership map). No other work package can edit the policy that judges it.

## CI integration

The enforcement runs as the `pr-scope-guard` job in `.github/workflows/validate.yml`.
The job checks out the guard and manifest from the trusted base, derives the work
package from the PR body via `--declaration-file`, and fails the PR on any out-of-scope
path.

### Bootstrap (honest caveat)

On the PR that **first introduces** the guard, the base revision lacks both the guard
and the manifest, so the job self-bootstrap-skips. That skip is **not** proof the
diff would pass the future policy — it only means there was no policy at base to judge
it. After that PR merges, the guard and manifest are at base and every subsequent PR is
evaluated against them. In particular, the scope-policy files become permanently locked
to `WP-PR-SCOPE-POLICY-01`, so a bootstrap-style bundling cannot recur.
