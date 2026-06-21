# Public Roadmap

This roadmap communicates OpenVA direction without creating a support, legal,
compliance, procurement, security, or vendor-certification commitment.

OpenVA is a public-source-only, metadata-first registry of vendor-published
assurance references. It is not an advisory or vendor-ranking service.

## Unified vendor resolution

OpenVA has moved from static catalogue lookup to **catalogue-first,
live-refresh-on-use** resolution shared by browser users, API consumers, agents,
and MCP integrations (`docs/vendor-resolution.md`). Shipped: the
`resolve_vendor_sources` contract, the result-state vocabulary, `cached`/`verify`
freshness modes, the proposed source-reference history model, durable idempotent
candidate ingress into the existing `maintenance/candidates` queue (the same one
`autonomous-catalog-growth.yml` consumes), the result schema, and a CLI. The
hosted browser Local Matcher is cached-only and surfaces a `result_state` per
vendor; it does not perform live discovery or lifecycle routing. Scheduled
`catalog-growth-discovery` runs now hand strict-safe growth to the existing
`candidate-promotion-pr.yml` promotion workflow automatically through
`catalog-growth-promotion-bridge.yml`, which dispatches the controlled write path
only when the strict-growth plan has eligible actions and no hold, active
promotion run, or open growth PR blocks it (and only for scheduled discovery
runs). A read-only, cached-pack enrichment API now extends the match service under
`/v1` (catalogue meta, vendor and source lookup, single-vendor match, and a bounded
batch `enrich` endpoint) so zero-install spreadsheet and document clients can resolve
vendors against the published catalogue without cloning the repository
(`docs/resolver-api.md`); it performs no live verification and persists nothing. A Google
Sheets client now consumes that `/v1/enrich` endpoint (`integrations/google-sheets/`): from
a custom menu a spreadsheet user configures a public-read OpenVA endpoint, selects source
types, and writes stable `openva_*` reference columns back into a sheet, without reproducing
any matcher, ranking, or canonicality logic and without embedding an API key. It needs no
local Python, Docker, repository checkout, or API secret, but the current release installs
manually into a bound Apps Script project; it is a reference and fallback client, not the
primary distribution path (see Distribution model below), and a zero-install Google
Workspace add-on remains a future objective, not a shipped capability.

This is not a new advisory or scoring system. OpenVA preserves source-reference
and observation history; it does not archive or reproduce historical vendor
documents.

### Autonomous candidate-bound promotion

Candidate intake is now an end-to-end, fail-closed control path
(`docs/candidate-intake.md`). The external boundary (`candidate-intake-pr.yml`)
stages non-canonical candidate records via the canonical ingress and opens a
PR with a workflow-triggering token; the `agent-automerge` candidate-intake job
recomputes eligibility and identity from each persisted record — never trusting
the stored `eligibility_state` — and auto-merges only after the guard and
release gate pass. The growth controller then recomputes the selected
candidate's eligibility, binds its identity and SHA-256 content digest, and
dispatches `candidate-promotion-pr.yml` in `candidate-bound` mode, which verifies
the binding on the exact head and materializes exactly that candidate as one
`machine_provisional` vendor (selected == mutated). Candidate records stay
non-canonical; catalogue truth still changes only through the established PR path,
and promotion to a terminal status remains the independent quorum. This completes
autonomous candidate promotion up to a reviewable, bound catalogue PR; it is not
production hosting, and OpenVA's hosted `/v1` API and remote MCP are not live.

## Distribution model

**Primary distribution:** OpenVA HTTP/MCP capabilities composed by users' existing
agents with the workspace connectors those agents already control. The agent reads
the user's spreadsheet, database, or tickets through its own connector, sends OpenVA
only bounded vendor identities, and writes results back itself. OpenVA does not
require direct access to Google Drive, Microsoft 365, Notion, Jira, Slack, or any
other workspace, and holds no workspace credential. The read-only MCP surface is
available over **stdio** and **Streamable HTTP**, and a composite `enrich_inventory`
tool serves agent-composed workspace workflows. See
[`agent-workspace-composition.md`](agent-workspace-composition.md) and
[ADR-0002](architecture/decisions/ADR-0002-agent-composed-workspace-integration.md)
/ [ADR-0003](architecture/decisions/ADR-0003-remote-mcp-product-surface.md).

**Secondary distribution:** thin native/reference clients for environments without
capable agents or where organisational policy requires a dedicated client. The
Google Sheets client (`integrations/google-sheets/`) is the current example —
implemented, manually installed, useful as a tested reference and fallback. Excel,
Word, or Google Workspace add-on clients are not the default next step; a native
client is built only where demonstrated demand or policy justifies it
([ADR-0005](architecture/decisions/ADR-0005-native-clients-as-secondary-compatibility-surfaces.md)).

The static GitHub Pages viewer, pinned digest-verifiable exports, and the static/
local MCP layer remain the canonical reproducible foundation. This positioning
describes priority and transport capability; OpenVA does not operate a production
hosted endpoint, and live `verify`-mode over remote MCP remains future work governed
by [ADR-0001](architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md).

### Hosted public-read deployment (decision-ready)

The deployment architecture for ADR-0001's accepted hosted posture is specified in
[ADR-0006](architecture/decisions/ADR-0006-hosted-public-read-deployment.md) and
[`docs/operations/hosted-deployment-decision.md`](operations/hosted-deployment-decision.md):
a portable container (recommended baseline Google Cloud Run; alternatives AWS Lambda
and Azure Container Apps), an async `verify`-worker, a TTL-deleted job/result store,
and an always-on static fallback. ADR-0006 is **Accepted** (the architecture decision)
and remains decision-only — acceptance provisions nothing, creates no provider account,
and OpenVA still does not operate a production hosted endpoint. The dependency-ordered implementation slices are in
[`docs/operations/hosted-deployment-implementation-plan.md`](operations/hosted-deployment-implementation-plan.md):
with ADR-0006 accepted, the in-repo **code/CI slices (WP-02A–02E and WP-02L)** are
buildable now. The remaining slices wait on infrastructure: **WP-02F (staging) and
WP-02G (production) require the maintainer-accepted external deployment choices**
(provider, region, domain, credentials, spend), and **WP-02H, WP-02I, WP-02J, and
WP-02K depend on that staging/production infrastructure** and follow it.

## Current state

OpenVA operates an autonomous catalog pipeline for bounded, machine-verifiable
public-source facts. Discovery, verification, observation, maintenance,
promotion, rollback, publication, and audit actions run through declared
workflows and pull-request gates. Humans govern code, schemas, authority,
permissions, thresholds, and exceptions.

The catalog remains an evolving public dataset. A published record means OpenVA
identified and classified a public source reference; it does not mean the vendor
is compliant, approved, safe, certified, suitable, or recommended.

## Priorities

### Coverage quality

- deepen DPA, subprocessor, privacy, security, compliance, and trust-center
  coverage for commonly used vendors;
- expand regional and industry coverage through bounded catalog batches;
- prefer authoritative vendor-controlled sources over inferred URLs;
- preserve native-language source metadata where available.

### Source freshness and reliability

- increase recent observation coverage;
- detect moved, unavailable, bot-protected, and materially changed sources;
- repair or quarantine sources only through evidence-bearing workflows;
- keep discovery and maintenance bounded by host, URL, byte, and time limits.

### Machine consumption

- keep static exports deterministic, schema-versioned, and digest-verifiable;
- maintain the hosted vendor pages, agent index, discovery manifest, sitemap,
  robots file, and `llms.txt` surface;
- publish stable MCP and package distributions when release operations are ready;
- provide importer fixtures and inventory-matching examples without introducing
  risk scoring or organization-specific decisions.

### Governance and compatibility

- preserve deny-by-default workflow authority;
- require independent evidence and separation of duties for autonomous promotion;
- keep every machine-created catalog claim reversible;
- maintain release gates, conformance fixtures, versioning rules, and public
  security and contribution policies;
- retire obsolete workflows and documentation only after their durable contracts
  and evidence have been identified.

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

- legal, compliance, procurement, audit, security, KYC, AML, sanctions, or
  vendor-risk advice;
- vendor approval badges, rankings, recommendations, or risk scores;
- customer-specific agreement analysis;
- authenticated trust-center or private-portal collection;
- credentialed scraping, CAPTCHA solving, proxy rotation, or anti-bot bypass;
- private evidence storage;
- raw document mirroring by default.

## Contribution priorities

Good contributions are bounded and testable, for example:

- correcting a public source reference;
- adding public metadata for a clearly identified vendor source;
- improving fixtures, examples, or factual documentation;
- adding tests around existing behavior;
- improving adapter compatibility without changing catalog meaning.

Schema, workflow-authority, permission, and policy-threshold changes require
maintainer review and explicit scope.

## Public operation checks

Maintainers should keep the following true:

- project scope and limitations are accurately documented;
- governance, contribution, security, and licensing documents are current;
- generated outputs are reproducible and drift-free;
- validation and release gates pass;
- scheduled workflows are enabled and observable;
- public discovery and agent-export endpoints are available;
- open issues and pull requests do not misrepresent catalog completeness or
  automation authority.
