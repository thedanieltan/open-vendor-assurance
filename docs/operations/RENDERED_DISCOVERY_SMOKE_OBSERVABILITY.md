# Rendered discovery acceptance observability

## Purpose

Rendered-discovery execution must leave evidence that separates implementation validation, hosted deployment acceptance, and full-catalog production acceptance. Direct Chromium fixtures do not substitute for hosted or catalog-wide execution evidence.

## Existing control planes

No new workflow, trigger type, or permission is introduced.

- `discovery-ledger-append-pr.yml` retains the pull-request-write reporting lane. Its legacy append job remains restricted to successful `catalog-growth-discovery` runs, while its separate Discovery Mesh reporter records completed push and manually dispatched acceptance runs.
- `catalog-growth-promotion-bridge.yml` retains the actions-write dispatch lane. Its original promotion job remains restricted to `catalog-growth-discovery`; a separate exact-gated job may dispatch one full-catalog Discovery Mesh acceptance run.

## Hosted deployment smoke

A watched crawler merge triggers the existing one-shard, five-vendor push smoke. The reporter records:

- workflow run ID, attempt, URL, conclusion, and head commit;
- individual job outcomes;
- the one-shard, five-vendor diagnostic profile;
- aggregate-artifact availability;
- rendered-discovery differential counters;
- browser direct-network and canonical-write posture;
- the associated merged pull request.

Hosted deployment acceptance requires successful `plan`, `discover`, and `aggregate` jobs, the aggregate artifact, and `rendered-discovery-differential.json`. Candidate-intake mutation remains disabled for this push-only probe.

## Controlled full-catalog dispatch

A successful push smoke normally causes no additional run. The actions-write bridge dispatches full-catalog acceptance only when every gate below succeeds:

- the upstream workflow is `discovery-mesh`;
- the upstream source event is `push`;
- the upstream run concluded successfully;
- its commit belongs to a merged pull request titled exactly `Trigger full-catalog rendered-discovery acceptance`;
- the pull-request branch begins `agent/full-catalog-rendered-acceptance-`;
- the pull-request author is the repository owner;
- no prior `workflow_dispatch` Discovery Mesh run exists for the same head SHA.

The bridge calls `discovery-mesh.yml` on `main` without input overrides using its existing GitHub Actions authority. The target workflow therefore uses its default 32-shard matrix and leaves the vendor limit blank.

## Full-catalog evidence

For a completed `workflow_dispatch` Discovery Mesh run, the existing reporter downloads `openva-discovery-mesh-aggregate` and publishes:

- workflow run ID, attempt, source event, conclusion, and head commit;
- every job outcome;
- the default 32-shard, no-vendor-limit profile;
- the aggregate shard-report count;
- every rendered-discovery differential counter;
- browser direct-network and canonical-write posture;
- the production candidate-intake posture.

The evidence is written to the associated pull request and workflow summary before the reporter evaluates acceptance. Full-catalog acceptance requires:

1. The workflow and its `plan`, `discover`, and `aggregate` jobs succeeded.
2. The aggregate artifact includes `rendered-discovery-differential.json`.
3. The differential contains exactly 32 shard reports.
4. No vendor limit was supplied.
5. Browser direct-network access remains false.
6. Rendered signals remain noncanonical.
7. Candidate verification, intake, promotion, and canonical mutation remain on their existing governed paths.

A failed workflow, missing artifact, skipped required job, or unexpected shard count is published as evidence before the reporter fails its acceptance gate.

Full-catalog acceptance measures actual catalog-wide JavaScript eligibility, render failures, recovered locator signals, verified rendered candidates, and browser cost. A zero-yield differential may still pass operational acceptance, but it does not demonstrate improved source coverage.
