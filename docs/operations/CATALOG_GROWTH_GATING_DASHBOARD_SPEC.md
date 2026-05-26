# Catalog Growth Gating Dashboard Spec

This document defines the future catalog growth gating dashboard. It is a spec only. It does not build UI, create a workflow, change promotion behavior, or mutate catalog records.

## Purpose

Lane B catalog growth should not proceed blindly when source-health debt or catalog-quality issues are high. A future dashboard should help operators decide whether candidate promotion is allowed, allowed with warnings, or blocked pending cleanup.

The dashboard is an operator decision aid. It is not catalog truth and must not automatically promote candidates.

## Non-goals

The dashboard must not:

- automatically promote candidates,
- must not automatically mutate `data/vendors/**`,
- replace `catalog-growth-discovery.yml`,
- replace `candidate-promotion-pr.yml`,
- replace `source-maintenance-report.yml`,
- replace `coverage-audit.yml`,
- relax release gates,
- block emergency manual review without an explicit human decision,
- become a source of catalog truth.

## Input artifacts

Future dashboard input should come from existing report artifacts:

- `latest-source-health.json`
- `public/source-health-snapshot.json`
- `source-observation-ledger.json`
- source maintenance summary artifacts
- catalog completeness report
- entity review queue
- field provenance coverage report
- catalog growth discovery report
- candidate promotion plan
- release source-health readiness report

The dashboard should consume artifacts. It should not generate canonical catalog truth.

## Gating signals

Candidate signals:

- number of current source-health failures,
- number of stale source checks,
- number of confirmed P0 source repair candidates,
- number of unresolved reviewed decision rows,
- number of stale no-replacement decisions,
- catalog completeness score,
- entity review queue count,
- field provenance coverage gaps,
- number of pending candidate promotion actions,
- missing required artifacts,
- age of latest source maintenance run,
- age of latest coverage audit run.

## Suggested dashboard states

```text
promotion_allowed
promotion_allowed_with_warnings
promotion_blocked_source_debt
promotion_blocked_catalog_quality
promotion_blocked_missing_artifacts
```

## State semantics

### `promotion_allowed`

All required artifacts are current, source-health debt is within policy, catalog quality is within policy, and no blocking candidate promotion issues are known.

### `promotion_allowed_with_warnings`

Promotion may proceed after human review, but warnings exist. Examples include stale but non-blocking source checks, non-critical provenance gaps, or low-severity entity review items.

### `promotion_blocked_source_debt`

Source-health debt is above policy threshold, confirmed P0 source candidates exist, or required source-health artifacts are stale.

### `promotion_blocked_catalog_quality`

Catalog completeness, entity correctness, or provenance coverage is below policy threshold.

### `promotion_blocked_missing_artifacts`

Required artifacts are missing or too old to support a gating decision.

## Operator decisions

The dashboard should help operators answer:

1. Can Lane B promotion proceed now?
2. Which blockers must be cleared first?
3. Is the blocker source debt, catalog quality, or missing evidence?
4. Which workflow should run next?
5. Which artifact supports the decision?

The dashboard must always preserve human review. It should not bypass `candidate-promotion-pr.yml` or the PR safety loop.

## Relationship to `catalog-growth-discovery.yml`

`catalog-growth-discovery.yml` remains the catalog expansion proposal entry point.

The dashboard may show the latest discovery plan and candidate counts, but it must not write candidates into the catalog.

## Relationship to `candidate-promotion-pr.yml`

`candidate-promotion-pr.yml` remains the controlled write path for reviewed promotions.

The dashboard may indicate whether promotion is allowed by policy, but it must not invoke candidate promotion automatically.

## Relationship to `source-maintenance-report.yml`

`source-maintenance-report.yml` remains the source cleanup and reporting entry point.

The dashboard should consume source-health artifacts from it and point operators back to source cleanup when source debt blocks growth.

## Relationship to `coverage-audit.yml`

`coverage-audit.yml` remains the catalog quality entry point.

The dashboard should consume coverage, completeness, entity review, and provenance artifacts from it. It must not duplicate catalog-quality calculations unless a future implementation explicitly defines derived dashboard metrics.

## Relationship to release/site loop

The dashboard may be displayed on a future operator-facing surface or exported as a report, but it must not become a release gate until policy is explicit.

Release/site workflows may consume its output only after:

- dashboard artifact schema is stable,
- required input artifacts are defined,
- blocking thresholds are documented,
- tests prove missing or stale artifacts fail closed.

## Future implementation path

1. Define policy thresholds in documentation.
2. Build a report-only dashboard artifact generator.
3. Consume existing artifacts only.
4. Add tests for state derivation.
5. Add CI-readiness tests for artifact shape.
6. Add site or operator display only after report-only output is stable.
7. Keep candidate promotion manual/controlled.

## Guardrails

This spec does not authorize:

- UI implementation,
- workflow creation,
- automatic promotion,
- catalog mutation,
- source URL replacement,
- source-health gate relaxation,
- release-gate relaxation,
- replacement of `coverage-audit.yml`,
- replacement of `source-maintenance-report.yml`.
