# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a public-source-only, metadata-first resolver for vendor-published assurance references.

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

Export the review workbook or CSV when matching is complete.

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

For non-developer users:

```text
Browser resolver UI: https://thedanieltan.github.io/open-vendor-assurance/
docs/continuous-publication.md
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
docs/continuous-publication.md
docs/compatibility-policy.md
docs/local-compiler.md
docs/agent-export-contract.md
docs/adapter-contract.md
docs/adapter-output-contract.md
docs/consumer-conformance-fixtures.md
openva-pack.json
indexes/
schemas/openva/
```

For agent-composed use:

```text
docs/agent-workspace-composition.md   how an agent composes OpenVA with its own workspace connector
docs/agent-integrations.md            MCP, HTTP, and framework adapters
integrations/mcp/openva_mcp/          read-only MCP server
```

OpenVA's preferred distribution model is agent-composed: a user's existing agent reads the workspace through the connector it already controls, sends OpenVA only bounded vendor identities through read-only HTTP/MCP tools, and writes source-reference results back itself. OpenVA never needs workspace credentials and does not require direct access to Google Drive, Microsoft 365, Notion, Jira, Slack, or another workspace.

For spreadsheet users without a capable agent, the Google Sheets client is a secondary compatibility surface:

```text
integrations/google-sheets/      Google Sheets client over the /v1/enrich API
```

The Google Sheets integration enriches vendor rows against a configured public-read OpenVA endpoint, embeds no API key, and writes stable `openva_*` reference columns back into a sheet. It currently requires manual installation into a bound Apps Script project. Results are public-source references from the service's loaded snapshot, not advice or live verification.

For public operation and governance:

```text
docs/public-launch-checklist.md
docs/continuous-publication.md
docs/compatibility-policy.md
docs/roadmap.md
docs/resolver-first-closeout.md
docs/triage-policy.md
docs/first-good-issue-policy.md
docs/consumer-conformance-fixtures.md
DISCLAIMER.md
LICENSE
```

## Continuous publication

OpenVA has no formal catalog-release lifecycle. The current accepted catalog is published continuously:

```text
accepted change
→ merge to main
→ validate and rebuild generated indexes
→ deploy GitHub Pages
```

The exact state used by a page, API snapshot, agent bundle, or export is identified by its source commit SHA, generated timestamp, schema version, and relevant digests. Consumers that need a fixed state should pin an exact commit SHA or digest rather than waiting for or following a version tag.

See `docs/continuous-publication.md` and `docs/compatibility-policy.md`.

## Contributing vendor/source updates

Use the `Vendor catalog update` GitHub issue form when you want to suggest a vendor, add a public source, or correct factual public-source metadata.

A useful human or agent submission has this shape:

```text
Vendor: Example Vendor / example-vendor
Official website: https://vendor.example
Public source URL: https://vendor.example/legal/dpa
Requested change: Add this public DPA page to the catalog.
Why authoritative: It is published on the vendor's official domain.
```

Contributors do not need to classify OpenVA schema fields such as source type, artifact type, access class, rights class, or language. OpenVA automation classifies metadata during intake and then routes eligible changes through validation, catalog guards, generated-output checks, policy gates, and controlled merge lanes.

Do not submit private agreements, gated trust-center exports, SOC reports, ISO certificates, screenshots, copied document text, customer-specific terms, credentials, or anything that requires login, form submission, customer status, NDA, sales approval, support-ticket access, or anti-bot bypass.

Low-risk public-source updates can proceed through machine gates without default human review. Ambiguous, gated, private, advisory, conflicting, or unsupported submissions fail closed as non-canonical evidence rather than being merged by assumption.

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

- use raw document mirroring by default;
- include bespoke agreements;
- include authenticated trust-center or customer portal materials;
- include NDA-gated content;
- use anti-bot bypass;
- state that any vendor is compliant, approved, safe, certified, adequate, suitable, or recommended;
- provide tenant-specific risk decisions;
- replace professional, legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice.

## Validate the repository

Run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
python -m tools.openva.conformance fixtures/packs/valid-brand-only-fallback
```

These checks validate the continuously published repository state. They do not prepare or publish a formal release.

## Resolver-first closeout status

The resolver-first Phases 1–9 are complete as implementation slices. The shipped browser UI is static and browser-local. It uses loaded public metadata and does not upload private vendor inventories, run live discovery from the page, or operate a production hosted verification endpoint.

Hosted resolver infrastructure remains gated by staging, production, smoke evidence, credentials, provider choice, domain, and launch evidence. Until those gates are complete, OpenVA should be described as a static/browser-local resolver UI plus repository-shipped HTTP/MCP/self-hosted components, not as an operated production hosted resolver.

See `docs/resolver-first-closeout.md` for the consolidation record.

## Automation posture

OpenVA operates an autonomous reference-cache maintenance system: routine public-source record maintenance and background reusable-memory updates run through pull requests, machine decisions, separation of duties, validation gates, and controlled automerge. Humans govern code, schemas, workflows, authority, policy thresholds, permissions, and emergency holds.

When evidence is insufficient, the system fails closed (`deferred` / `rejected` / `quarantined` / `rolled_back`) rather than treating ambiguity as approval. See `AGENTS.md` and `docs/catalog-autonomy-policy.md`.

The full workflow inventory lives in `.github/workflows/`, with classification and retirement status tracked in `docs/operations/`. Representative public-facing workflow groups are:

```text
validate.yml                         validates PRs and pushes to main
catalog-pr-guard.yml                 enforces catalog PR boundaries
catalog-growth-discovery.yml         proposes candidates from bounded discovery signals
candidate-promotion-pr.yml           controlled promotion PRs from reviewed evidence
source-maintenance-report.yml        scheduled source health, observation ledger, and discovery report
submitted-source-verification.yml    verifies submitted source claims
coverage-audit.yml                   breadth/depth audit and coverage report
site-pages.yml                       publishes accepted main to GitHub Pages
bot-dashboard-issue.yml              bot dashboard render and issue sync
bot-chatops.yml                      live /openva hold and /openva unhold label commands
```

Scheduled maintenance detects drift in public-source locator metadata, materialises routine records, and produces artifacts. Automation does not write directly to `main`; every repository mutation flows through a pull request, validation, and a controlled merge lane. Accepted `main` is then deployed continuously by the Pages workflow.

Quarantined legacy report workflows remain manual-only pending retirement evidence; see `docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md`.

Live chat-ops is limited to `/openva hold` and `/openva unhold`, which add or remove only the `openva-hold` label on the current issue or pull request and are maintainer-gated. All other `/openva` commands remain report-only, local-audit-only, or denied; see `docs/operations/BOT_CHATOPS_EXECUTION.md`.

Agent-generated public-source work enters through pull requests and is decided autonomously by machine gates. The internal lifecycle is:

```text
submitted claim → candidate → machine_provisional → active
                             ↘ deferred | rejected | quarantined | rolled_back
```

Human review remains required for changes to code, schemas, workflows, policy thresholds, authority contracts, permissions, and governance—not for routine public-source locator records.

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

## Licensing and public reuse

OpenVA is intended to be freely forked, modified, redistributed, self-hosted, and built upon for commercial or non-commercial use.

- Software and project documentation remain under the MIT License in `LICENSE`.
- OpenVA-authored catalog metadata and generated data are dedicated under CC0 1.0 Universal.
- Vendor documents, trademarks, pages, and other third-party materials remain with their respective owners and are not licensed by OpenVA.

Forks and substantial software redistributions must retain the MIT notice. CC0-covered catalog metadata has no attribution or share-alike requirement. See `docs/licensing.md` for the detailed boundary.
