# Source Operations Scheduler Spec

This document defines the future source operations scheduler architecture. It is a spec only. It does not create a workflow, change a schedule, does not mutate catalog records, or alter source-health gates.

## Purpose

At catalog scale, full source checking can become expensive, noisy, and hard to review. The future scheduler should support sharded and incremental source checks while preserving the current Lane A operating model.

`source-maintenance-report.yml` remains the source cleanup and reporting entry point until a future migration proves otherwise.

## Goals

- Support deterministic source-check sharding.
- Support incremental source verification.
- Avoid source-check starvation.
- Preserve reviewer-friendly artifacts.
- Preserve machine/operator artifacts.
- Keep source-health evidence compatible with release readiness.
- Allow emergency full runs.
- Keep repair PR generation separate from checking.

## Non-goals

The scheduler must not:

- replace `source-maintenance-report.yml` in this package,
- create repair PRs,
- mutate `data/vendors/**`,
- change source URLs,
- weaken source-health gates,
- bypass reviewer decision validation,
- bypass `source-refinement-scan.yml`,
- bypass release readiness,
- create a new workflow in this package.

## Inputs

Future scheduler inputs may include:

- canonical vendor/source records,
- previous `latest-source-health.json`,
- previous `source-observation-ledger.json`,
- previous `public/source-health-snapshot.json`,
- source type,
- vendor priority,
- last checked timestamp,
- last verification status,
- stale no-replacement evidence,
- release readiness policy,
- manual emergency full-run flag.

## Outputs

Future scheduler outputs should be artifacts, not catalog mutations:

- shard manifest,
- selected source list,
- skipped source list with reasons,
- source verification report for selected sources,
- scheduler summary,
- freshness coverage report,
- operator-readable markdown summary.

## Sharding strategy

A future scheduler should use deterministic shard assignment so the same source maps consistently unless the source identity changes.

Candidate shard key:

```text
vendor_id + source_id + source_type
```

Required shard properties:

- deterministic,
- stable across runs,
- independent of repository traversal order,
- evenly distributed enough for catalog scale,
- auditable in generated artifacts.

## Incremental scheduling strategy

The scheduler should prioritize:

1. Previously failing or unavailable sources.
2. Sources with stale `last_checked_at`.
3. Sources near release readiness thresholds.
4. Sources with recent replacement/no-replacement review activity.
5. New catalog growth sources.
6. Remaining sources by deterministic shard rotation.

No source should be skipped indefinitely. Every source needs a maximum age threshold that forces re-check.

## Retry and backoff rules

Future retry policy should distinguish:

- transient network failure,
- DNS failure,
- TLS failure,
- HTTP 5xx,
- HTTP 4xx,
- gated/login-required access,
- semantic mismatch,
- soft 404,
- redirect drift.

Backoff must not hide persistent source debt. Repeated failures should feed `source-refinement-scan.yml` and source cleanup artifacts rather than silently disappearing.

## Artifact naming

Future scheduler artifacts should be explicit and non-authoritative, for example:

- `openva-source-scheduler-plan`
- `source-scheduler-plan.json`
- `source-scheduler-summary.md`
- `source-scheduler-selected-sources.csv`
- `source-scheduler-skipped-sources.csv`

Names must not imply catalog truth or reviewed repair authority.

## Relationship to `source-maintenance-report.yml`

`source-maintenance-report.yml` remains the authoritative reporting entry point for Lane A.

Future scheduler output may feed `source-maintenance-report.yml`, but it must not replace the full source maintenance artifact package until:

- artifact equivalence is documented,
- reviewer inbox behavior is preserved,
- release readiness consumes the new shape safely,
- tests prove no consumer breakage.

## Relationship to `source-refinement-scan.yml`

`source-refinement-scan.yml` currently confirms P0 candidates from repeated source maintenance evidence.

Future scheduler output must preserve enough historical evidence for repeated-failure confirmation. It must not bypass confirmation history or generate repairs directly.

## Relationship to release readiness

Release readiness should consume scheduler-derived artifacts only after policy is explicit.

Future release behavior must distinguish:

- checked and healthy,
- checked and failing,
- not checked in current shard but still fresh,
- not checked and stale,
- reviewed unavailable-source state,
- stale reviewed unavailable-source state.

## Failure modes

The scheduler must handle:

- missing previous artifacts,
- incomplete shard output,
- stale shard coverage,
- failed source verification run,
- artifact download failure,
- skewed shard distribution,
- new source records missing prior history,
- emergency release requiring full check.

Failure should fail closed for release readiness when source freshness cannot be established.

## Migration plan

1. Keep `source-maintenance-report.yml` unchanged.
2. Build a scheduler planning CLI in a future package.
3. Emit report-only scheduler artifacts.
4. Compare scheduler output against full source maintenance output.
5. Add CI-readiness tests for artifact shape.
6. Add workflow integration only after artifact equivalence is proven.
7. Preserve emergency full-run path.

## Tests required before implementation

Before implementation, tests must prove:

- deterministic shard assignment,
- no starvation across rotations,
- priority ordering,
- stale-source escalation,
- emergency full-run selection,
- artifact schema stability,
- no catalog mutation,
- no repair PR generation,
- release readiness can distinguish stale from fresh skipped sources.

## Guardrails

This spec does not authorize:

- new workflow creation,
- schedule changes,
- catalog mutation,
- source URL replacement,
- repair PR generation,
- release-gate relaxation,
- reviewer artifact shape changes.
