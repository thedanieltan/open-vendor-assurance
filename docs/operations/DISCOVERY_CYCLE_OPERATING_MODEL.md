# Discovery Cycle operating model

## Purpose

Discovery Cycle is the vendor-growth convergence layer between the existing full-catalog `discovery-mesh.yml` crawler and OpenVA's existing unified candidate lifecycle.

It removes the need for a second scheduled vendor-discovery authority and removes broad rediscovery from the promotion handoff. It does not create a new catalog mutation path.

## Authority chain

```text
discovery-mesh.yml
  -> exact current-attempt aggregate artifact
  -> rotating bounded vendor workset
  -> one vendor-candidate source-discovery pass
  -> vendor_resolution.CatalogQueueIngress
  -> maintenance/candidates/*.json (noncanonical)
  -> candidate-intake PR + existing automerge:candidate-intake lane
  -> autonomous-catalog-growth.yml
  -> candidate-bound candidate-promotion-pr.yml
  -> machine-provisional Catalog PR
  -> existing delay / quorum / observation lifecycle
```

`candidate-promotion-pr.yml` remains the sole canonical catalog mutation authority.

## Discovery authority

`discovery-mesh.yml` remains the network discovery authority for full-catalog depth and vendor-breadth replenishment. Discovery Cycle consumes only successful scheduled or explicitly dispatched production Discovery Mesh runs on `main`.

A manual recovery names one exact Discovery Mesh run ID. No successful/latest run is inferred.

The aggregate artifact is bound to the current source-run attempt by `startedAt`, must be unique for that attempt, and is downloaded by exact artifact ID. Reruns therefore cannot consume a same-named artifact from an older attempt.

## Fair bounded worksets

`max_vendors_per_discovery_run` remains a runtime safety bound, not a catalog ceiling. Discovery Cycle partitions the complete current breadth-candidate set into deterministic bounded buckets and advances by the Discovery Mesh run number. It therefore does not repeatedly consume the first N candidates forever.

Candidates already canonical by vendor ID or domain are removed before network work.

## Unified candidate convergence

Scheduled discovery projects evidence into the existing WP40 unified candidate schema and writes through `vendor_resolution.CatalogQueueIngress`. Candidate identity is stable across cycles, so later source evidence merges into the same candidate rather than creating a parallel queue.

Only materialization-qualified source types count as usable assurance sources. Incomplete country identity remains in the breadth-resolution plane and is not persisted as an immutable incomplete candidate identity.

Candidate records remain noncanonical. The candidate-intake lane recomputes schema, identity and eligibility before merge. Once a candidate is workflow-visible, the existing autonomous growth controller binds the exact candidate ID, path, content digest, origin and selected vendor through the candidate-bound mutation path.

## Discovery data plane

Raw breadth projections, worksets, source-discovery reports and ingress reports stay in GitHub Actions artifacts. The repository receives only bounded unified candidate records required by the existing lifecycle.

Each Discovery Cycle produces a digest-bound bundle manifest containing:

- source Discovery Mesh run ID and attempt;
- source commit SHA;
- cycle/run number;
- SHA-256 digests of the fresh breadth projection, workset, source-discovery report and ingress report;
- one bundle SHA-256 digest.

## Failure posture

The cycle fails closed on:

- wrong workflow, branch, event or conclusion;
- a source commit outside current `main` history;
- missing or ambiguous current-attempt aggregate artifacts;
- artifact pagination ambiguity;
- invalid queue bounds;
- out-of-scope staging paths;
- candidate schema, identity or eligibility inconsistency;
- absence of the workflow-triggering autonomous PR token.

A cycle with no selected candidates or no candidate-state changes is a clean no-op.

## Legacy retirement gate

`catalog-growth-discovery.yml` and its strict-growth promotion bridge are legacy duplicate authorities. They must not be removed merely because Discovery Cycle is implemented.

Retirement requires live evidence of the replacement chain:

1. a scheduled Discovery Mesh run is consumed automatically;
2. the rotating workset performs source discovery once;
3. a governed candidate-intake PR opens and merges;
4. `autonomous-catalog-growth.yml` selects the exact workflow-visible candidate;
5. candidate-bound `candidate-promotion-pr.yml` opens the machine-provisional Catalog PR;
6. the existing delay/quorum lifecycle advances without bypass;
7. canonical vendor count grows above the prior 500 baseline;
8. a later cycle does not fall back to first-N starvation or a parallel vendor queue.

Only after this evidence is recorded should the redundant scheduled legacy crawler and strict-growth bridge be disabled/retired in a follow-up workflow-governance change.
