# Discovery Mesh Operating Model

This document extends `WORKFLOW_OPERATING_MODEL.md` and `WORKFLOW_CONSOLIDATION_AUDIT.md` for the full-catalog discovery mesh introduced under `WP-02E-SUPPLY-CHAIN`.

## Workflow classification

| Workflow | Operating loop | Classification | Trigger | Mutation boundary |
|---|---|---|---|---|
| `discovery-mesh.yml` | Catalog growth | `keep_core` | `workflow_dispatch`, daily schedule, and closed candidate-intake pull requests | May create and enable native auto-merge for a noncanonical candidate-intake PR. It never writes canonical vendor or source records directly. |

## Catalog breadth

`discovery-mesh.yml` has no catalog vendor-count cap. Every scheduled run deterministically assigns the complete eligible catalog to one of 32 shards. The optional `vendor_limit` input exists only for manually dispatched diagnostics and is not applied to scheduled runs.

The page, request, link, locator, and delegated-host limits are per-vendor resource-safety bounds. They do not restrict the number of vendors OpenVA may discover, resolve, maintain, or admit.

## Source-depth execution

Each shard:

1. enumerates every vendor assigned to that shard;
2. traverses every attested official domain;
3. performs bounded depth-two HTML link-graph discovery;
4. applies deterministic multilingual source-type classification;
5. verifies official-domain locator candidates through the existing source-verification machinery;
6. emits delegated-host locators as unverified first-party-attested signals;
7. extracts subprocessor relationship identity signals;
8. writes report artifacts only.

The aggregate job deduplicates shard results, verifies candidate sources, preserves unresolved vendor identity signals, and builds a reviewed promotion plan.

## Vendor-breadth replenishment

The aggregate job projects relationship identity observations through `vendor_breadth_replenishment` into four stable, noncanonical files:

- `maintenance/generated/vendor-breadth-signal-ledger.json`;
- `maintenance/generated/vendor-breadth-resolution-queue.json`;
- `maintenance/generated/vendor-breadth-candidates.json`;
- `maintenance/generated/vendor-breadth-provider-metrics.json`.

The ledger is replay-idempotent. Reprocessing the same provider signal does not increment demand or observation counts and does not change persisted bytes. Distinct signal IDs, such as distinct resolver requests or separately attested provider records, accumulate as independent observations. Material corrections update the existing observation in place.

Incomplete identities remain in the resolution queue. Only identities with a usable name, official-domain candidate, and country candidate enter `vendor-breadth-candidates.json`. Current and previous catalog domains are excluded. Provider-replenished candidates are not truncated by curated seed targets and are consumed by the existing `vendor_candidate_discovery` command.

Relationship signals are produced automatically by the daily mesh. Resolver-demand and public-directory adapters use the same ledger contract and may be supplied by an authorized producer without changing the admission pipeline. Provider signals are evidence inputs, not catalog facts.

## Production health and intake decision

Every aggregate run builds JSON and Markdown `discovery_mesh_health` reports. The report separates:

- current catalog breadth and source depth;
- pages, requests, locator signals, delegated hosts, and verified source candidates;
- provider-discovered entities, unresolved identities, and source-discovery-ready candidates;
- viable reviewed promotion actions;
- locator, verification, and promotion yield ratios;
- changed versus unchanged stable breadth outputs.

The health report is report-only and non-advisory. It does not score vendors or alter admission thresholds.

The health report also provides the deterministic intake decision:

- intake is needed when at least one viable source-promotion action exists or at least one stable breadth projection changed;
- a true no-op run has neither viable source-promotion actions nor changed stable breadth outputs;
- true no-op runs upload evidence and exit without creating a pull request.

A health status of `attention` does not bypass or automatically loosen crawl, identity, or admission controls. Its reason codes are operational diagnostics for maintainers.

## Exact candidate-intake boundary

The aggregate job opens `Ops: stage discovery mesh candidates` from an `agent-discovery-mesh-intake-*` branch only when the health decision requires intake.

The PR may contain only:

- stable changed `maintenance/generated/vendor-breadth-*.json` projections;
- the exact reviewed discovery-mesh promotion plan when it contains viable actions;
- candidate-source YAML records explicitly referenced by that exact plan.

Run-specific identity signals, candidate manifests, viability reports, source-discovery reports, replenishment-run reports, and health reports remain workflow artifacts. They are not committed merely to preserve execution telemetry.

Before commit, the workflow enforces a cached-path allowlist and fails closed when:

- a candidate path is outside `data/vendors/*/candidate_sources/*.yaml`;
- a staged candidate is not accompanied by the exact reviewed promotion plan;
- any unrelated path is staged;
- health requires intake but no eligible changed path exists.

The candidate-intake PR does not contain canonical source or vendor mutations. It runs through normal validation and native auto-merge.

## Canonical mutation boundary

When an exact candidate-intake PR merges, the `promotion-handoff` job inside `discovery-mesh.yml`:

- requires the exact branch prefix and PR title;
- requires exactly one merged discovery-mesh promotion plan;
- no-ops when the intake contains only breadth projections;
- no-ops on a zero-action plan;
- fails closed on ambiguous plan selection;
- dispatches `candidate-promotion-pr.yml` in `reviewed-path` mode with the exact committed plan path.

`candidate-promotion-pr.yml` remains the sole canonical catalog mutation authority. Its queue gate, source preflight, release gates, PR validation, generated-catalog risk classification, and automerge controls remain unchanged.

New-vendor identities from `vendor-breadth-candidates.json` enter the existing vendor-candidate discovery, source-discovery, strict eligibility, materialization-envelope, machine-provisional, observation, quorum, and promotion path. The breadth ledger does not create a second admission or mutation path.

## Consolidation posture

`discovery-mesh.yml` is deliberately one workflow rather than separate discovery, aggregation, intake, and promotion-bridge workflows. Event-specific job guards keep scheduled discovery and merged-intake handoff in one declared authority surface, limiting workflow sprawl.

It is classified as `keep_core`. Retirement is blocked until another workflow demonstrates equivalent uncapped full-catalog sharding, replay-idempotent breadth replenishment, measured health reporting, true no-op suppression, exact candidate-only intake, exact-plan handoff, and preservation of `candidate-promotion-pr.yml` as the sole canonical mutation authority.
