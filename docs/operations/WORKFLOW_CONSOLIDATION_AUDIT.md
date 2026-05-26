# Workflow Consolidation Audit

This audit classifies every public workflow in `.github/workflows/` and identifies consolidation work that should happen without creating workflow sprawl.

Classification values:

- `keep_core`: durable operating-loop workflow.
- `keep_support`: useful controlled support workflow outside a core loop.
- `edit_existing`: keep the workflow but simplify or clarify it in place.
- `retire_candidate`: likely redundant, but do not delete until consumers and artifacts are proven replaced.
- `remove_now_if_safe`: safe to delete only after tests and stale references prove removal.
- `defer`: known future need, not part of this package.

No workflow is removed by this audit. Risky retirements require a migration note and CI-readiness tests before deletion.

## Classification table

| Workflow | Classification | Rationale | Recommended action |
|---|---|---|---|
| `validate.yml` | `keep_core` | PR safety baseline for validation, index generation, generated drift, and tests. | Keep. |
| `catalog-pr-guard.yml` | `keep_core` | Catalog PR scope guard. | Keep. |
| `agent-weighted-review.yml` | `keep_core` | Advisory review agents add reviewer signal without merging or mutating catalog files. | Keep. |
| `agent-automerge.yml` | `keep_core` | Controlled automerge lane with preflight and validation before merge. | Keep without policy relaxation. |
| `source-maintenance-report.yml` | `edit_existing` | Source cleanup/reporting entry point. It keeps the full operator artifact and exposes a one-file reviewer inbox. | Keep in place. Maintain reviewer/operator artifact separation. |
| `source-refinement-scan.yml` | `keep_core` | Confirms P0 source repair candidates from repeated source maintenance evidence. | Keep. |
| `source-repair-pr.yml` | `keep_core` | Manual, reviewed, validated source repair PR creation path. | Keep manual and reviewed-only. |
| `source-repair-pr-cleanup.yml` | `keep_core` | Cleans up stale generated source repair PRs. | Keep. |
| `coverage-audit.yml` | `keep_core` | Catalog quality entry point for completeness, entity correctness, and provenance. | Keep. |
| `catalog-growth-discovery.yml` | `keep_core` | Catalog expansion proposal entry point. | Keep as report/proposal path only. |
| `candidate-promotion-pr.yml` | `keep_core` | Controlled write path for reviewed promotions. | Keep. |
| `release-candidate.yml` | `keep_core` | Release readiness consumer of source-health artifacts. | Keep; do not make it a catalog truth generator. |
| `site-pages.yml` | `keep_core` | Site publication consumer of source-health and catalog-confidence artifacts. | Keep; do not make it a catalog truth generator. |
| `release-downloads.yml` | `keep_core` | Release download publishing for tags. | Keep. |
| `site-live-feed.yml` | `keep_core` | Controlled live feed publication path. | Keep. |
| `catalog-agent-pr.yml` | `keep_support` | Manual support path for agent-authored catalog PRs. | Keep as PR-only support path. |
| `catalog-maintenance-pr.yml` | `keep_support` | Scheduled/manual support path for maintenance PRs. | Keep until overlap with promotion and repair paths is further reduced. |
| `contribution-intake-agent.yml` | `keep_support` | Issue-to-PR intake support path. | Keep. |
| `catalog-maintenance.yml` | `retire_candidate` | Overlaps with validation/index/test work in `validate.yml` and catalog quality/entity reporting in `coverage-audit.yml`. | Retire after confirming entity stub reporting is either no longer needed or folded into `coverage-audit.yml`. |
| `source-refinement-queue.yml` | `retire_candidate` | Consumes older observation report paths and likely overlaps with `source-maintenance-report.yml`, source repair sweep output, source review triage, and reviewer decision sheet. | Retire only if no unique queue remains. Likely future `remove_now_if_safe` candidate after consumer search and stale-reference tests. |
| `observe-report.yml` | `retire_candidate` | May be superseded for source observations by `source-observation-ledger`, `latest-source-health`, and `public/source-health-snapshot`. | Keep only if it tracks non-source observations still needed by the project; otherwise mark legacy or retire. |

## Retire/consolidation candidate detail

### `catalog-maintenance.yml`

Observed overlap:

- Validation/index/test behavior overlaps with `validate.yml`.
- Catalog quality and entity reporting overlap with `coverage-audit.yml`.

Recommended action:

Retire after confirming entity stub reporting is either no longer needed or folded into `coverage-audit.yml`. Do not delete until docs and tests prove that no current operator sequence points to it as an authoritative workflow.

### `source-refinement-queue.yml`

Observed overlap:

- It consumes an older observation report path.
- It likely overlaps with `source-maintenance-report.yml`, source repair sweep artifacts, source review triage output, and the reviewer decision sheet.

Recommended action:

Retire if no unique queue remains. This is the likely first removal candidate, but not in this package unless tests prove its outputs are fully replaced and no stale references remain.

### `observe-report.yml`

Observed overlap:

- Source-specific observation needs are increasingly represented by `source-observation-ledger.json`, `latest-source-health.json`, and `public/source-health-snapshot.json`.

Recommended action:

Keep only if it tracks non-source observations still needed by the project. If not, mark legacy and retire after consumers are migrated.

## Future actions not implemented here

### Future Action A: reviewed decision validation handoff

Purpose: after a reviewer returns `source-review-decision-sheet.csv`, run validation manually or through an existing controlled path.

Current status: handoff hardening is documented. The controlled path is `source_review_decisions validate-sheet` followed by `source_review_decisions export-reviewed-artifacts` only when validation has zero invalid rows. Reviewed artifacts must be committed under `maintenance/reviewed/` before `source-repair-pr.yml` is run.

Do not add a scheduled workflow for this path. Do not automatically mutate catalog records from reviewer sheets. Do not run `source-repair-pr.yml` from uncommitted reviewer input.

### Future Action B: reviewed no-replacement truth-state application

Purpose: define whether no-replacement decisions live under `maintenance/reviewed/` or in a first-class unavailable-source catalog structure.

Do not implement until the truth-state schema is decided.

### Future Action C: workflow retirement

Purpose: retire `catalog-maintenance.yml`, `source-refinement-queue.yml`, and/or `observe-report.yml` only after the audit proves their outputs are fully replaced.

Do not delete all three in one package unless tests and docs prove no consumers remain.

### Future Action D: source operations scheduler

Purpose: at catalog scale, add sharded or incremental source checking.

Do not implement now.

### Future Action E: catalog growth gating dashboard

Purpose: show when Lane B promotion is allowed based on source-health debt.

Do not implement now.

## Removal criteria

A workflow may be removed only when all of the following are true:

1. It is classified as `remove_now_if_safe`.
2. No CI-readiness test depends on it except an updated allowlist.
3. No docs point to it as a current workflow.
4. Its artifacts are already produced by a current core workflow.
5. Tests are updated to confirm absence, replacement documentation, and no stale references.
6. This audit explains the removal.

Current result: no workflow is classified as `remove_now_if_safe` in this package.
