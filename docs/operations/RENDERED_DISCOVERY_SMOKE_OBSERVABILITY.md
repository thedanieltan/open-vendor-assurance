# Rendered discovery acceptance observability

## Purpose

Rendered-discovery execution must leave evidence that separates implementation validation, hosted deployment acceptance, and full-catalog production acceptance. Direct Chromium fixtures do not substitute for hosted or catalog-wide execution evidence.

## Existing control planes

No new workflow, trigger type, or permission is introduced.

- `discovery-ledger-append-pr.yml` retains the pull-request-write reporting lane. Its legacy append job remains restricted to successful `catalog-growth-discovery` runs, while its separate smoke reporter records completed `discovery-mesh` push runs.
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

The dispatched Discovery Mesh run follows the existing production pipeline and publishes `openva-discovery-mesh-aggregate`, including `rendered-discovery-differential.json`. Acceptance review must confirm:

1. The workflow and its `plan`, `discover`, and `aggregate` jobs succeeded.
2. The differential contains 32 shard reports.
3. No vendor limit was supplied.
4. Browser direct-network access remains false.
5. Rendered signals remain noncanonical.
6. Candidate verification, intake, promotion, and canonical mutation remain on their existing governed paths.

Full-catalog acceptance measures actual catalog-wide JavaScript eligibility, render failures, recovered locator signals, verified rendered candidates, and browser cost. A zero-yield differential may still pass operational acceptance, but it does not demonstrate improved source coverage.
