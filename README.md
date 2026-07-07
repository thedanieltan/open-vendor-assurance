# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a local-first, public-source-only, metadata-first compiler for vendor-published assurance source references.

OpenVA's core job is simple:

```text
vendor CSV + requested source types -> resolver result-pack JSON/CSV
```

**Use OpenVA in your browser:** https://thedanieltan.github.io/open-vendor-assurance/

The browser UI is static. It helps users inspect the community index, preview source packs, and download browser-local exports from committed public metadata. It is not an OpenVA-hosted resolver and it does not process private vendor inventories for OpenVA.

OpenVA records factual locator metadata about public vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product.

## Start here

For spreadsheet users and agents that need source-pack output, use the local compiler:

```bash
python -m tools.openva.resolve_csv input.csv \
  --source-types trust_center,dpa,subprocessors_list,privacy_notice,security_page,status_page \
  --out-json result-pack.json \
  --out-csv result-pack.csv
```

The compiler reads the CSV from local disk, uses the committed OpenVA index as hint-only candidate metadata, and writes resolver result-pack JSON plus a flat CSV with deterministic `openva_*` columns. It performs no network calls and emits no live verification claims. See `docs/local-compiler.md`.

Supported input columns:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

For non-dev users:

```text
Browser/static index UI: https://thedanieltan.github.io/open-vendor-assurance/
GitHub Releases
docs/release-downloads.md
docs/local-compiler.md
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
docs/local-compiler.md                  local CSV -> result-pack compiler
docs/agent-workspace-composition.md     how an agent composes OpenVA with its own workspace connector
docs/agent-integrations.md              MCP, HTTP, and framework adapter notes
integrations/mcp/openva_mcp/            read-only MCP server components
```

OpenVA's preferred distribution model is local-first and agent-composed: the user's own agent, CLI, local engine, MCP server, or forked deployment reads the workspace it already controls, runs OpenVA tooling in the consumer environment, and writes source-pack results back itself. OpenVA does not need workspace credentials and does not require direct access to Google Drive, Microsoft 365, Notion, Jira, Slack, or another workspace.

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
- local-first;
- native-language-aware;
- provenance-driven;
- hash-friendly;
- source-pack oriented;
- usable independently of any one runtime or application.

OpenVA does not:

- process user vendor inventories for OpenVA;
- operate a hosted CSV processor;
- operate a hosted resolver API;
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

## Local compiler status

The local hint-only compiler is the primary concrete user path for turning a vendor CSV into OpenVA result-pack output:

```text
input.csv
  -> python -m tools.openva.resolve_csv
  -> result-pack.json
  -> result-pack.csv
```

The compiler is intentionally no-network. It uses the committed static/community index as candidate metadata and preserves provenance without overclaiming. Candidate locators remain:

```text
status=not_checked
verification_basis=not_checked
checked_at=null
```

Verified outcomes require a separate consumer-side live verification run. The community index is hint-only and is not authoritative evidence.

See `docs/local-first-resolution-doctrine.md`, `docs/local-compiler.md`, and `docs/resolver-result-pack-contract.md`.

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
