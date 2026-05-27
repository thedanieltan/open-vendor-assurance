# OpenVA System Design

OpenVA is a GitOps evidence registry for public vendor assurance metadata. It is not an app architecture, tenant workflow, private evidence store, or advisory decision engine.

The system exists to turn public vendor-published assurance references into curated metadata, reviewed evidence, deterministic generated outputs, and consumer-neutral release artifacts.

## Architectural pattern

```text
GitOps evidence registry
+ staged promotion
+ deterministic pack generation
+ loop-partitioned CI
+ consumer-neutral adapters
```

OpenVA must not become:

```text
crawler database
SaaS compliance platform
agent-maintained wiki
risk scoring product
document mirror
```

## Artifact authority model

| Area | Path | Authority |
|---|---|---|
| Canonical catalog | `data/vendors/**` | Curated catalog truth after review and merge. |
| Staging and candidates | `maintenance/seeds/vendors/**`, `maintenance/queues/**`, `catalog-batches/**`, generated discovery reports | Proposal input only. |
| Reviewed evidence | `maintenance/reviewed/**` | Validated evidence that can authorize a later controlled write path. |
| Generated outputs | `indexes/**`, `dist/**`, `openva-pack.json` | Generated from canonical YAML. Never hand-edited. |
| Operating knowledge | `docs/**` | Explanatory material unless a document or contract is explicitly named by a tool or test. |
| Control plane | `.github/workflows/**`, `.github/validation-ownership.yaml` | Repository automation and check ownership. Not business logic. |
| Publication | GitHub Releases, release downloads, hosted catalog viewer, site assets | Consumer-facing publication of generated artifacts. Not catalog truth. |

## Core layers

### 1. Canonical catalog layer

`data/vendors/**` is the reviewed source of truth. It should contain vendor, source, artifact, legal entity, entity mention, provenance, candidate source, unavailable source, observation, and change records only after review.

This layer is intentionally strict:

```text
No direct automation writes to main.
No raw document mirroring by default.
No private or gated source contents.
No advisory conclusions.
No customer-specific assessment fields.
```

### 2. Staging and candidate layer

Staging material proposes catalog growth. It does not become catalog truth by existing.

Typical staging inputs are:

```text
maintenance/seeds/vendors/**
maintenance/queues/**
catalog-batches/**
generated discovery reports
candidate promotion proposals
```

The rule is:

```text
Discovery proposes. Promotion writes.
```

Queues decide what to inspect. Seeds identify possible vendors. Reports describe what was found. Reviewed plans authorize promotion. `candidate-promotion-pr.yml` creates reviewable catalog PRs from committed reviewed promotion evidence.

### 3. Review evidence layer

`maintenance/reviewed/**` is the evidence handoff between human or agent review and catalog mutation.

It may contain reviewed promotion plans, reviewed repair plans, no-replacement decisions, deferred decisions, validation reports, and evidence reports. It is not raw reviewer input and it is not canonical catalog truth.

The rule is:

```text
Raw reviewer input is not committed truth.
Validated reviewed artifacts are promotion evidence.
Catalog changes happen only through controlled write paths.
```

### 4. Source maintenance layer

Source maintenance observes, reports, and prepares repairs. It should not become a broad write engine.

The current consolidated source maintenance workflow remains the operational entry point while the catalog is still small enough for broad scheduled reporting. Future sharding should preserve the same boundary:

```text
Observe and report broadly.
Repair narrowly.
Write only through reviewed evidence.
```

A future source operations scheduler may shard verification and reduce unnecessary weekly work, but it must not bypass confirmation history, reviewed evidence, or controlled PR creation.

### 5. Generated export layer

Generated outputs are derived artifacts:

```text
indexes/**
dist/vendors/**
openva-pack.json
release CSV assets
site-consumable JSON
```

Canonical YAML is authored. JSON, indexes, packs, and release assets are generated. Generated drift must block merge.

### 6. Consumer adapter layer

Adapters make OpenVA useful without turning it into an advisory product.

Allowed adapter direction:

```text
CSV export adapter
vendor inventory matcher
domain/entity matcher
DPA/subprocessor/source coverage adapter
public-source evidence bundle adapter
contracting-entity resolution adapter
source freshness adapter
```

Avoid adapter outputs that decide risk, legal sufficiency, approval, vendor suitability, DPIA conclusions, or final processor/subprocessor legal classification. Those decisions belong to downstream user environments.

The rule is:

```text
OpenVA prepares evidence.
Users decide what to do with it.
```

### 7. CI and control-plane layer

Validation should remain strong but easier to diagnose.

`validate.yml` is one workflow with multiple named jobs. Each job owns an operating area and the full suite remains as the global regression signal. This keeps branch protection strict while making failures attributable.

The ownership contract is:

```text
.github/validation-ownership.yaml
```

The workflow inventory contract is:

```text
docs/operations/contracts/workflow-inventory.yaml
```

### 8. Publication layer

Publication consumes generated artifacts. It does not decide catalog truth.

The publication layer includes GitHub Releases, release downloads, the hosted catalog viewer, site pages, live feed, and public source-health snapshot consumption.

## Target flow

```text
taxonomy / coverage model
-> seed identities
-> discovery queue
-> candidate backlog
-> candidate source discovery
-> reviewed promotion evidence
-> candidate-promotion-pr
-> PR safety checks
-> canonical catalog
-> generated indexes / packs / site
-> source maintenance loop
-> repair or truth-state source debt
```

## Write-path rules

OpenVA has narrow write paths:

| Write path | May write | Must not do |
|---|---|---|
| `candidate-promotion-pr.yml` | PR branches from reviewed promotion evidence. | Auto-promote candidates, merge PRs, bypass review. |
| `source-repair-pr.yml` | PR branches from committed reviewed repair evidence. | Run from raw reviewer spreadsheets, merge PRs, bypass source confirmation. |
| `catalog-agent-pr.yml` and `catalog-maintenance-pr.yml` | Human-reviewed support PRs. | Write directly to `main`, bypass validation, or make advisory claims. |
| Publication workflows | Release assets or Pages deployment artifacts. | Create catalog truth or mutate canonical vendor records. |

## Contracts

Machine-readable contracts hold safety boundaries that should not depend on exact prose wording:

```text
.github/validation-ownership.yaml
docs/operations/contracts/workflow-inventory.yaml
docs/operations/contracts/reviewer-decision-handoff.yaml
docs/maintenance/contracts/catalog-growth-scale-readiness.yaml
```

Docs explain the contracts. Tests validate the contracts. Prose can be rewritten for clarity without weakening the control model.

## Design tests

A change is architecturally suspect when it does any of the following:

```text
writes directly to data/vendors/** without a reviewed PR
promotes discovery output without reviewed evidence
commits raw reviewer spreadsheets as truth
turns publication into catalog generation
adds advisory risk, approval, legal, procurement, audit, or compliance conclusions
requires private vendor credentials or gated source contents
makes generated outputs hand-authored
hides a failure inside a generic validation job
```

OpenVA should scale by improving artifact authority, promotion review, deterministic generation, and check ownership before changing the catalog schema.
