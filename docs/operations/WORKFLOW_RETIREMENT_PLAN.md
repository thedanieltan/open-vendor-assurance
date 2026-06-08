# Workflow Retirement Plan

This document defines the workflow retirement and sunset plan for OpenVA. It applies the Bot Operating Model retirement statuses to the current public workflow inventory.

Workflow retirement is separate from deletion. Retirement is the evidence-backed decision that a workflow no longer owns a primary operating function. Deletion is a later destructive change that must happen in a follow-up PR after this plan, the inventory contract, and validation tests agree.

The machine-readable contract is `docs/operations/contracts/workflow-retirement.yaml`.

## Purpose

OpenVA has mature strict-growth and controlled promotion lanes, plus bot operating contracts for dashboard state, queue checks, failure routing, report-only chat-ops, calibration, and dashboard signal quality. The remaining risk is workflow sprawl: legacy report workflows and support workflows can stay callable longer than their authority model justifies.

The plan answers which workflows are active, shadow/report-only, deprecated but callable, quarantined, retired, or blocked from retirement.

## Status Definitions

| Status | Meaning | Current use |
|---|---|---|
| `active` | Current workflow with declared operating ownership. | Core PR safety, source maintenance, catalog quality, catalog growth, bot operations, and publication workflows. |
| `shadow_report_only` | Report-only comparison or migration workflow. | Legacy reporting workflows that do not write repository state. |
| `deprecated_callable` | Callable for compatibility while replacement evidence is gathered. | Support PR workflows that must not expand strict-growth authority. |
| `quarantined` | Temporarily blocked from scheduled or primary operation while replacement evidence is finalized. | `source-refinement-queue.yml` and `observe-report.yml` are manual-only quarantined legacy report workflows. |
| `retired` | Removed from active operation after evidence and follow-up destructive PR. | No current public workflow is retired. |

Unknown or unclassified workflows block retirement by default. A destructive retirement PR must prove that the workflow has a valid classification, replacement owner, evidence trail, passing tests, and no remaining dashboard, release, or operator dependency.

## Current Classification

Core workflows remain `active` and must not be retired yet:

- `validate.yml`
- `catalog-pr-guard.yml`
- `agent-weighted-review.yml`
- `agent-automerge.yml`
- `source-maintenance-report.yml`
- `source-refinement-scan.yml`
- `source-repair-pr.yml`
- `source-repair-pr-cleanup.yml`
- `coverage-audit.yml`
- `catalog-growth-discovery.yml`
- `candidate-promotion-pr.yml`
- `release-candidate.yml`
- `site-pages.yml`
- `release-downloads.yml`
- `site-live-feed.yml`
- `bot-dashboard-issue.yml`

Support workflows are `deprecated_callable`. They remain callable during compatibility review, but they are not strict-growth authority and are candidates for later consolidation:

- `catalog-agent-pr.yml`
- `catalog-maintenance-pr.yml`
- `contribution-intake-agent.yml`

Legacy report workflows now have split posture:

- `catalog-maintenance.yml` remains `shadow_report_only` while legacy catalog-maintenance artifact dependencies are checked.
- `source-refinement-queue.yml` is quarantined by WP22 as the first legacy report workflow.
- `observe-report.yml` is quarantined by WP26 as the second legacy report workflow.

Both quarantined workflows remain present and manual-only. They are not deleted, disabled, renamed, or granted new permissions. Quarantine removes scheduled primary operation while leaving a rollback/manual evidence path.

No workflow is marked `retired` in this work package.

## Replacement Owner Model

Each retirement candidate must name a replacement workflow or operating loop that owns the same function. Replacement ownership does not mean the old workflow can be deleted immediately. It means the future retirement PR knows which loop must provide evidence.

Examples:

- Legacy catalog maintenance reporting is covered by `validate.yml`, `source-maintenance-report.yml`, `coverage-audit.yml`, and deterministic index validation.
- Legacy source refinement queue output is covered by `source-refinement-scan.yml` and the source maintenance loop.
- Observation report output is covered by `source-maintenance-report.yml`, `catalog-growth-discovery.yml`, and the dashboard/failure-router operating loops.
- Support catalog PR paths must converge on reviewed evidence, controlled promotion, source repair, or a separately approved support operating loop.

## Retirement Gates

A future destructive retirement PR must prove all of the following:

1. The workflow is classified in `workflow-retirement.yaml`.
2. The workflow is not `active`.
3. The replacement owner is named and has passed a recent run or validation check.
4. Required retirement evidence is present and linked from the PR.
5. Remaining blockers are resolved or explicitly accepted by maintainers.
6. Dashboard, release, site, and operator documentation no longer depend on legacy-only artifacts.
7. `tests/test_workflow_retirement.py` and `tests/test_workflow_contracts.py` pass.
8. Workflow inventory is updated in the same destructive PR if a workflow file is removed.

WP22 and WP26 quarantine actions are not destructive retirement. They are contract classifications that confirm selected legacy report workflows are no longer primary scheduled operating paths while keeping manual workflows available for rollback or legacy artifact inspection.

Deletion, disabling, permission changes, and workflow renames remain out of scope unless a later destructive retirement PR satisfies the gates. WP26 makes only one trigger posture change: `observe-report.yml` becomes manual-only.

## Evidence Requirements

Retirement evidence is lane-specific, but every candidate needs:

- passing validation suite output
- replacement-owner run evidence
- dashboard or report comparison evidence when replacing a report-only workflow
- queue and failure-router compatibility evidence when replacing a bot-facing workflow
- confirmation that no catalog truth is sourced only from the retiring workflow
- confirmation that report-only lanes did not mutate catalog truth

For catalog growth and source repair, evidence must preserve reviewed evidence, source repair, promotion actions, strict-growth, and controlled promotion boundaries.

## What Must Not Be Retired Yet

The PR safety loop must not be retired while it protects main:

- `validate.yml`
- `catalog-pr-guard.yml`
- `agent-weighted-review.yml`
- `agent-automerge.yml`

The source maintenance and source repair loop must not be retired while source certainty and reviewed evidence remain release gates:

- `source-maintenance-report.yml`
- `source-refinement-scan.yml`
- `source-repair-pr.yml`
- `source-repair-pr-cleanup.yml`

The catalog growth loop must not be retired while discovery may propose and controlled promotion writes:

- `catalog-growth-discovery.yml`
- `candidate-promotion-pr.yml`

The publication loop must not be retired while it owns release, site, download, and live-feed outputs:

- `release-candidate.yml`
- `site-pages.yml`
- `release-downloads.yml`
- `site-live-feed.yml`

Support workflows must not be deleted until maintainers decide whether their function is replaced by reviewed evidence, controlled promotion, source repair, dashboard/chat-ops reporting, or a smaller explicit support lane.

Quarantined legacy report workflows must not be deleted until their artifact-consumer and operator-doc blockers are cleared:

- `source-refinement-queue.yml`
- `observe-report.yml`

## Future Destructive PR Checklist

A destructive retirement PR must include:

- the workflow name and current retirement status
- replacement owner and successful evidence
- resolved blockers
- artifact dependency check
- permission and trigger removal rationale
- workflow inventory update
- site/release impact statement
- exact validation commands and results

If any workflow is still unclassified, `workflow-retirement.yaml` denies retirement by default.
