# Catalog Growth Scale Readiness

This guide explains how catalog growth should scale after the initial seed files are complete.

It is documentation only. It does not create a queue, run discovery, create pull requests, run promotion, or write canonical vendor/source records.

It complements the discovery queue; it is not input to the queue validator.

## Operating model

Catalog growth uses this path:

```text
seed identities
-> discovery queue
-> reviewed promotion evidence
-> controlled promotion
-> source maintenance
```

Seed files identify possible vendors. Discovery finds possible sources. Reviewed plans under `maintenance/reviewed/` provide promotion evidence. `candidate-promotion-pr.yml` remains the controlled catalog write path.

## After bootstrap seeds

Seed files are the bootstrap layer, not the permanent growth mechanism.

After a coverage lane has enough seed coverage, new candidates should be selected from queue and backlog signals:

- coverage gaps
- source-health budget
- candidate backlog state
- official-domain authority
- core source availability
- duplicate or entity-family risk

## Candidate lifecycle

```text
seeded
-> discovered
-> deduplicated
-> source_discovered
-> review_ready
-> approved_for_promotion
-> promoted
-> observed
-> maintenance_required
```

## Core source scope

Start with the core vendor-assurance source set:

```text
dpa
subprocessors_list
privacy_notice
security_page
```

These are sufficient for vendor assurance intake and evidence preparation.

Extended source types such as trust centers, certification references, product terms, AI terms, and data transfer terms should be deferred until the core loop is stable.

## Promotion readiness

A candidate is not promotion-ready just because it has a website.

Promotion requires reviewed evidence for personal-data relevance, official-domain authority, useful public source coverage, coverage-gap fit, dedupe confidence, and acceptable source-health impact.

Promotion is blocked when the official domain is unknown, the candidate duplicates an existing vendor/entity family, no public source candidates are available, only gated materials are available, raw document mirroring would be required, source-health debt exceeds the agreed budget, or the reviewed plan is not committed under `maintenance/reviewed/`.

## Batching

Keep reviewed promotion batches small enough for review.

The generated proposal default remains 50 candidate-promotion actions per plan. The preferred initial reviewed batch size is 25 candidate-promotion actions per reviewed plan.

## Guardrails

- Seed files are staging records, not catalog records.
- Discovery output is staging evidence, not catalog truth.
- Candidate promotion requires reviewed plans under `maintenance/reviewed/`.
- `candidate-promotion-pr.yml` is the controlled catalog write path.
- Catalog growth should slow down when source-health debt exceeds the agreed budget.
