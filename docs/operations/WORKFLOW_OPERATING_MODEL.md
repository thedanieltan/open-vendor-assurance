# Workflow Operating Model

OpenVA workflows are organized as operating loops, not as a flat list of automation. The goal is to keep source cleanup, catalog growth, release readiness, and publication understandable as the catalog scales.

This document is the canonical map for current GitHub Actions workflows. It does not authorize catalog mutation, source URL replacement, automerge policy changes, or release-gate relaxation.

## Three-lane operating stance

### Lane A: Source debt cleanup

Source cleanup is a versioning gate. The lane exists to eliminate source debt or truth-state it before release confidence is claimed.

Lane A starts with `source-maintenance-report.yml`, routes reviewer work through triage and reviewed decision artifacts, uses `source-repair-pr.yml` only for committed and validated reviewed repairs, and then re-runs source maintenance before release readiness is evaluated.

### Lane B: Catalog growth discovery and controlled promotion

Catalog discovery is a proposal pipeline. Discovery may identify candidate vendors and sources, but catalog writes happen only through controlled promotion.

Lane B starts with `catalog-growth-discovery.yml`. Reviewed and approved plans are copied into `maintenance/reviewed/`, then applied through `candidate-promotion-pr.yml`. Candidate promotion creates reviewable PRs and remains subject to the PR safety loop.

### Lane C: Workflow loop refinement

Workflow refinement exists to make the operating system understandable and scalable. Lane C should consolidate, document, and simplify existing workflows rather than add more workflow sprawl.

## Durable operating loops

### Loop 1: PR safety loop

Purpose: protect `main`.

Workflows:

- `validate.yml`
- `catalog-pr-guard.yml`
- `agent-weighted-review.yml`
- `agent-automerge.yml`

### Loop 2: Source cleanup loop

Purpose: eliminate or truth-state source debt.

Workflows:

- `source-maintenance-report.yml`
- `source-refinement-scan.yml`
- `source-repair-pr.yml`
- `source-repair-pr-cleanup.yml`

`source-maintenance-report.yml` is the source cleanup and reporting entry point.

### Loop 3: Catalog quality loop

Purpose: measure completeness, entity correctness, and provenance.

Workflow:

- `coverage-audit.yml`

`coverage-audit.yml` is the catalog quality entry point.

### Loop 4: Catalog growth loop

Purpose: discover and propose catalog expansion, then apply only reviewed promotions.

Workflows:

- `catalog-growth-discovery.yml`
- `candidate-promotion-pr.yml`

`catalog-growth-discovery.yml` is the catalog expansion proposal entry point. `candidate-promotion-pr.yml` is the controlled write path for reviewed promotions.

### Loop 5: Release/site loop

Purpose: publish only with source-health and catalog-confidence awareness.

Workflows:

- `release-candidate.yml`
- `site-pages.yml`
- `release-downloads.yml`
- `site-live-feed.yml`

`release-candidate.yml` and `site-pages.yml` consume artifacts. They must not become catalog truth generators.

### Loop 6: Bot operations visibility loop

Purpose: make bot operating posture visible without strengthening bot authority.

Workflow:

- `bot-dashboard-issue.yml`

`bot-dashboard-issue.yml` renders the local bot dashboard and runs dashboard issue sync. It defaults to dry-run/report-only behavior. Scheduled runs must not create or update issues, mutate catalog data, mutate PRs, dispatch workflows, or change automerge state.

## Reviewed decision handoff boundary

Reviewer decision handling is a controlled evidence handoff inside Lane A. It is not a workflow by itself and must not become a scheduled mutation path.

The boundary is:

```text
source-maintenance-report.yml
→ openva-source-reviewer-inbox / source-review-decision-sheet.csv
→ matching source-review-triage-plan.json from openva-source-maintenance-report
→ source_review_decisions validate-sheet
→ zero invalid rows only
→ source_review_decisions export-reviewed-artifacts
→ reviewed-artifacts PR under maintenance/reviewed/
→ CI passes
→ source-repair-pr.yml may be run manually from committed reviewed repair evidence
```

The reviewer sheet is untrusted input. `validate-sheet` is report-only. `export-reviewed-artifacts` writes reviewed evidence only. `source-repair-pr.yml` is the later controlled write path and must not run from an uncommitted reviewer sheet.

## Operator sequence

### Lane A sequence

1. Run `source-maintenance-report.yml`.
2. Send reviewers the `openva-source-reviewer-inbox` artifact.
3. Keep the matching `source-review-triage-plan.json` from the same run's `openva-source-maintenance-report` artifact.
4. Validate returned reviewed decisions with `source_review_decisions validate-sheet` against the matching triage plan.
5. Stop if validation reports any invalid rows.
6. Export reviewed artifacts only after validation has zero invalid rows.
7. Commit reviewed artifacts under `maintenance/reviewed/` in a reviewed-artifacts PR.
8. Wait for CI to pass on the reviewed-artifacts PR.
9. Run `source-repair-pr.yml` only for committed and validated reviewed repair artifacts.
10. Run `source-maintenance-report.yml` again.
11. Run `release-candidate.yml`.

### Lane B sequence

1. Run `catalog-growth-discovery.yml`.
2. Review generated plans.
3. Copy the approved plan to `maintenance/reviewed/`.
4. Run `candidate-promotion-pr.yml`.
5. Let the PR safety loop run.
6. Continue into the site/release loop after approval and merge.

### Lane C sequence

1. Maintain this workflow operating model.
2. Maintain the consolidation audit.
3. Apply small workflow simplifications.
4. Update CI-readiness tests when the intended public workflow surface changes.

## Workflow inventory

| Workflow | Purpose | Trigger | Permissions | Writes repository state? | Creates PRs? | Merges PRs? | Primary artifacts | Downstream consumers | Status |
|---|---|---|---|---:|---:|---:|---|---|---|
| `validate.yml` | Validate records, generated pack/indexes, and tests. | `pull_request`, `push` to `main` | `contents: read` | No | No | No | Validation logs | PR safety loop, branch protection | Core |
| `catalog-pr-guard.yml` | Enforce catalog PR scope and title expectations. | `pull_request` | `contents: read`, `pull-requests: read` | No | No | No | Guard logs | PR safety loop | Core |
| `agent-weighted-review.yml` | Advisory agent checks for schema, source accessibility, wording, and provenance. | `pull_request` | `contents: read`, `pull-requests: read`, `issues: write` | No catalog writes; comments only | No | No | Advisory comments | PR reviewers, automerge policy context | Core |
| `agent-automerge.yml` | Controlled automerge lanes for approved agent PRs. | `pull_request` | `contents: write`, `pull-requests: write`, `checks: read`, `statuses: read` | Yes, through merge only | No | Yes | Preflight artifact, merge result | `main`, release/site loop | Core |
| `source-maintenance-report.yml` | Source cleanup/reporting entry point. Builds source health, verification, discovery, repair sweep, triage, decision sheet, promotion, and cleanup reports. | `workflow_dispatch`, scheduled weekly | `contents: read` | No | No | No | `openva-source-maintenance-report`, `openva-source-reviewer-inbox` | Source cleanup loop, release candidate, site pages, reviewers | Core |
| `source-refinement-scan.yml` | Compare recent source maintenance runs and identify confirmed P0 repair candidates. | `workflow_dispatch`, scheduled weekly | `actions: read`, `contents: read` | No | No | No | Confirmed P0 scan and evidence artifacts | `source-repair-pr.yml`, release readiness | Core |
| `source-repair-pr.yml` | Create repair PRs from committed and validated reviewed evidence and repair plans. | `workflow_dispatch` | `contents: write`, `pull-requests: write` | Yes, in PR branch | Yes | No | Repair action report, PR body | PR safety loop, source maintenance re-run | Core |
| `source-repair-pr-cleanup.yml` | Close stale generated source repair PRs. | `workflow_dispatch`, scheduled weekly | `contents: read`, `pull-requests: write`, `issues: write` | PR state only | No | No | Stale PR cleanup report | Operators | Core |
| `coverage-audit.yml` | Catalog quality entry point for completeness, entity review, and provenance coverage. | `workflow_dispatch`, scheduled | `contents: read` | No | No | No | Coverage, completeness, entity, and provenance reports | Site pages, operators | Core |
| `catalog-growth-discovery.yml` | Catalog expansion proposal entry point. Discovers candidate vendors and sources without writing catalog truth. | `workflow_dispatch`, scheduled | `contents: read`, `issues: write` | No catalog writes; may create/update issues | No | No | Candidate discovery reports and proposal plans | Reviewers, candidate promotion | Core |
| `candidate-promotion-pr.yml` | Controlled write path for reviewed catalog growth promotions. | `workflow_dispatch`, scheduled | `contents: write`, `pull-requests: write` | Yes, in PR branch | Yes | No | Promotion application report and PR | PR safety loop, site/release loop | Core |
| `release-candidate.yml` | Build release candidate with source-health readiness awareness. | `workflow_dispatch` | `contents: read`, `actions: read` | No | No | No | Release artifacts, source-health readiness report | Release operators | Core |
| `site-pages.yml` | Build and deploy the reviewed catalog site with downloaded source-health and catalog-confidence artifacts. | `push` to `main`, `workflow_dispatch` | `contents: read`, `actions: read`, `pages: write`, `id-token: write` | Pages deployment only | No | No | Pages artifact | Public site | Core |
| `release-downloads.yml` | Publish release downloads for version tags. | tag `push` | `contents: write` | GitHub release assets only | No | No | Release download assets | Release consumers | Core |
| `site-live-feed.yml` | Refresh live site feed on a controlled cadence. | `workflow_dispatch`, scheduled weekly | `contents: read`, `pages: write`, `id-token: write` | Pages deployment only | No | No | Live feed deployment artifact | Public site | Core |
| `bot-dashboard-issue.yml` | Render the bot dashboard and run dashboard issue sync in dry-run/report-only mode by default. | `workflow_dispatch`, scheduled weekly | `contents: read`, `issues: write` | Issue update only when manually requested with explicit input; scheduled runs are dry-run/report-only | No | No | Bot dashboard and issue-sync report | Maintainers | Core |
| `catalog-agent-pr.yml` | Manual support path for agent-authored catalog PRs. | `workflow_dispatch` | `contents: write`, `pull-requests: write` | Yes, in PR branch | Yes | No | PR branch and PR body | PR safety loop | Support |
| `catalog-maintenance-pr.yml` | Support path for scheduled/manual catalog maintenance PRs. | `workflow_dispatch`, scheduled | `contents: write`, `pull-requests: write` | Yes, in PR branch | Yes | No | Maintenance PR artifacts | PR safety loop | Support |
| `contribution-intake-agent.yml` | Convert issue-based contribution intake into controlled PRs. | `issues`, `workflow_dispatch` | `contents: write`, `pull-requests: write`, `issues: write` | Yes, in PR branch | Yes | No | Intake PR artifacts | PR safety loop | Support |
| `catalog-maintenance.yml` | Legacy catalog maintenance report for validation, index rebuild, drift check, tests, and entity stub reporting. | `workflow_dispatch`, scheduled weekly (`17 2 * * 1`) | `contents: read`, `actions: read` | No | No | No | `catalog-maintenance-report` | Operators | Consolidation candidate |
| `source-refinement-queue.yml` | Legacy source refinement queue generated from an observation report path. | `workflow_dispatch` only | `contents: read` | No | No | No | `openva-source-refinement-queue` | Operators | Consolidation candidate |
| `observe-report.yml` | Observation report path for full public-source observation dry-run output and review queue export. | `workflow_dispatch`, scheduled weekly (`0 2 * * 1`) | `contents: read` | No | No | No | `openva-observation-report` | Operators | Consolidation candidate |

## Reviewer versus operator artifacts

`source-maintenance-report.yml` emits two distinct artifacts:

- `openva-source-maintenance-report`: full operator and machine artifact package.
- `openva-source-reviewer-inbox`: reviewer-only inbox containing exactly `source-review-decision-sheet.csv`.

Reviewers should download the reviewer inbox. Operators and agents should use the full source maintenance report.
