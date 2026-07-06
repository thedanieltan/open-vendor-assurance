# Public Roadmap

This roadmap communicates OpenVA direction without creating a support, legal,
compliance, procurement, security, or vendor-certification commitment.

OpenVA is a resolver-first, public-source-only, metadata-first service for vendor-published assurance source references. It helps humans and agents turn bounded vendor identities into structured public source packs. It is not an advisory, scoring, monitoring, or vendor-ranking service.

## North star: vendor source resolution

OpenVA is moving from a catalog-browsing product to a **public-source resolver** for CISO, DPO, procurement, compliance, and agent workflows.

The target flow is:

```text
vendor identity
  -> match / resolve identity
  -> find public source URLs
  -> classify source type
  -> return a structured source pack
  -> export, write back, or queue reusable reference memory
```

The reference cache remains useful, but it is supporting infrastructure: speed, dedupe, identity memory, source-type normalization, negative memory, and reproducibility. The cache is not audit evidence, a canonical legal source, a complete vendor universe, or a vendor approval layer.

## Unified vendor resolution

OpenVA has moved from static catalogue lookup to **reference-cache-first, resolve-on-use** source resolution shared by browser users, API consumers, agents, and MCP integrations (`docs/vendor-resolution.md`). Shipped: the `resolve_vendor_sources` contract, the result-state vocabulary, `cached`/`verify` freshness modes, the proposed source-reference history model, durable idempotent candidate ingress into the existing `maintenance/candidates` queue, the result schema, and a CLI.

The hosted browser Local Matcher is currently cached-only and surfaces a `result_state` per vendor; it does not perform live discovery or lifecycle routing. Scheduled `catalog-growth-discovery` runs hand strict-safe growth to the existing `candidate-promotion-pr.yml` promotion workflow automatically through `catalog-growth-promotion-bridge.yml`, which dispatches the controlled write path only when the strict-growth plan has eligible actions and no hold, active promotion run, or open growth PR blocks it.

A read-only, cached-pack enrichment API extends the match service under `/v1` (catalogue meta, vendor and source lookup, single-vendor match, and a bounded batch `enrich` endpoint) so zero-install spreadsheet and document clients can resolve vendors against the published reference cache without cloning the repository (`docs/resolver-api.md`). It performs no live verification and persists nothing.

A Google Sheets client consumes that `/v1/enrich` endpoint (`integrations/google-sheets/`): from a custom menu a spreadsheet user configures a public-read OpenVA endpoint, selects source types, and writes stable `openva_*` reference columns back into a sheet, without reproducing matcher, ranking, or source-canonicality logic and without embedding an API key. It needs no local Python, Docker, repository checkout, or API secret, but the current release installs manually into a bound Apps Script project; it is a reference and fallback client, not the primary distribution path.

This is not a new advisory or scoring system. OpenVA preserves source-reference and observation history. It does not archive, reproduce, monitor, compare, or interpret historical vendor documents.

## Current state

OpenVA operates an autonomous reference-cache and catalog pipeline for bounded, machine-verifiable public-source locator facts. Discovery, verification, observation, maintenance, promotion, rollback, publication, and audit actions run through declared workflows and pull-request gates. Humans govern code, schemas, authority, permissions, thresholds, and exceptions.

A published record means OpenVA identified and classified a public source reference. It does not mean the vendor is compliant, approved, safe, certified, suitable, or recommended.

## Distribution model

**Primary distribution:** OpenVA HTTP/MCP capabilities composed by users' existing agents with the workspace connectors those agents already control. The agent reads the user's spreadsheet, database, or tickets through its own connector, sends OpenVA only bounded vendor identities, and writes results back itself. OpenVA does not require direct access to Google Drive, Microsoft 365, Notion, Jira, Slack, or any other workspace, and holds no workspace credential. The read-only MCP surface is available over **stdio** and **Streamable HTTP**, and a composite `enrich_inventory` tool serves agent-composed workspace workflows. See [`agent-workspace-composition.md`](agent-workspace-composition.md), [ADR-0002](architecture/decisions/ADR-0002-agent-composed-workspace-integration.md), and [ADR-0003](architecture/decisions/ADR-0003-remote-mcp-product-surface.md).

**Secondary distribution:** thin native/reference clients for environments without capable agents or where organisational policy requires a dedicated client. The Google Sheets client (`integrations/google-sheets/`) is the current example — implemented, manually installed, useful as a tested reference and fallback. Excel, Word, or Google Workspace add-on clients are not the default next step; a native client is built only where demonstrated demand or policy justifies it ([ADR-0005](architecture/decisions/ADR-0005-native-clients-as-secondary-compatibility-surfaces.md)).

The static GitHub Pages viewer, pinned digest-verifiable exports, and the static/local MCP layer remain the reproducible foundation. This positioning describes priority and transport capability; OpenVA does not operate a production hosted endpoint, and live `verify`-mode over remote MCP remains future work governed by [ADR-0001](architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md).

## Hosted public-read deployment

The deployment architecture for ADR-0001's accepted hosted posture is specified in [ADR-0006](architecture/decisions/ADR-0006-hosted-public-read-deployment.md) and [`docs/operations/hosted-deployment-decision.md`](operations/hosted-deployment-decision.md): a portable container (recommended baseline Google Cloud Run; alternatives AWS Lambda and Azure Container Apps), an async `verify`-worker, a TTL-deleted job/result store, and an always-on static fallback. ADR-0006 is **Accepted** and the decision package is complete; acceptance authorises the architecture only — it provisions nothing, creates no provider account, and **OpenVA still does not operate a production hosted endpoint**.

The provider-neutral application path is complete and merged. What remains is the maintainer-gated infrastructure chain: staging, production, production smokes, launch evidence, and programme closeout. These require accepted external deployment choices (provider, region, domain, credentials, spend), plus real provisioning. No slice claims the service is live until launch evidence exists.

## Product phases

### Phase 1 — Positioning correction

Reframe public language from catalog-first to resolver-first.

Deliverables:

- README and roadmap language updated;
- hosted-page language updated;
- catalog described as reference cache / public source memory;
- source URLs described as locator metadata, not audit truth;
- non-advisory boundary preserved.

### Phase 2 — Resolver-first public UI

Make the primary browser journey `Resolve vendor sources`, not `Browse catalog`.

Deliverables:

- paste/upload vendor list entry point;
- role presets for CISO, DPO, and procurement;
- source-type selector;
- source pack result matrix;
- export/write-back oriented copy;
- catalog browse moved to a secondary path.

### Phase 3 — Source pack schema

Standardise human, API, MCP, CSV, and spreadsheet outputs.

Required result fields:

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

Expose cached lookup, on-demand source checks, and async resolver jobs through staging infrastructure.

Minimum endpoints:

```text
POST /resolve
POST /v1/enrich
POST /v1/check
POST /resolve-jobs
GET /resolve-jobs/{id}
GET /resolve-jobs/{id}/results
GET /v1/catalog/meta
```

### Phase 5 — Source map and discovery engine

Use web discovery as a bounded resolver primitive, not as broad scraping or document monitoring.

Discovery sources may include:

```text
sitemap
robots-allowed public links
known path patterns
official-domain search
trust-center subdomain patterns
safe public dynamic page probing
```

Stored output remains locator metadata only: source URL, source type, vendor identity, public access status, status code, redirect target, checked time, confidence, rejection reason, and `not_advice`.

### Phase 6 — Candidate memory as background cache

Turn useful resolver discoveries into reusable reference memory without exposing ordinary users to internal workflow concepts.

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

Make OpenVA useful where teams already work.

Priority surfaces:

1. CSV upload/export;
2. Google Sheets;
3. MCP tools;
4. Notion/Jira through agent-composed workflows;
5. API for internal tools.

### Phase 8 — Role-specific views

Same resolver, different defaults.

- CISO: security page, trust center, compliance page, vulnerability disclosure, certification references.
- DPO: DPA, privacy notice, subprocessor list, data transfer terms, AI/data terms.
- Procurement: vendor identity, official domain, legal entity hints, source coverage, missing/ambiguous/gated flags, export/write-back status.

### Phase 9 — Demand-informed cache growth

Stop optimizing for catalog size. Optimize for resolver usefulness.

Prioritize:

```text
repeated user/agent misses
frequently requested vendors
frequently missing source types
repeated ambiguous identities
candidate URLs rediscovered multiple times
high-use broken/gated/unavailable URLs
```

Scheduled discovery remains, but user and agent demand becomes the signal.

## Priorities

### Resolution usefulness

- make vendor/source resolution the primary workflow;
- clearly distinguish cached, checked-on-demand, and discovered results;
- preserve `matched`, `ambiguous`, and `no_match` as separate states;
- return source packs that are easy to export or write back.

### Source locator quality

- deepen DPA, subprocessor, privacy, security, compliance, and trust-center coverage for commonly requested vendors;
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
- keep every machine-created catalog claim reversible;
- maintain release gates, conformance fixtures, versioning rules, and public security and contribution policies;
- retire obsolete workflows and documentation only after their durable contracts and evidence have been identified.

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
- improving adapter compatibility without changing catalog meaning.

Schema, workflow-authority, permission, and policy-threshold changes require maintainer review and explicit scope.

## Public operation checks

Maintainers should keep the following true:

- project scope and limitations are accurately documented;
- governance, contribution, security, and licensing documents are current;
- generated outputs are reproducible and drift-free;
- validation and release gates pass;
- scheduled workflows are enabled and observable;
- public discovery and agent-export endpoints are available;
- open issues and pull requests do not misrepresent cache completeness, catalog completeness, live verification status, or automation authority.
