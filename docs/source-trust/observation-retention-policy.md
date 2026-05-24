# Source Observation Retention Policy

OpenVA source-health observations are operational public-source facts. They are not legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.

This policy covers the Layer 4 source-trust artifacts produced by source maintenance:

- `source-observation-ledger.json`
- `latest-source-health.json`
- `public/source-health-snapshot.json`

## Current State

`source-maintenance-report` generates source observation and source-health artifacts from source verification output.

Those artifacts are not committed to the repository. They are uploaded as GitHub Actions artifacts and consumed by later workflows such as release readiness and site publishing.

`latest-source-health.json` and `public/source-health-snapshot.json` are artifact-derived views. They summarize the latest known source-health state from the latest available maintenance run. They are snapshots, not permanent guarantees that a source remains reachable or suitable.

## Deferred Append-Only History

OpenVA does not commit append-only historical source observation ledgers yet.

Durable committed history is deferred because:

- Full observation history can create repo bloat as source count and run frequency grow.
- Large generated history files create noisy diffs that obscure meaningful catalog review.
- The correct retention horizon is not decided.
- There is no compaction policy yet.
- Public site/API requirements currently need a latest snapshot more than a complete run history.

## Near-Term Strategy

The approved near-term strategy is:

- Historical observations remain artifact-only.
- `latest-source-health.json` is regenerated from the latest source observation ledger artifact.
- `public/source-health-snapshot.json` is regenerated from `latest-source-health.json`.
- The site consumes the latest available public source-health snapshot artifact.
- The site falls back to `Not yet verified` labels when no snapshot artifact is available.
- Release readiness consumes source-health artifacts rather than running full-catalog live verification inside the release workflow.
- No append-only historical observation ledger is committed to the repository yet.

## Future Options

Future durable storage may use one of these approaches:

- A committed compact latest snapshot only.
- A rolling N-run source observation ledger.
- Monthly compressed source-health snapshots.
- External artifact or object storage with explicit retention controls.
- A hybrid model where the repository stores only compact latest state and external storage keeps longer history.

## Decision Criteria

Before adding a durable source observation ledger, maintainers should decide:

- Expected source count and maintenance run frequency.
- Required artifact retention horizon.
- Whether the public site/API needs historical trend data or only latest state.
- Repository size impact and generated diff noise.
- Auditability requirements for source-health claims.
- Compaction rules for duplicate, superseded, or low-value observations.
- Whether external storage is available and appropriate.

## Non-Goals

This policy does not:

- Commit observation history.
- Add a database.
- Change source-maintenance artifacts.
- Change site behavior.
- Change release gate behavior.
- Mutate catalog data.
- Mirror raw source documents.

## Review Trigger

Revisit this policy when any of the following becomes true:

- Source count or maintenance cadence makes artifact-only history insufficient.
- GitHub Actions artifact retention is too short for operational needs.
- The public site/API needs historical source-health trend data.
- Release readiness needs auditable evidence older than the latest maintenance artifact.
- Maintainers propose committing any historical observation records.
