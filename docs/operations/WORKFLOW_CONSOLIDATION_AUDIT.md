# Workflow Consolidation Audit

This audit classifies every public workflow in `.github/workflows/` and identifies consolidation work that should happen without creating workflow sprawl.

Classification values:

- `keep_core`: durable operating-loop workflow.
- `keep_support`: useful controlled support workflow outside a core loop.
- `edit_existing`: keep the workflow but simplify or clarify it in place.
- `retire_candidate`: likely redundant, but do not delete until consumers and artifacts are proven replaced.
- `remove_now_if_safe`: safe to delete only after tests and stale references prove removal.
- `defer`: known future need, not part of this package.

No workflow is removed by this audit. Risky retirements require a migration note and CI-readiness tests before deletion. Detailed evidence for retire candidates is recorded in `docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md`.

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
| `bot-dashboard-issue.yml` | `keep_core` | Report-only bot dashboard issue visibility path. | Keep dry-run/report-only by default; real issue update requires explicit maintainer input. |
| `catalog-agent-pr.yml` | `keep_support` | Manual support path for agent-authored catalog PRs. | Keep as PR-only support path. |
| `catalog-maintenance-pr.yml` | `keep_support` | Scheduled/manual support path for maintenance PRs. | Keep until overlap with promotion and repair paths is further reduced. |
| `contribution-intake-agent.yml` | `keep_support` | Issue-to-PR intake support path. | Keep. |
| `catalog-maintenance.yml` | `retire_candidate` | Overlaps with validation/index/test work in `validate.yml` and catalog quality/entity reporting in `coverage-audit.yml`; entity-stub replacement is not proven. | Keep as `retire_candidate`; see `WORKFLOW_RETIREMENT_EVIDENCE.md`. |
| `source-refinement-queue.yml` | `retire_candidate` | Consumes older observation report paths and overlaps with `source-maintenance-report.yml`, source repair sweep output, source review triage, and reviewer decision sheet; stale consumers remain unproven. | Quarantined by WP22; keep manual-only until deletion evidence is complete. |
| `observe-report.yml` | `retire_candidate` | May be superseded for source observations by `source-observation-ledger`, `latest-source-health`, and `public/source-health-snapshot`; non-source observation role remains unresolved. | Keep as `retire_candidate`; see `WORKFLOW_RETIREMENT_EVIDENCE.md`. |

## Retire/consolidation candidate detail

### `catalog-maintenance.yml`

Observed overlap:

- Validation/index/test behavior overlaps with `validate.yml`.
- Catalog quality and entity reporting overlap with `coverage-audit.yml`.
- Entity stub reporting is not yet proven redundant.

Recommended action:

Retire after confirming entity stub reporting is either no longer needed or folded into `coverage-audit.yml`. Do not delete until docs and tests prove that no current operator sequence points to it as an authoritative workflow.

### `source-refinement-queue.yml`

Observed overlap:

- It consumes an older observation report path.
- It likely overlaps with `source-maintenance-report.yml`, source repair sweep artifacts, source review triage output, and the reviewer decision sheet.
- `docs/source-refinement-workflow.md` must be reviewed before removal.

Recommended action:

WP22 quarantines this workflow because it is already manual-only and read-only. Do not delete it until no unique queue remains and stale references and consumers are proven clean.

### `observe-report.yml`

Observed overlap:

- Source-specific observation needs are increasingly represented by `source-observation-ledger.json`, `latest-source-health.json`, and `public/source-health-snapshot.json`.
- `README.md` and `docs/observation-reporting.md` must be reviewed before removal.

Recommended action:

Keep only if it tracks non-source observations still needed by the project. If not, mark legacy and retire after consumers are migrated.

## Future actions not implemented here

### Future Action A: reviewed decision validation handoff

Purpose: after a reviewer returns `source-review-decision-sheet.csv`, run validation manually or through an existing controlled path.

Current status: handoff hardening is documented. The controlled path is `source_review_decisions validate-sheet` followed by `source_review_decisions export-reviewed-artifacts` only when validation has zero invalid rows. Reviewed artifacts must be committed under `maintenance/reviewed/` before `source-repair-pr.yml` is run.

Do not add a scheduled workflow for this path. Do not automatically mutate catalog records from reviewer sheets. Do not run `source-repair-pr.yml` from uncommitted reviewer input.

### Future Action B: reviewed no-replacement truth-state application

Purpose: define whether no-replacement decisions live under `maintenance/reviewed/` or in a first-class unavailable-source catalog structure.

Current status: design is documented in `NO_REPLACEMENT_TRUTH_STATE_DESIGN.md`. No application code or catalog schema write is implemented in this package.

Do not implement until the truth-state schema is decided.

### Future Action C: workflow retirement

Purpose: retire `catalog-maintenance.yml`, `source-refinement-queue.yml`, and/or `observe-report.yml` only after the audit proves their outputs are fully replaced.

Current status: retirement evidence is documented in `WORKFLOW_RETIREMENT_EVIDENCE.md`; `source-refinement-queue.yml` is quarantined by contract, and no workflow is removed because none is proven safe to delete.

Do not delete all three in one package unless tests and docs prove no consumers remain.

### Future Action D: source operations scheduler

Purpose: at catalog scale, add sharded or incremental source checking.

Current status: architecture is documented in `SOURCE_OPERATIONS_SCHEDULER_SPEC.md`. No workflow, scheduler command, or schedule change is implemented in this package.

Do not implement now.

### Future Action E: catalog growth gating dashboard

Purpose: show when Lane B promotion is allowed based on source-health debt.

Current status: dashboard contract is documented in `CATALOG_GROWTH_GATING_DASHBOARD_SPEC.md`. No UI, workflow, or automatic promotion behavior is implemented in this package.

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
