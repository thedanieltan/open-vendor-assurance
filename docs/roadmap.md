# OpenVA public roadmap

OpenVA is a resolver-first, public-source-only, metadata-first project for vendor-published assurance source references. This roadmap describes product direction; it does not create a support, legal, compliance, procurement, security, or vendor-certification commitment.

## North star

```text
vendor identity
  -> resolve identity
  -> choose source fields
  -> locate public source URLs
  -> return a structured source pack
  -> export or write back through the user's own tools
```

OpenVA's reference catalog exists to make resolution faster, reproducible, and reusable. It is not a complete vendor universe, a legal archive, a risk score, or a vendor approval layer.

## Current product

OpenVA currently ships:

- a static GitHub Pages resolver and direct source lookup;
- browser-local CSV resolution against a loaded public metadata snapshot;
- configurable source-pack fields and role presets;
- deterministic JSON and CSV catalog exports;
- Python readers, exporters, and inventory matching adapters;
- a read-only MCP server over stdio and Streamable HTTP;
- an optional self-hosted HTTP resolver;
- an uncapped discovery mesh for catalog breadth and source depth;
- controlled candidate, validation, release, and promotion workflows;
- a lightweight workspace dependency graph and affected-test planner.

OpenVA does not currently operate a production central matching service or hosted private-inventory upload service. Private inventories should remain in the user's browser, local environment, agent workspace, or self-hosted environment.

## Distribution model

**Primary distribution:** agent-composed and file-based use. A user's existing agent or application reads its own workspace, sends bounded vendor identities to OpenVA, and writes the returned public source references back under the user's control.

**Secondary distribution:** the browser-local resolver, local command-line tools, the optional self-hosted HTTP service, Google Sheets compatibility, and direct release downloads.

Native workspace clients remain compatibility surfaces rather than a reason for OpenVA to request workspace credentials. OpenVA does not access the user's Google Drive, Microsoft 365, Notion, Jira, Slack, or other private workspace.

## Priority 1 — catalog breadth and depth

The discovery mesh is the principal catalog-growth system.

Current direction:

- discover candidate vendors from resolver demand, public directories, and vendor relationship pages;
- expand subprocessor and public partner relationships into identity signals;
- crawl attested official domains through bounded link graphs, sitemaps, and multilingual classification;
- preserve incomplete identity signals rather than discarding them;
- deduplicate repeated observations in a persistent breadth ledger;
- keep breadth, depth, and source-maintenance queues independently measurable;
- promote only through the existing evidence, release, and pull-request controls.

There is no catalog vendor-count ceiling. Per-host requests, page depth, bytes, concurrency, and retry intervals remain safety budgets rather than catalog caps.

## Priority 2 — resolver usefulness

OpenVA should make it easy for a human or agent to answer:

```text
Which public assurance sources exist for this vendor?
Which expected source types are missing or ambiguous?
Which URL should I open for my own review?
Which snapshot and provenance produced this result?
```

Planned improvements include:

- stronger legal-entity and jurisdiction-aware matching;
- clearer cached, checked-on-demand, and discovered result labels;
- better missing-source and ambiguous-identity explanations;
- simpler source-pack presets and export workflows;
- stable output contracts across browser, CSV, API, MCP, and SDK surfaces.

## Priority 3 — machine consumption

OpenVA will continue to publish deterministic, schema-versioned, digest-verifiable outputs suitable for agents and downstream systems.

Key surfaces:

- `openva-pack.json`;
- `indexes/` and generated vendor shards;
- release CSV and JSON assets;
- MCP over stdio and Streamable HTTP;
- the self-hosted `/v1/enrich` and related resolver endpoints;
- consumer conformance fixtures and adapter contracts.

The repository is now operated as a lightweight single-product monorepo. Dependency-aware pull-request validation is additive: shared contracts and unowned paths still fail safe to the full suite.

## Priority 4 — public reuse

OpenVA should remain easy to fork and build upon.

- Software and project documentation remain under MIT.
- OpenVA-authored catalog metadata is dedicated under CC0 1.0.
- Forks may modify, redistribute, self-host, and commercialize the software and metadata under those permissive terms.
- Third-party vendor documents, marks, and webpages remain outside OpenVA's licence grant.

See `docs/licensing.md`.

## Priority 5 — optional hosted operation

The provider-neutral hosted application path exists, but production operation is not claimed.

A future operated service remains gated by:

```text
provider and region
managed secrets and identity
DNS and TLS
spend and abuse controls
staging deployment
production deployment
production smoke evidence
operational ownership
```

Until those gates are satisfied, public copy must describe OpenVA as a static/browser-local resolver plus local and self-hostable components.

## Product boundary

In scope:

- vendor identity resolution;
- public source URL discovery and classification;
- factual source-access and source-health metadata;
- source-pack generation and export;
- agent and workspace write-back projections;
- reusable public-source candidate memory.

Out of scope:

- document-substance evaluation;
- vendor approval or rejection;
- risk scoring or recommendations;
- legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice;
- private evidence storage;
- authenticated trust-center or NDA-gated collection;
- raw document mirroring by default;
- credentialed scraping, CAPTCHA solving, proxy rotation, or anti-bot bypass.

## Public release posture

OpenVA v0.1.0 was an infrastructure launch with a seed dataset, not a completeness claim. Catalog coverage grows continuously and should never be presented as complete.

The repository includes optional, API-key-gated verify transport for self-hosted use. It does not currently operate a production central matching service.

## Contribution priorities

Useful contributions include:

- adding or correcting a public source reference;
- adding factual metadata for a clearly identified vendor;
- improving source-resolution fixtures or examples;
- improving adapters and compatibility without changing source meaning;
- strengthening deterministic tests and public documentation.

Schema, workflow-authority, permission, licensing, and policy-threshold changes require explicit maintainer review.
