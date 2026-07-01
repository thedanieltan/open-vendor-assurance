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

## Committed Event Ledger (WP32)

WP32 amends the earlier deferral. OpenVA now commits a **compact, append-only
observation event ledger**, with growth controls that answer the original
deferral concerns:

- Only **events** are committed (first observation, access change, redirect
  change, material/non-material content change, health transition). Unchanged
  observations never produce committed rows, so growth is bounded by the
  actual change rate, not by run frequency.
- Events are stored as **monthly NDJSON files** under
  `maintenance/source-observations/events/YYYY-MM.ndjson` — one event per
  line, minimal reviewable diffs, and a natural compaction unit later.
- Rows enter the committed ledger **only through reviewed pull requests** via
  `python -m tools.openva.observation_ledger append`. Workflows never commit
  ledger files; they upload a proposed delta as an artifact.
- Existing lines are never rewritten or reordered; out-of-order appends are
  refused.

Full per-run observation records remain artifact-only.

See `docs/observation-ledger.md` for the ledger model, field semantics, and
the reviewed-PR append procedure.

## Near-Term Strategy

The approved strategy is:

- Full per-run observation records remain artifact-only.
- The committed ledger stores compact change events only (see above).
- `latest-source-health.json` is regenerated from the latest source observation ledger artifact.
- `public/source-health-snapshot.json` is regenerated from `latest-source-health.json`.
- The site consumes the latest available public source-health snapshot artifact.
- The site falls back to `No source-health observation` labels when no snapshot artifact is available.
- Release readiness consumes source-health artifacts rather than running full-catalog live verification inside the release workflow.

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
