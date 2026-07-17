# Rendered discovery acceptance controller

## Purpose

The rendered-discovery acceptance controller repairs a gap between a successful hosted push smoke and the uncapped full-catalog Discovery Mesh run. The previous bridge could dispatch or skip silently because `gh workflow run` did not persist the resulting run ID outside its private workflow summary.

The controller provides an exact run receipt without changing catalog admission, candidate verification, promotion, or canonical mutation authority.

## Authority and serialization

The controller:

- listens to completed `discovery-mesh` push runs and supports an exact manual recovery input;
- shares the `catalog-growth-promotion-bridge` concurrency group, serializing it with the legacy bridge;
- has Actions write authority only to dispatch `discovery-mesh.yml`;
- has pull-request write authority only to publish the dispatch receipt;
- has read-only repository contents access;
- does not create or merge pull requests;
- does not write catalog, candidate, source, observation, or promotion state.

## Exact acceptance gates

Automatic or manual execution must resolve a source run that is:

1. a `discovery-mesh` run;
2. triggered by `push`;
3. completed successfully;
4. associated with a merged pull request titled exactly `Trigger full-catalog rendered-discovery acceptance`;
5. sourced from a branch beginning `agent/full-catalog-rendered-acceptance-`;
6. authored by the repository owner.

An ordinary crawler merge is ineligible and exits without dispatch.

## Idempotency

Before dispatch, the controller checks for a prior receipt marker on the acceptance pull request. If no receipt exists, it checks for a manually dispatched Discovery Mesh run created after the source smoke completed.

- Zero matching runs: dispatch one run.
- One matching run: adopt it and publish its exact ID.
- More than one matching run: fail closed rather than guess or create another run.

The shared concurrency group prevents the legacy bridge and controller from racing one another.

## Exact run details

The controller calls GitHub's workflow-dispatch REST endpoint with `return_run_details=true` and API version `2026-03-10`. A successful response must include:

- `workflow_run_id`;
- the API run URL;
- the browser-facing run URL.

The controller then verifies that the returned run is a `discovery-mesh` `workflow_dispatch` run.

## Durable receipt

The associated acceptance pull request receives a comment containing:

- source smoke run ID;
- source commit;
- controller state (`dispatched`, `existing_run`, or `existing_receipt`);
- exact full-catalog workflow run ID and URL;
- the default 32-shard, no-vendor-limit profile;
- confirmation that capacity-affecting input overrides were not supplied;
- confirmation that the controller does not write canonical sources.

The same receipt is uploaded as `openva-full-catalog-dispatch-receipt` for 14 days.

## Completion evidence

This controller proves dispatch identity only. The existing Discovery Mesh outcome reporter remains responsible for full-catalog completion evidence, including job outcomes, exact shard count, rendered-discovery differential, browser posture, candidate-intake outcome, and any resulting pull requests.
