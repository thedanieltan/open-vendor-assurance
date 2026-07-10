# Public Roadmap

This roadmap communicates OpenVA direction without creating a support, legal,
compliance, procurement, security, or vendor-certification commitment.

OpenVA is a resolver-first, public-source-only, metadata-first project for vendor-published assurance source references. It helps humans and agents turn bounded vendor identities into structured public source packs. It is not an advisory, scoring, monitoring, or vendor-ranking service.

## North star: vendor source resolution

OpenVA is a **public-source resolver** for CISO, DPO, procurement, compliance, and agent workflows.

The target flow is:

```text
vendor identity
  -> match / resolve identity
  -> choose source fields
  -> find public source URLs
  -> classify source type
  -> return a structured source pack
  -> export, write back, or queue reusable reference memory
```

The reference cache remains supporting infrastructure: speed, dedupe, identity memory, source-type normalization, negative memory, and reproducibility. The cache is not audit evidence, a canonical legal source, a complete vendor universe, or a vendor approval layer.

## Closeout status

The resolver-first Phases 1-9 are complete as implementation slices. See `docs/resolver-first-closeout.md` for the consolidation record.

| Phase | Merged PR | Status |
| --- | --- | --- |
| Phase 1 — Positioning correction | #518 | Complete |
| Phase 2 — Resolver-first public UI | #520 | Complete |
| Phase 3 — Source pack schema | #521 | Complete |
| Phase 4 — Hosted resolver staging | #522 | Staging smoke plan complete; production hosted launch not claimed |
| Phase 5 — Source map and discovery engine | #523 | Complete |
| Phase 6 — Candidate memory as background cache | #524 | Complete |
| Phase 7 — Workspace write-back | #525 | Connector-neutral projection complete |
| Phase 8 — Configurable source pack builder | #526 | Complete |
| Phase 9 — Resolver-usefulness prioritisation | #527 | Complete |

This closeout does not create a Phase 10. Future work should be operational launch evidence, bug fixes, wording reconciliation, drift-prevention tests, or concrete user-driven adapter/workspace compatibility work.

## Current state

OpenVA currently ships:

- static GitHub Pages browser UI;
- browser-local CSV resolution against loaded public metadata;
- configurable source-pack field selection;
- direct public source lookup;
- source-pack result schema;
- static/digest-verifiable agent exports;
- release CSV assets;
- connector-neutral workspace write-back row projection;
- bounded source-map discovery primitives;
- candidate memory as background reusable public-source memory;
- resolver-usefulness prioritisation for already-eligible background candidates;
- self-hostable HTTP/MCP/service components.

The browser page is static and browser-local. It does not upload private vendor inventories, run live discovery from the page, or operate a production hosted verify endpoint.

## Distribution model

Primary distribution: agent-composed workspace integration. A user's existing agent or application reads the workspace through a connector it already controls, sends OpenVA only bounded vendor identities, and writes returned public source references back under the user's control.

Secondary distribution: browser-local resolution, local files and command-line tools, the optional self-hosted HTTP service, Google Sheets compatibility, and release downloads.

The read-only MCP surface supports stdio and Streamable HTTP. OpenVA does not require direct access to Google Drive, Microsoft 365, Notion, Jira, Slack, or another private workspace.

## Hosted resolver deployment status

The provider-neutral hosted application path and staging smoke plan exist, but OpenVA does not currently claim an operated production hosted resolver.

Hosted/live operation remains gated by:

```text
provider
region
domain
credentials
spend controls
staging deployment
production deployment
production smokes
launch evidence
operational ownership
```

Until those gates are complete, use this wording:

```text
OpenVA ships a static/browser-local resolver UI and self-hostable resolver components.
It does not currently operate a production hosted private-inventory upload or live verify endpoint.
```

## Product boundary

In scope:

- resolving bounded vendor identities;
- locating public vendor-published assurance source URLs;
- classifying source types;
- separating found, missing, ambiguous, gated, unavailable, candidate-found, and not-checked states;
- shaping source-pack output for humans, APIs, MCP tools, CSV, spreadsheets, and agents;
- exporting public-source locator metadata;
- background reusable memory through candidate records and controlled PR gates.

Out of scope:

- evaluating document substance;
- approving or rejecting vendors;
- risk scoring;
- legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice;
- private evidence storage;
- authenticated trust-center collection;
- NDA-gated material;
- raw document mirroring by default;
- continuous content monitoring;
- legal document versioning.

## Correct user-facing model

The user-facing model is:

```text
vendor list
  -> choose source fields
  -> resolve public source references
  -> review found / missing / ambiguous / gated / unavailable states
  -> export source pack
  -> optionally write back through the user's own workspace or agent
```

Role labels are presets only:

- CISO preset: security page, trust center, compliance page, vulnerability disclosure, certification references;
- DPO preset: DPA, privacy notice, subprocessor list, data transfer terms, AI/data terms;
- procurement preset: vendor identity, official domain, legal entity hints, source coverage, missing/ambiguous/gated flags, export/write-back status.

Users can include or remove fields. Presets are not separate products, approval paths, or conclusions.

## Completed product phases

### Phase 1 — Positioning correction

Public language was reframed from catalog-first to resolver-first. Source URLs are described as locator metadata, not audit truth. The non-advisory boundary remains explicit.

### Phase 2 — Resolver-first public UI

The primary browser journey became resolving vendor sources and exporting source packs. Browse/search remains a secondary utility path.

### Phase 3 — Source pack schema

OpenVA now has a public source-pack result contract for humans, API/MCP consumers, CSV/spreadsheet exports, and agents. Required result fields include:

```text
match_status
source_type
source_url
result_state
mode
confidence
public_access_status
checked_at
snapshot_id
candidate_queued
not_advice
```

### Phase 4 — Hosted resolver staging

The staging smoke plan defines the expected hosted resolver evidence contract and endpoint mapping:

```text
POST /resolve
POST /v1/enrich
POST /v1/check
POST /resolve-jobs
GET /resolve-jobs/{id}
GET /resolve-jobs/{id}/results
GET /v1/catalog/meta
```

This phase did not provision production or claim an operated hosted endpoint.

### Phase 5 — Source map and discovery engine

Bounded discovery emits locator metadata only: source URL, source type, vendor identity, public access status, status code, redirect target, checked time, confidence, rejection reason, and `not_advice`.

Discovery remains a resolver primitive, not broad scraping, content monitoring, or document interpretation.

### Phase 6 — Candidate memory as background cache

Useful resolver discoveries can become reusable public-source memory without exposing ordinary users to internal workflow concepts.

User-facing statuses:

```text
queued for reuse
already known
candidate found
not queued: ambiguous
not queued: unsafe
not queued: insufficient evidence
```

Internal mutation continues through candidate records, eligibility checks, PRs, release gates, and controlled automerge.

### Phase 7 — Workspace write-back

OpenVA now has a connector-neutral source-pack write-back row projection for CSV, spreadsheets, APIs, MCP tools, and agent-composed workspace workflows.

Priority surfaces remain:

1. CSV upload/export;
2. Google Sheets;
3. MCP tools;
4. Notion/Jira through agent-composed workflows;
5. API for internal tools.

### Phase 8 — Configurable source pack builder

OpenVA uses one configurable source-pack builder. CISO, DPO, and procurement are presets only. Users can add or remove source fields before export.

### Phase 9 — Resolver-usefulness prioritisation

Background reusable-memory prioritisation now uses resolver-usefulness signals, including:

```text
repeated user/agent misses
frequently requested vendors
frequently missing source types
repeated ambiguous identities
candidate URLs rediscovered multiple times
high-use broken/gated/unavailable URLs
```

Demand signals only prioritise already-eligible candidates. They do not make unsafe, ambiguous, gated, or insufficient-evidence candidates selectable.

## Priorities after closeout

### Operational launch evidence

- complete staging only when provider, region, domain, credentials, and spend controls exist;
- run staging smokes against the documented evidence contract;
- do not claim production hosted operation until launch evidence exists.

### Resolution usefulness

- make vendor/source resolution the primary workflow;
- clearly distinguish cached, checked-on-demand, and discovered results;
- preserve `matched`, `ambiguous`, and `no_match` as separate states;
- return source packs that are easy to export or write back.

### Source locator quality

- deepen DPA, subprocessor, privacy, security, compliance, and trust-center source coverage for commonly requested vendors;
- prefer authoritative vendor-controlled sources over inferred URLs;
- record moved, unavailable, gated, and ambiguous source-locator status;
- keep discovery and maintenance bounded by host, URL, byte, and time limits.

### Machine consumption

- keep static exports deterministic, schema-versioned, and digest-verifiable;
- maintain the hosted vendor pages, agent index, discovery manifest, sitemap, robots file, and `llms.txt` surface;
- publish stable MCP and package distributions when release operations are ready;
- provide importer fixtures and inventory-matching examples without introducing risk scoring or organization-specific decisions.

### Governance and compatibility

- preserve deny-by-default workflow authority;
- require independent evidence and separation of duties for autonomous promotion;
- keep every machine-created source claim reversible;
- maintain release gates, conformance fixtures, versioning rules, and public security and contribution policies;
- retire obsolete workflows and documentation only after their durable contracts and evidence have been identified.

### Public reuse

- keep software and project documentation under MIT;
- dedicate OpenVA-authored catalog metadata and generated data under CC0 1.0 Universal;
- permit public and private forks, modification, redistribution, self-hosting, and commercial use under those permissive terms;
- exclude vendor-owned documents, trademarks, webpages, and other third-party materials from OpenVA's licence grant.

See `docs/licensing.md`.

## Operating boundaries

OpenVA will continue to use:

- public sources only;
- metadata-first records rather than raw document mirroring;
- pull requests for every repository mutation;
- machine-readable authority contracts and release gates;
- bounded automation that fails closed on ambiguity;
- human governance for policy, authority, schema, workflow, and permission changes.

## Not on the roadmap

OpenVA does not plan to provide:

- legal, compliance, procurement, audit, security, KYC, AML, sanctions, or vendor-risk advice;
- vendor approval badges, rankings, recommendations, or risk scores;
- customer-specific agreement analysis;
- authenticated trust-center or private-portal collection;
- credentialed scraping, CAPTCHA solving, proxy rotation, or anti-bot bypass;
- private evidence storage;
- raw document mirroring by default;
- continuous content monitoring or legal document versioning.

## Contribution priorities

Good contributions are bounded and testable, for example:

- correcting a public source reference;
- adding public metadata for a clearly identified vendor source;
- improving source-resolution fixtures, examples, or factual documentation;
- adding tests around existing behavior;
- improving adapter compatibility without changing source meaning.

Schema, workflow-authority, permission, and policy-threshold changes require maintainer review and explicit scope.

## Public operation checks

Maintainers should keep the following true:

- project scope and limitations are accurately documented;
- governance, contribution, security, and licensing documents are current;
- generated outputs are reproducible and drift-free;
- validation and release gates pass;
- scheduled workflows are enabled and observable;
- public discovery and agent-export endpoints are available;
- open issues and pull requests do not misrepresent cache completeness, live verification status, hosted deployment status, or automation authority.
