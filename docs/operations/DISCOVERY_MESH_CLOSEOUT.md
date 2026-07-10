# Discovery Mesh Programme Closeout

## Status

Implementation is complete when the final closeout pull request merges. Production acceptance remains pending until the first successful full-catalog `discovery-mesh.yml` run executes from the merged revision and satisfies the live acceptance gates below.

No catalog vendor-count ceiling exists. Scaling is controlled through deterministic sharding and per-vendor network-safety budgets rather than truncating the catalog or provider candidate supply.

## Delivered work packages

| Work package | Delivery |
|---|---|
| Discovery mesh core | Multilingual first-party HTML graph discovery, delegated-host evidence, relationship extraction, discovery memory, and breadth/depth planning. |
| Unbounded sharded runner | Exhaustive catalog partitioning across deterministic shards with no default vendor limit. |
| Scheduled activation and intake controls | Daily full-catalog execution, candidate-only intake, guarded promotion handoff, and preservation of the existing canonical mutation authority. |
| Breadth providers and replenishment | Resolver-demand, public-directory, and relationship provider contracts; replay-idempotent identity ledger; unresolved queue; uncapped candidate projection; existing vendor-discovery bridge. |
| Production health and closeout | Catalog, crawl, provider, and admission metrics; exact candidate staging; true no-op suppression; workflow evidence and operating model. |

## Success metrics

Every aggregate run emits `discovery_mesh_health` JSON and Markdown artifacts containing these load-bearing measures:

- catalog vendor count and source count;
- percentage of catalog vendors with at least one canonical source;
- provider-discovered entity count;
- source-discovery-ready provider candidate count;
- unresolved identity count retained for further resolution;
- pages and requests issued;
- locator signals and verified source candidates produced;
- viable reviewed promotion actions;
- locator signals per request;
- verified candidates per request;
- viable promotions per verified candidate;
- changed and unchanged stable breadth outputs;
- explicit `catalog_vendor_count_cap: null`.

The metrics are diagnostic, not admission thresholds. Poor yield must lead to provider, classifier, crawl-frontier, or resource-budget tuning; it must not automatically weaken source authority, identity, verification, or promotion controls.

## Live acceptance gates

The first production acceptance run must demonstrate all of the following:

1. The shard matrix uses the configured production shard count and contains no scheduled vendor limit.
2. Every shard completes or reports a visible failure; aggregate processing does not silently omit a failed shard.
3. The aggregate job emits source discovery, vendor breadth replenishment, and health artifacts.
4. The health report records the current catalog breadth, source depth, provider queue state, and crawl/admission yield.
5. A true no-op run creates no candidate-intake pull request.
6. A run with breadth-state changes creates an intake pull request containing only changed stable breadth projections unless viable source actions also exist.
7. A run with viable source actions stages only candidate records referenced by the exact reviewed plan.
8. A breadth-only intake merge does not dispatch canonical mutation.
9. A source-plan intake merge dispatches the existing `candidate-promotion-pr.yml` workflow with the exact committed plan path.
10. Replaying identical provider signals does not inflate demand or observation counts and does not create stable-output drift.
11. Existing validation, source preflight, release gates, machine-provisional admission, observation, quorum, and controlled automerge remain authoritative.

The acceptance evidence must cite the actual workflow run ID, commit SHA, aggregate artifact name, health status, intake decision, and any resulting pull request numbers. These values must not be prefilled or inferred before the run occurs.

## Tuning policy

Production tuning follows measured outcomes:

- increase or decrease shard count to control wall-clock duration and runner concurrency;
- adjust per-vendor page, request, link, locator, or delegated-host limits when crawl efficiency and missed-source evidence justify it;
- improve multilingual terms and link ranking when relevant pages are observed but not selected;
- add or refine provider adapters when breadth growth is constrained by identity-signal supply;
- prioritize unresolved identity states according to repeated demand, provider independence, and evidence completeness;
- retain an uncapped catalog and uncapped provider candidate projection.

No tuning action may convert an unverified signal into a catalog fact or bypass the existing admission pipeline.

## Provider activation posture

Relationship-graph signals are produced automatically by the scheduled mesh.

Resolver-demand and public-directory adapters are implemented against the same provider contract. They require an authorized producer or public feed to supply their input artifacts. Activating those producers does not require another identity or catalog admission path; their signals enter the same replay-idempotent ledger and existing vendor-candidate discovery pipeline.

## Programme boundary

OpenVA continues to resolve vendor identity and locate vendor-published public assurance sources. The discovery mesh does not assess vendor risk, determine contractual parties, certify compliance, recommend procurement action, or provide legal, audit, security, KYC, or AML conclusions.
