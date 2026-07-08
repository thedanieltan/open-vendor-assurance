# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a public-source, metadata-first resolver for vendor-published assurance references.

**Use OpenVA in your browser:** https://thedanieltan.github.io/open-vendor-assurance/

OpenVA helps users turn a vendor list into a review sheet of public vendor assurance URLs. Upload a CSV, resolve vendors against indexed public-source records, and export selected source-reference columns without installing Python, Docker, or developer tooling.

OpenVA records factual locator metadata about public vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product. It does not approve, score, certify, monitor, or assess vendors.

## Get value quickly

### Browser users — no install

Open:

```text
https://thedanieltan.github.io/open-vendor-assurance/
```

Then upload or paste a CSV with at least one of:

```text
vendor_name
domain
business_entity_name
registration_number
```

Export the review CSV when matching is complete.

### MCP users — copy/paste install

Use this when your agent host supports MCP.

macOS / Linux:

```bash
git clone https://github.com/thedanieltan/open-vendor-assurance.git
cd open-vendor-assurance
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install ./adapters/python/openva_pack_reader ./adapters/python/openva_vendor_inventory_matcher ./integrations/mcp/openva_mcp
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public --verify
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public
```

Windows PowerShell:

```powershell
git clone https://github.com/thedanieltan/open-vendor-assurance.git
cd open-vendor-assurance
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install ./adapters/python/openva_pack_reader ./adapters/python/openva_vendor_inventory_matcher ./integrations/mcp/openva_mcp
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public --verify
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public
```

MCP host config:

```json
{
  "mcpServers": {
    "openva": {
      "command": "openva-mcp",
      "args": ["--base-url", "https://thedanieltan.github.io/open-vendor-assurance/public"]
    }
  }
}
```

If your MCP host cannot find `openva-mcp`, use the absolute path inside the virtual environment:

```text
/path/to/open-vendor-assurance/.venv/bin/openva-mcp
C:\path\to\open-vendor-assurance\.venv\Scripts\openva-mcp.exe
```

### Self-hosted API users — copy/paste Docker

Use this when you want an internal HTTP endpoint for `/v1/enrich`.

```bash
git clone https://github.com/thedanieltan/open-vendor-assurance.git
cd open-vendor-assurance
docker build -f services/openva_match_service/Dockerfile -t openva-match-service:local .
docker run --rm \
  -p 8000:8000 \
  -v "$PWD:/data/openva-pack:ro" \
  -e OPENVA_PACK_PATH=/data/openva-pack \
  -e OPENVA_SERVICE_API_KEY=replace-with-a-secret \
  openva-match-service:local
```

Test from another terminal:

```bash
curl -fsS \
  -H "Authorization: Bearer replace-with-a-secret" \
  http://localhost:8000/v1/catalog/meta \
  | python -m json.tool
```

Call `/v1/enrich`:

```bash
curl -fsS \
  -H "Authorization: Bearer replace-with-a-secret" \
  -H "Content-Type: application/json" \
  -d '{"vendors":[{"row_id":"1","vendor_name":"Stripe","domain":"stripe.com"}],"source_types":["dpa","subprocessors_list","privacy_notice","security_page","trust_center"]}' \
  http://localhost:8000/v1/enrich \
  | python -m json.tool
```

OpenVA does not currently operate a production central API. Self-hosted API users run their own instance.

### Google Sheets users — manual fallback

The Google Sheets client is a secondary compatibility surface. It requires manual Apps Script installation today.

```text
1. Open your Google Sheet.
2. Select Extensions → Apps Script.
3. Create the files listed in integrations/google-sheets/README.md.
4. Paste the matching file contents from integrations/google-sheets/src/.
5. Replace the manifest with integrations/google-sheets/appsscript.json.
6. Reload the spreadsheet.
7. Use the OpenVA menu.
```

There is no Google Workspace Marketplace add-on yet.

## Start here

For non-dev users:

```text
Browser resolver UI: https://thedanieltan.github.io/open-vendor-assurance/
GitHub Releases
docs/release-downloads.md
docs/releases/v0.1-closure.md
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

OpenVA's preferred distribution model is agent-composed: a user's existing agent reads the workspace through the connector it already controls, sends OpenVA only bounded vendor identities through read-only HTTP/MCP tools, and writes source-reference results back itself. OpenVA never needs workspace credentials and does not require direct access to Google Drive, Microsoft 365, Notion, Jira, Slack, or another workspace.

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
docs/releases/v0.1-closure.md
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
- source-reference oriented;
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

OpenVA v0.1 additionally locks the human CSV and agent enrichment contracts; see `docs/releases/v0.1-closure.md`.

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

OpenVA exports consumer-neutral source-reference metadata and dataset packs. Importing OpenVA data should not be treated as vendor approval, risk acceptance, legal advice, compliance advice, procurement advice, security advice, KYC/AML advice, or regulatory advice.

## Public-source-only rule

If a source requires login, NDA, customer status, sales approval, support ticket access, private portal access, credentialed access, form submission, or anti-bot bypass, it is out of scope.
