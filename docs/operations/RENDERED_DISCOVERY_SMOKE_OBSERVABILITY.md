# Rendered discovery smoke observability

## Purpose

The read-only rendered-discovery deployment smoke must leave durable evidence whether it succeeds, fails, is cancelled, or completes without its expected artifact. Implementation checks and direct Chromium fixtures do not substitute for hosted execution evidence.

## Existing control plane

The existing `discovery-ledger-append-pr.yml` workflow listens for both `catalog-growth-discovery` and `discovery-mesh` completions. This does not add another workflow, trigger type, or permission surface.

The legacy discovery-ledger append job remains restricted to successful `catalog-growth-discovery` runs. A separate report-only job handles completed `discovery-mesh` runs whose originating event was `push`.

## Durable evidence

For every completed push smoke, the reporter records:

- workflow run ID, attempt, URL, conclusion, and head commit;
- individual job outcomes;
- the one-shard, five-vendor diagnostic profile;
- whether the aggregate artifact was available;
- every rendered-discovery differential counter when available;
- browser direct-network and canonical-write posture;
- the associated merged pull request when GitHub exposes one for the head commit.

The reporter posts the record to the associated pull request and also writes it to its workflow summary.

## Acceptance

Hosted deployment acceptance requires all of the following:

1. The discovery-mesh workflow concludes successfully.
2. The `plan`, `discover`, and `aggregate` jobs conclude successfully.
3. The `openva-discovery-mesh-aggregate` artifact exists.
4. The artifact includes `rendered-discovery-differential.json`.
5. Candidate-intake mutation remains disabled for the push smoke.

A missing artifact, skipped required job, cancellation, or failed workflow is recorded and causes the reporter job to fail after publishing the evidence.

Full-catalog production acceptance remains a separate scheduled or manually dispatched uncapped run.
