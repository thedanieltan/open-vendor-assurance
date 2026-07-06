# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a resolver-first, public-source-only, metadata-first service for vendor assurance source references.

**Use OpenVA in your browser:** https://thedanieltan.github.io/open-vendor-assurance/

OpenVA helps CISO, DPO, procurement, compliance, and agent workflows resolve vendor identities into public vendor-published source URLs such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA maintains a public reference cache to make resolution faster, safer, and more repeatable. The cache is not audit evidence, vendor approval, legal authority, or a complete vendor universe.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product.

## Start here

For non-dev users:

```text
Hosted source resolver and catalog viewer: https://thedanieltan.github.io/open-vendor-assurance/
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

For agent-composed use (primary distribution):

```text
docs/agent-workspace-composition.md   how an agent composes OpenVA with its own workspace connector
docs/agent-integrations.md            MCP (stdio + Streamable HTTP), HTTP, and framework adapters
integrations/mcp/openva_mcp/          read-only MCP server (stdio + Streamable HTTP)
```

OpenVA's primary distribution model is agent-composed: a user's existing agent reads the
workspace (spreadsheet, database, tickets) through the connector it already controls, sends
OpenVA only bounded vendor identities via the read-only HTTP/MCP tools, and writes results
back itself. OpenVA never accesses the workspace and holds no workspace credential
(see [ADR-0002](docs/architecture/decisions/ADR-0002-agent-composed-workspace-integration.md)
and [ADR-0003](docs/architecture/decisions/ADR-0003-remote-mcp-product-surface.md)).

For spreadsheet users without a capable agent (Google Sheets — secondary/fallback):

```text
integrations/google-sheets/      Google Sheets client over the /v1/enrich API
```

The Google Sheets integration is a **secondary compatibility surface**, not the primary
distribution path: a bound Apps Script project that enriches vendor rows against a configured
public-read OpenVA deployment. It consumes the existing `/v1/enrich` API, embeds no API key,
and writes stable `openva_*` reference columns back into a sheet. No local Python, Docker,
repository checkout or API secret is required; the current release requires manual
installation into a bound Apps Script project, and a zero-install Workspace add-on is a
future objective rather than a current capability. Results are public-source references
cached to the service's loaded snapshot — not advice or live verification.

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
- resolver-first;
- factual and non-advisory;
- native-language-aware;
- provenance-driven;
- hash-friendly;
- exportable through universal packs;
- usable independently of any one runtime or application.

OpenVA resolves:

```text
vendor identity -> public source URL references -> source-type classification -> structured source pack
```

OpenVA does not:

- mirror raw vendor documents by default;
- monitor or version document contents;
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

OpenVA operates an **autonomous** reference-cache and catalog lifecycle: routine public-source
resolution findings, catalog growth, and maintenance run through pull requests without human
approval, gated by machine decisions, separation of duties, release gates, and controlled
automerge. Humans govern the rules (code, schemas, workflows, authority, policy thresholds,
permissions, the emergency hold), not routine records. When evidence is insufficient the
system fails closed (`deferred` / `rejected` / `quarantined` / `rolled_back`) rather than
queueing a human. See `AGENTS.md` and `docs/catalog-autonomy-policy.md`.

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

Scheduled maintenance performs cache hygiene, detects public-source locator drift, materialises routine catalog records, and produces artifacts. No automation changes `main` directly; every mutation flows through a pull request, the release gate, and a controlled automerge lane.

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

OpenVA maintains public-source vendor assurance locator metadata:

```text
vendor_public_profile
public_source_reference
artifact_reference
source_observation
source_locator_status
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

OpenVA exports consumer-neutral dataset packs and resolver outputs. Importing OpenVA data should not be treated as vendor approval, risk acceptance, legal advice, compliance advice, procurement advice, security advice, KYC/AML advice, or regulatory advice.

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
