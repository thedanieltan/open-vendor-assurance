# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a resolver-first, public-source-only, metadata-first project for vendor-published assurance source references.

**Use OpenVA in your browser:** https://thedanieltan.github.io/open-vendor-assurance/

The browser UI helps users resolve vendor names into public source packs. It supports source lookup, browser-local CSV resolution, configurable source-pack fields, and export of selected public metadata without installing Python, Docker, or developer tooling.

OpenVA records factual locator metadata about public vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product.

## Start here

For non-dev users:

```text
Browser resolver UI: https://thedanieltan.github.io/open-vendor-assurance/
GitHub Releases
docs/release-downloads.md
openva-inventory-template.csv
openva-sample-inventory.csv
```

For contributors and maintainers:

```text
CONTRIBUTING.md
docs/submission-intake.md
docs/submission-verification.md
docs/catalog-agent-protocol.md
docs/agent-control-plane.md
docs/human-review-operations.md
MAINTAINERS.md
GOVERNANCE.md
SECURITY.md
```

For consumers and downstream importers:

```text
GitHub Releases
docs/release-downloads.md
docs/local-compiler.md
docs/agent-export-contract.md
docs/adapter-contract.md
docs/adapter-output-contract.md
docs/consumer-conformance-fixtures.md
docs/versioning-policy.md
docs/release-policy.md
docs/release-checklist.md
openva-pack.json
indexes/
schemas/openva/
```

For agent-composed use:

```text
docs/agent-workspace-composition.md   how an agent composes OpenVA with its own workspace connector
docs/agent-integrations.md            MCP (stdio + Streamable HTTP), HTTP, and framework adapters
integrations/mcp/openva_mcp/          read-only MCP server (stdio + Streamable HTTP)
```

OpenVA's preferred distribution model is agent-composed: a user's existing agent reads the workspace through the connector it already controls, sends OpenVA only bounded vendor identities through read-only HTTP/MCP tools, and writes source-pack results back itself. OpenVA never needs workspace credentials and does not require direct access to Google Drive, Microsoft 365, Notion, Jira, Slack, or another workspace.

For spreadsheet users without a capable agent, the Google Sheets client is a secondary compatibility surface:

```text
integrations/google-sheets/      Google Sheets client over the /v1/enrich API
```

The Google Sheets integration is a bound Apps Script client that enriches vendor rows against a configured public-read OpenVA endpoint. It consumes the existing `/v1/enrich` API, embeds no API key, and writes stable `openva_*` reference columns back into a sheet. The current release requires manual installation into a bound Apps Script project; a zero-install Workspace add-on is a future objective rather than a current capability. Results are public-source references from the service's loaded snapshot, not advice or live verification.

For public relaunch readiness:

```text
docs/public-launch-checklist.md
docs/roadmap.md
docs/resolver-first-closeout.md
docs/triage-policy.md
docs/first-good-issue-policy.md
DISCLAIMER.md
LICENSE
```

## Scope

OpenVA is:

- public-source-only;
- metadata-first;
- factual and non-advisory;
- resolver-first;
- native-language-aware;
- provenance-driven;
- hash-friendly;
- source-pack oriented;
- usable independently of any one runtime or application.

OpenVA does not:

- mirror raw vendor documents by default;
- include bespoke agreements;
- include authenticated trust-center or customer portal materials;
- include NDA-gated content;
- state that any vendor is compliant, approved, safe, certified, adequate, suitable, or recommended;
- provide tenant-specific risk decisions;
- replace professional, legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice.

## Validate the repository

Run:

```bash
python -m tools.openva.validate validate
pytest -q
```

Before a release or pack-pinning point, also run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

## Resolver-first closeout status

The resolver-first Phases 1-9 are complete as implementation slices:

```text
#518 Phase 1 — Positioning correction
#520 Phase 2 — Resolver-first public UI
#521 Phase 3 — Source pack schema
#522 Phase 4 — Hosted resolver staging smoke plan
#523 Phase 5 — Source map and discovery engine
#524 Phase 6 — Candidate memory as background cache
#525 Phase 7 — Workspace write-back projection
#526 Phase 8 — Configurable source pack builder
#527 Phase 9 — Resolver-usefulness prioritisation
```

The shipped browser UI is static and browser-local. It uses loaded public metadata and does not upload private vendor inventories, run live discovery from the page, or operate a production hosted verify endpoint.

Hosted resolver infrastructure remains gated by staging, production, smoke evidence, credentials, provider choice, domain, and launch evidence. Until those gates are complete, OpenVA should be described as a static/browser-local resolver UI plus repository-shipped HTTP/MCP/self-hosted components, not as an operated production hosted resolver.

See `docs/resolver-first-closeout.md` for the consolidation record.

## Automation posture

OpenVA operates an autonomous reference-cache maintenance system: routine public-source record maintenance and background reusable-memory updates run through pull requests, machine decisions, separation of duties, release gates, and controlled automerge. Humans govern the rules: code, schemas, workflows, authority, policy thresholds, permissions, and emergency holds.

When evidence is insufficient, the system fails closed (`deferred` / `rejected` / `quarantined` / `rolled_back`) rather than treating ambiguity as approval. See `AGENTS.md` and `docs/catalog-autonomy-policy.md`.

The full workflow inventory lives in `.github/workflows/`, with classification and retirement status tracked in `docs/operations/`. Representative public-facing workflow groups are:

```text
validate.yml                         validates PRs and pushes to main
catalog-pr-guard.yml                 enforces catalog PR boundaries
catalog-growth-discovery.yml         proposes candidates from bounded discovery signals
candidate-promotion-pr.yml           controlled promotion PRs from reviewed evidence
source-maintenance-report.yml        scheduled source health, observation ledger, and discovery report
submitted-source-verification.yml    verifies submitted source claims (comment and label only)
coverage-audit.yml                   breadth/depth audit and coverage report
bot-dashboard-issue.yml              bot dashboard render and issue sync (dry-run default)
bot-chatops.yml                      live /openva hold and /openva unhold label commands
release-candidate.yml                release artifact smoke workflow
```

Scheduled maintenance detects drift in public-source locator metadata, materialises routine records, and produces artifacts. No automation changes `main` directly; every mutation flows through a pull request, the release gate, and a controlled automerge lane.

Quarantined legacy report workflows remain manual-only pending retirement evidence; see `docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md`.

Live chat-ops is limited to `/openva hold` and `/openva unhold`, which add or remove only the `openva-hold` label on the current issue or pull request, are maintainer-gated, and are smoke-tested. All other `/openva` commands remain report-only, local-audit-only, or denied; see `docs/operations/BOT_CHATOPS_EXECUTION.md`.

Agent-generated public-source work enters through pull requests and is decided autonomously by machine gates. The internal lifecycle is:

```text
submitted claim -> candidate -> machine_provisional -> active
                             \-> deferred | rejected | quarantined | rolled_back
```

Human review remains required for changes to code, schemas, workflows, policy thresholds, authority contracts, permissions, and governance — not for routine public-source locator records.

## Architecture stance

OpenVA maintains public-source vendor assurance metadata:

```text
vendor_public_profile
public_source_reference
artifact_reference
source_observation
freshness_status
change_event
source_pack_result
```

Consumers of OpenVA own their own operational use of that metadata:

```text
workspace_vendor
vendor_review
risk_decision
approval
private_evidence
audit_event
control_mapping
user-specific obligation impact
```

OpenVA exports consumer-neutral source packs and dataset packs. Importing OpenVA data should not be treated as vendor approval, risk acceptance, legal advice, compliance advice, procurement advice, security advice, KYC/AML advice, or regulatory advice.

## Public-source-only rule

If a source requires login, NDA, customer status, sales approval, support ticket access, private portal access, credentialed access, form submission, or anti-bot bypass, it is out of scope.

The repository may record that a public landing page exists. It must not include private contents, private hashes, private summaries, or extracted private text.

## Native-language rule

The native-language source remains authoritative. English summaries are convenience metadata only.

## Default evidence model

The default evidence model is:

```text
source URL + provenance metadata + access classification + rights classification + hash metadata
```

The default evidence model is not:

```text
raw document mirroring
```

## Pack contract

Current export identifiers:

```text
profileId: openva.public-metadata.v1
schemaVersion: openva-export-pack.v1
schema_version: 0.1.0
```

Consumers should pin the release tag or repository commit, `profileId`, `schemaVersion`, `packId`, and pack/index digests where reproducibility matters.

Pack-level `generated_at` and `generatedAt` values may be fixed to preserve deterministic rebuilds. They are not a freshness signal; use source, change, observation, release tag, or repository commit metadata for provenance.

See:

```text
docs/versioning-policy.md
docs/release-policy.md
```

## Agent exports

For AI agents, OpenVA publishes static, deterministic, digest-verifiable JSON exports on the hosted site. Start at:

```text
https://thedanieltan.github.io/open-vendor-assurance/public/openva-agent-index.json
```

The agent index lists every export with its content digest, and every file carries a snapshot block (`commit_sha`, `generated_at`, `digest`) for verification. Exports record public source metadata, observed health, and change signals only — no risk scores, no legal conclusions, no gated content.

See `docs/agent-export-contract.md` for shapes, field semantics, and the digest verification recipe.

The hosted site also publishes a static discovery surface over these exports: a static page per vendor at `/vendors/{vendor_id}/`, an agent integration guide at `/agents/`, a typed discovery manifest at `/.well-known/openva.json`, plus `sitemap.xml`, `robots.txt`, and `llms.txt`. All OpenVA-owned public URLs derive from `config/publication.yaml`.

## Unified vendor resolution

OpenVA resolves vendor assurance sources through one shared contract for browser users, API consumers, agents, and MCP integrations. A request resolves vendor identity, maps requested source types, returns public source references where available, and separates matched, ambiguous, missing, gated, unavailable, and not-checked states.

Results preserve separate axes for:

```text
identity match status
requested source type
result state
mode: cached_only | checked_on_demand | discovered
public access status
confidence
snapshot identity
candidate memory state
not_advice
```

The browser resolver is cached/static and browser-local. It reports loaded public metadata and source-pack states, but it does not perform live discovery or lifecycle routing from the page.

For local batch use, `python -m tools.openva.resolve_csv` compiles a vendor CSV
into resolver result-pack JSON and flat CSV using committed OpenVA index hints
only. It does not fetch URLs, perform live verification, upload inventories, or
call a hosted OpenVA resolver. See `docs/local-compiler.md`.

The hosted/self-hosted resolver contracts live in `tools/openva/vendor_resolution.py`, `schemas/openva/vendor-resolution-result.schema.json`, and `schemas/openva/source-pack-result.schema.json`, with details in `docs/vendor-resolution.md` and `docs/resolver-api.md`.

OpenVA preserves source-reference and observation history. It does not archive, reproduce, continuously monitor, compare, or interpret historical vendor documents.

## Release Downloads

For spreadsheet-first users, OpenVA publishes non-technical download assets through GitHub Releases:

```text
openva-csv.zip
openva-sample-inventory.csv
openva-inventory-template.csv
```

`openva-csv.zip` contains curated CSV exports for vendors, sources, artifacts, observations, candidate sources, unavailable sources, and source coverage. The sample and template inventory files show simple `vendor_name`, `business_entity_name`, optional `domain`, optional `jurisdiction`, optional `registration_number`, and optional `registered_address` columns for matching a vendor list against OpenVA.

These files are generated from the tagged repository state. OpenVA does not currently operate a production central matching service or a hosted private-inventory upload service. The repository ships optional API-key-gated verify transport for self-hosted use and future hosted deployment. That transport is disabled by default unless configured by the operator, and the public project does not claim a production hosted verify endpoint until staging, production, smoke evidence, and launch evidence are complete.

See `docs/release-downloads.md` for a plain-language walkthrough of the release assets.

## Browser resolver UI

OpenVA provides a GitHub Pages resolver UI for non-dev users.

Browser resolver UI: https://thedanieltan.github.io/open-vendor-assurance/

The hosted page is static and read-only over public OpenVA metadata. It lets users resolve vendor sources from loaded public metadata, configure source-pack fields, use browser-local CSV matching, look up public source records, and export selected public metadata.

The site does not provide accounts, workspaces, server-side matching, hosted private inventory upload, live discovery from the page, vendor scoring, vendor approval, or compliance conclusions. Private vendor inventories should remain browser-local, local, or self-hosted inside the user's own environment.

The hosted page is generated as a compiled static distribution:

```text
data/meta.json
data/vendor-search.min.json
data/source-types.json
data/coverage-summary.json
data/vendors/{vendor_id}.json
data/observation-feed.json
```

The static site is a release snapshot over loaded public metadata, not a live monitoring feed. Durable observation and change state lives in the observation ledger and in the agent exports under `/public/`.

For details, see `docs/release-downloads.md` and `site/README.md`.

## Adapters

OpenVA ships small Python adapters for common consumption paths. Install an adapter from the repository checkout, then point it at the pack directory or `openva-pack.json`.

```bash
python -m pip install adapters/python/openva_pack_reader
python -m pip install adapters/python/openva_csv_export
python -m pip install adapters/python/openva_sqlite_export
python -m pip install adapters/python/openva_jsonl_export
python -m pip install adapters/python/openva_vendor_inventory_matcher
```

Available adapters:

```text
openva_pack_reader                  read-only pack, index, and vendor manifest reader
openva_csv_export                   spreadsheet-friendly CSV export
openva_sqlite_export                local SQLite export
openva_jsonl_export                 pipeline-friendly JSONL export
openva_vendor_inventory_matcher     conservative inventory-to-OpenVA matcher
```

Examples:

```bash
python -m openva_csv_export --pack . --out ./openva-csv
python -m openva_sqlite_export --pack . --out ./openva.sqlite
python -m openva_jsonl_export --pack . --out ./openva-jsonl
python -m openva_vendor_inventory_matcher --pack . --input customer_vendors.csv --out matched_vendors.csv
```

The optional match service in `services/openva_match_service/` wraps the pack reader and inventory matcher as a self-hosted HTTP service. OpenVA does not currently operate a production central matching service or a hosted private-inventory upload service. The repository ships optional API-key-gated verify transport for self-hosted use and future hosted deployment. Until hosted deployment gates are completed, private vendor inventories should remain browser-local, local, or inside a consumer-controlled self-hosted environment. The service also exposes a read-only, cached-pack enrichment API under `/v1` for zero-install spreadsheet and document clients — see [`docs/resolver-api.md`](docs/resolver-api.md).
