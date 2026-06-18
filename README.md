# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a public-source-only, metadata-first registry of vendor-published assurance references.

**Use OpenVA in your browser:** https://thedanieltan.github.io/open-vendor-assurance/

The hosted catalog viewer is the easiest path for non-dev users. It lets users browse the reviewed public catalog, use the browser-local vendor inventory matcher, and export selected public metadata without installing Python, Docker, or developer tooling.

OpenVA records factual metadata about public vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product.

## Start here

For non-dev users:

```text
Hosted catalog viewer: https://thedanieltan.github.io/open-vendor-assurance/
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

For public relaunch readiness:

```text
docs/public-launch-checklist.md
docs/roadmap.md
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
- native-language-aware;
- provenance-driven;
- hash-friendly;
- exportable through universal packs;
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

## Automation posture

OpenVA operates an **autonomous** catalog: routine catalog growth and
maintenance run through pull requests without human approval, gated by machine
decisions, separation of duties, release gates, and controlled automerge. Humans
govern the rules (code, schemas, workflows, authority, policy thresholds,
permissions, the emergency hold), not routine records. When evidence is
insufficient the system fails closed (`deferred` / `rejected` / `quarantined` /
`rolled_back`) rather than queueing a human. See `AGENTS.md` and
`docs/catalog-autonomy-policy.md`.

The full workflow inventory lives in `.github/workflows/`, with classification and retirement status tracked in `docs/operations/`. Representative public-facing workflow groups are:

```text
validate.yml                         validates PRs and pushes to main
catalog-pr-guard.yml                 enforces Catalog PR boundaries
catalog-growth-discovery.yml         proposes catalog candidates (reports and issues only)
candidate-promotion-pr.yml           controlled promotion PRs from reviewed evidence
source-maintenance-report.yml        scheduled source health, observation ledger, and discovery report
submitted-source-verification.yml    verifies submitted source claims (comment and label only)
coverage-audit.yml                   catalog breadth/depth audit and coverage growth report
bot-dashboard-issue.yml              bot dashboard render and issue sync (dry-run default)
bot-chatops.yml                      live /openva hold and /openva unhold label commands
release-candidate.yml                release artifact smoke workflow
```

Scheduled maintenance detects drift, materialises routine catalog records, and
produces artifacts. No automation changes `main` directly; every mutation flows
through a pull request, the release gate, and a controlled automerge lane.

Quarantined legacy report workflows remain manual-only pending retirement evidence; see `docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md`.

Live chat-ops is limited to `/openva hold` and `/openva unhold`, which add or remove only the `openva-hold` label on the current issue or pull request, are maintainer-gated, and are smoke-tested. All other `/openva` commands remain report-only, local-audit-only, or denied; see `docs/operations/BOT_CHATOPS_EXECUTION.md`.

Agent-generated catalog work enters through pull requests and is decided
autonomously by the machine quorum and release gates. The catalog lifecycle is:

```text
submitted claim -> candidate -> machine_provisional -> active
                             \-> deferred | rejected | quarantined | rolled_back
```

Human review remains required for changes to code, schemas, workflows, policy
thresholds, authority contracts, permissions, and governance — not for routine
catalog records.

## Architecture stance

OpenVA maintains public-source vendor assurance metadata:

```text
vendor_public_profile
public_source_reference
artifact_reference
source_observation
freshness_status
change_event
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

OpenVA exports consumer-neutral dataset packs. Importing OpenVA data should not be treated as vendor approval, risk acceptance, legal advice, compliance advice, procurement advice, security advice, KYC/AML advice, or regulatory advice.

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

Pack-level `generated_at` and `generatedAt` values may be fixed to preserve
deterministic rebuilds. They are not a catalog freshness signal; use source,
change, observation, release tag, or repository commit metadata for provenance.

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

The agent index lists every export (vendor index, per-vendor source maps, flat source index, latest observations, latest change events) with its content digest, and every file carries a snapshot block (`commit_sha`, `generated_at`, `digest`) for verification. Exports record public source metadata, observed health, and change signals only — no risk scores, no legal conclusions, no gated content.

See `docs/agent-export-contract.md` for shapes, field semantics, and the digest verification recipe.

The hosted site also publishes a static discovery surface over these exports: a static page per vendor at `/vendors/{vendor_id}/`, an agent integration guide at `/agents/`, a typed discovery manifest at `/.well-known/openva.json`, plus `sitemap.xml`, `robots.txt`, and `llms.txt`. All OpenVA-owned public URLs derive from `config/publication.yaml`.

## Unified vendor resolution

OpenVA resolves vendor assurance sources **catalogue-first, with live refresh on
use**, through one pipeline shared by browser users, API consumers, agents, and
future MCP integrations. A request resolves the vendor identity, matches the
catalogue, and for each required source type checks whether a catalogue source
exists and is current. Current sources are returned as-is; missing, stale,
broken, redirected, or unavailable sources trigger bounded public discovery, and
any discovered or refreshed source is routed into the *existing* autonomous
catalogue-growth lifecycle (candidate → eligibility → machine_provisional →
quorum → PR → release gates → automerge). Live resolution never writes canonical
catalogue files.

Results use one small vocabulary — `catalog_current`, `catalog_refreshed`,
`newly_discovered`, `source_unavailable`, `not_found`, `identity_ambiguous`,
`verification_inconclusive`, `candidate_processing`, `catalogued` — and two
explicit freshness modes (`cached` for stored state, `verify` for a live check).
Cached and verified results are never silently treated as equivalent, and
catalogue membership, source health, and durable lifecycle stage are reported on
separate axes so a deferred or rejected candidate is never shown as processing.

In `verify` mode the resolver enqueues discovered/refreshed candidates to
`maintenance/candidates/` — the same queue the autonomous-growth workflow
consumes — under a concurrency-safe, deterministic merge. A candidate is only
reported as `candidate_processing` once it is reachable from the ref that workflow
checks out (the remote default branch); local-only writes/commits stay
`pending_ingress`. The hosted browser Local Matcher is cached-only (static page):
it reports catalogue state and a `result_state` per vendor but does not perform
live discovery or lifecycle routing.

OpenVA preserves source-reference and observation history. It does not archive or
reproduce historical vendor documents.

The contract lives in `tools/openva/vendor_resolution.py`
(`resolve_vendor_sources(...)`), validates against
`schemas/openva/vendor-resolution-result.schema.json`, and is documented in
`docs/vendor-resolution.md`.

## Release Downloads

For spreadsheet-first users, OpenVA publishes non-technical download assets through GitHub Releases:

```text
openva-csv.zip
openva-sample-inventory.csv
openva-inventory-template.csv
```

`openva-csv.zip` contains curated CSV exports for vendors, sources, artifacts, observations, candidate sources, unavailable sources, and source coverage. The sample and template inventory files show simple `vendor_name`, `business_entity_name`, optional `domain`, optional `jurisdiction`, optional `registration_number`, and optional `registered_address` columns for matching a vendor list against OpenVA.

These files are generated from the tagged repository state. OpenVA does not operate a public upload service or central hosted matching service; users keep their vendor inventories local unless they choose to run their own tooling.

See `docs/release-downloads.md` for a plain-language walkthrough of the release assets.

## Hosted catalog viewer

OpenVA also provides a GitHub Pages catalog viewer for non-dev users.

Hosted catalog viewer: https://thedanieltan.github.io/open-vendor-assurance/

The hosted site is a static, read-only viewer over public OpenVA metadata. It lets users browse the reviewed catalog snapshot, view the live observation feed shell, use the browser-local matcher, and export selected public metadata.

The site does not provide accounts, workspaces, server-side matching, hosted private inventory upload, vendor scoring, vendor approval, or compliance conclusions. Private vendor inventories should remain browser-local, local, or self-hosted inside the user's own environment.

The hosted site is generated as a compiled catalog distribution:

```text
data/meta.json
data/vendor-search.min.json
data/source-types.json
data/coverage-summary.json
data/vendors/{vendor_id}.json
data/observation-feed.json
```

The reviewed catalog is a release snapshot, not a live monitoring feed. The live observation feed shell is non-canonical; durable observation and change state lives in the observation ledger (see `docs/observation-ledger.md`) and in the agent exports under `/public/`.

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

The optional match service in `services/openva_match_service/` wraps the pack reader and inventory matcher as a self-hosted HTTP service. OpenVA does not operate a central hosted service. It also exposes a read-only, cached-pack enrichment API under `/v1` for zero-install spreadsheet and document clients — see [`docs/resolver-api.md`](docs/resolver-api.md).
