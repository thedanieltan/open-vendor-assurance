# Workflow Retirement Evidence

This document records the evidence needed before retiring current consolidation candidates. It supports `WORKFLOW_CONSOLIDATION_AUDIT.md` and intentionally does not delete any workflow.

A workflow may move from `retire_candidate` or `quarantined` to `remove_now_if_safe` only when its replacement is documented, its current artifacts are fully replaced, its consumers are migrated, stale references are removed or marked legacy, and CI-readiness tests prove the public workflow surface is intentional.

## Current result

No workflow is removed by this package. WP22 quarantines `source-refinement-queue.yml` by contract because it is already manual-only, read-only, and has active replacement owners, but stale docs and operator artifact consumers still block deletion. WP26 quarantines `observe-report.yml` by removing scheduled operation and keeping manual dispatch while replacement evidence is completed.

| Workflow | Current classification | Evidence result | Replacement status | Recommendation |
|---|---|---|---|---|
| `catalog-maintenance.yml` | `retire_candidate` | Not safe to remove yet. | Partial replacement only. | Keep as `retire_candidate`. |
| `source-refinement-queue.yml` | `quarantined` | First legacy report workflow quarantined; not safe to delete. | Replaced for current source cleanup by `source-maintenance-report.yml` and `source-refinement-scan.yml`, but stale consumers and docs still need proof. | Keep manual-only and blocked from destructive retirement. |
| `observe-report.yml` | `quarantined` | Second legacy report workflow quarantined; not safe to delete. | Source-observation replacement exists through source maintenance, catalog growth, and dashboard reporting, but non-source observation role is unresolved. | Keep manual-only and blocked from destructive retirement. |

## Evidence requirements

Before removal, each candidate must satisfy all of the following:

1. The workflow is classified as `remove_now_if_safe` in `WORKFLOW_CONSOLIDATION_AUDIT.md`.
2. This evidence document names a replacement workflow or states why no replacement is needed.
3. All artifact consumers are migrated or explicitly marked legacy.
4. All current docs either stop referring to the workflow as current or mark it legacy.
5. CI-readiness tests assert the workflow is absent if removed.
6. No release, site, source cleanup, catalog growth, or PR safety loop depends on the workflow.

## Candidate: `catalog-maintenance.yml`

### Current purpose

`catalog-maintenance.yml` is a read-only scheduled/manual maintenance report. It validates the catalog, rebuilds generated indexes, checks generated-file drift, runs tests, builds an entity stub report, writes a maintenance summary, and uploads `catalog-maintenance-report`.

### Current trigger

- Scheduled weekly.
- Manual `workflow_dispatch`.

### Current permissions

- `contents: read`
- `actions: read`

### Artifacts produced

- `reports/entity-stub-report.json`
- `reports/catalog-maintenance-report.md`
- Artifact name: `catalog-maintenance-report`

### Current documented consumers

- Operators reviewing catalog maintenance output.
- CI-readiness tests that intentionally allowlist the workflow.
- Historical docs may still mention it as a current maintenance report.

### Tests that depend on it

- Public workflow allowlist tests include `catalog-maintenance.yml`.
- Write-permission readiness tests implicitly expect it to remain read-only.

### Replacement workflow

Partial replacement only:

- `validate.yml` replaces validation, index build, generated drift, and test checks.
- `coverage-audit.yml` replaces much of the catalog quality reporting posture.

### Replacement artifact equivalence

Not fully equivalent. The entity stub report is not proven to be fully folded into `coverage-audit.yml`.

### Stale-reference status

Not yet proven clean. Do not remove until references are searched and either migrated to `coverage-audit.yml`/`validate.yml` or marked legacy.

### Recommendation

Keep as `retire_candidate`. Do not move to `remove_now_if_safe` until entity stub reporting is either removed as unnecessary or folded into `coverage-audit.yml` with tests.

## Candidate: `source-refinement-queue.yml`

### Current purpose

`source-refinement-queue.yml` is a manual workflow that reads an observation report JSON path, generates a source refinement queue in Markdown and JSON, exports a CSV, and uploads `openva-source-refinement-queue`. WP22 quarantines it by contract as the first legacy report workflow.

### Current trigger

- Manual `workflow_dispatch` with optional `observation_report_json` input.

### Current permissions

- `contents: read`

### Artifacts produced

- `reports/source-refinement-queue.md`
- `reports/source-refinement-queue.json`
- `reports/source-refinement-queue.csv`
- Artifact name: `openva-source-refinement-queue`

### Current documented consumers

- Legacy operators using the older observation-report-derived queue.
- CI-readiness tests that intentionally allowlist the workflow and assert uploaded artifacts.
- `docs/source-refinement-workflow.md` references this path and must be reviewed before removal.

### Tests that depend on it

- Public workflow allowlist tests include `source-refinement-queue.yml`.
- Report artifact tests assert `reports/source-refinement-queue.md`, `.json`, and `.csv`.

### Replacement workflow

Replacement owner:

- `source-maintenance-report.yml` now produces source quality refinement artifacts, source repair sweep artifacts, source review triage artifacts, and the reviewer decision sheet.
- `source-refinement-scan.yml` handles confirmed P0 refinement from repeated source maintenance runs.

### Replacement artifact equivalence

Sufficient for quarantine, but not for deletion. `source-maintenance-report.yml` produces more current source cleanup artifacts, and `source-refinement-scan.yml` owns confirmed P0 refinement evidence. The older observation-report-derived queue may still have doc references or operator expectations.

### Stale-reference status

Not clean yet. `docs/source-refinement-workflow.md` is now marked legacy/quarantined, but human review and agent-control-plane references still need a later cleanup before deletion.

### Recommendation

Keep as `quarantined`. Do not delete until stale references are migrated, two clean replacement runs are recorded, and tests prove no unique queue remains.

## Candidate: `observe-report.yml`

### Current purpose

`observe-report.yml` runs a full public-source observation dry run, generates an observation report, exports an observation review queue CSV, and uploads `openva-observation-report`. WP26 quarantines it by contract as the second legacy report workflow.

### Current trigger

- Manual `workflow_dispatch` only.
- Scheduled operation was removed by WP26.

### Current permissions

- `contents: read`

### Artifacts produced

- `reports/observation-report.md`
- `reports/observation-report.json`
- `reports/observation-review-queue.csv`
- Artifact name: `openva-observation-report`

### Current documented consumers

- Legacy operators reviewing observation output.
- CI-readiness tests that intentionally allowlist the workflow and assert uploaded artifacts.
- `README.md` and `docs/observation-reporting.md` may still reference this as a current observation report.

### Tests that depend on it

- Public workflow allowlist tests include `observe-report.yml`.
- Read-only observation workflow tests assert trigger shape, permissions, dry-run command, produced files, and no PR creation.
- Report artifact tests assert observation report artifacts.

### Replacement workflow

Partial replacement for source-specific observation:

- `source-maintenance-report.yml` produces `source-observation-ledger.json`.
- `source-maintenance-report.yml` produces `latest-source-health.json`.
- `source-maintenance-report.yml` produces `public/source-health-snapshot.json`.
- `catalog-growth-discovery.yml` proposes catalog-growth candidates through report-only discovery.
- Bot dashboard reports expose source-health, coverage, stale evidence, and failure-router posture.

### Replacement artifact equivalence

Sufficient for quarantine, but not for deletion. Source-health outputs cover source-specific observation needs, but a non-source observation role is not yet ruled out.

### Stale-reference status

Not clean yet. `README.md` and `docs/observation-reporting.md` must be reviewed before removal.

### Recommendation

Keep as `quarantined`. Do not delete until the project decides that non-source observations are not needed or migrates that role to another documented workflow.

## Future removal checklist

For any future PR that removes one of these workflows, include tests that assert:

1. The workflow file is absent from `.github/workflows/`.
2. The public workflow allowlist no longer includes it.
3. This document names its replacement.
4. `WORKFLOW_CONSOLIDATION_AUDIT.md` classifies it as `remove_now_if_safe` or records the completed removal.
5. No docs refer to the removed workflow as a current authoritative workflow.
6. Existing current artifacts are produced by replacement workflows or are explicitly retired.

## Scope guardrails

This evidence audit does not:

- remove workflows,
- create workflows,
- mutate catalog source records,
- generate repair PRs,
- alter automerge behavior,
- relax validation, source-health, review, release, or site gates.
