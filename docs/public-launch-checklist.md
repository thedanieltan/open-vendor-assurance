# Public Launch Checklist

Use this checklist before making OpenVA public or announcing broader contribution.

## Repository posture

- [ ] Repository description states resolver-first, public-source-only, metadata-first scope.
- [ ] README states OpenVA is not legal, compliance, procurement, security, KYC, AML, or risk advice.
- [ ] README states gated/private/customer-specific materials are excluded.
- [ ] README distinguishes the static/browser-local resolver UI from any future hosted/live resolver.
- [ ] LICENSE and metadata/code licensing posture are clear.
- [ ] SECURITY.md explains private reporting and automation boundaries.
- [ ] GOVERNANCE.md explains maintainer duties and human-review requirements.
- [ ] MAINTAINERS.md exists and is current.
- [ ] CONTRIBUTING.md references public source rules and non-advisory boundaries.
- [ ] CODEOWNERS covers governance-sensitive paths.

## Contribution readiness

- [ ] General PR template is current.
- [ ] Catalog/source PR template is current where internal automation still uses that term.
- [ ] Issue templates use a small public-facing set: vendor/source updates, scope or boundary questions, bugs, and docs.
- [ ] Source update issues receive contribution-intake agent comments and either a controlled PR or a clear human-review decision.
- [ ] Label taxonomy is documented.
- [ ] Good-first-issue policy is documented.
- [ ] Vendor-submitted update rules are documented.
- [ ] Public update pathway is documented.

## Automation and CI

- [ ] Validation workflow passes on main.
- [ ] PR guard workflows are active.
- [ ] Observation report workflow is read-only and does not write observation records.
- [ ] Source maintenance report workflow is read-only and publishes maintainer-readable summary, JSON, and CSV artifacts.
- [ ] Automation cannot merge directly to main.
- [ ] Candidate intake is autonomous and fail-closed: the consuming job recomputes eligibility and identity from each persisted candidate, never trusting the stored `eligibility_state`; the selected candidate is bound by id/path/SHA-256 digest/origin/vendor through to the candidate-bound mutation, and stale, forged, or changed records create no reusable public-source record.
- [ ] Candidate records remain non-authoritative; public-source truth changes only through the established PR path, and promotion to a terminal status remains independently gated.
- [ ] Workflows use least-privilege permissions.
- [ ] No workflow requires credentials for public source collection.
- [ ] No workflow bypasses anti-bot systems, CAPTCHAs, login gates, form gates, or portals.

## Data and pack integrity

- [ ] Generated indexes are current.
- [ ] `openva-pack.json` is current.
- [ ] Pack integrity verification passes.
- [ ] Deterministic timestamp semantics are documented.
- [ ] Adapter outputs expose non-advisory source-reference metadata.
- [ ] Match service responses expose non-advisory source-pack fields.
- [ ] Consumer conformance fixtures pass.
- [ ] Invalid conformance fixtures fail for expected reasons.
- [ ] No raw documents, screenshots, portal exports, SOC reports, ISO certificates, or extracted full text are committed by default.

## Public-source posture

- [ ] All source records are public.
- [ ] All source records are vendor-controlled, regulator-controlled, standards-body-controlled, or explicitly excepted.
- [ ] No source requires login, NDA, customer status, sales approval, support ticket access, private portal access, form submission, or anti-bot bypass.
- [ ] Source and artifact records use non-advisory wording.
- [ ] Non-English sources preserve native-language context where practical.
- [ ] Hashes remain `sha256:TBD` unless produced by approved OpenVA observation tooling.

## Open issue and PR hygiene

- [ ] Open source-update PRs are labelled or reviewed.
- [ ] Open governance-sensitive PRs are reviewed or clearly blocked.
- [ ] Issues requesting private/gated materials are closed or labelled as blocked by scope.
- [ ] Issues requesting legal/compliance/procurement/risk advice are closed or labelled as blocked by scope.
- [ ] Security-sensitive reports are not exposed publicly.

## Hosted deployment readiness (ADR-0006, decision-ready — not yet live)

The hosted deployment is **specified, not provisioned**. ADR-0006 is Accepted as the architecture decision; no provider account is created and no operated production endpoint is live. Before any hosted launch:

- [x] ADR-0006 (`docs/architecture/decisions/ADR-0006-hosted-public-read-deployment.md`) is accepted by a maintainer and recorded as Accepted in the ADR index.
- [ ] The maintainer external decisions are made: provider, region, domain, DNS/TLS, registry, secrets/identity, spend ceiling, production permissions — see `docs/operations/hosted-deployment-decision.md` §13.
- [ ] The engineered cost ceiling is configured: instance/concurrency cap, edge rate limit, and budget-alert kill-switch.
- [ ] The GitHub App key lives only in a managed secret store: never repo, browser, artifacts, or logs.
- [ ] Durable job/result records validate against `schemas/openva/hosted-job-record.schema.json` and carry no uploaded inventory, vendor identity, or request bodies.
- [ ] No prohibited telemetry field appears in any log, trace, or metric label (`docs/operations/hosted-deployment-observability.md`).
- [ ] The hosted path proposes candidates only through the existing PR-bound lifecycle; it never writes `data/**` or merges.
- [ ] Static exports, static MCP, and cached operation keep working with the hosted service disabled.
- [ ] Staging smoke evidence exists before staging is described as available.
- [ ] Production smoke evidence exists before any `live`, `hosted`, or `operated production resolver` claim.

## Launch note

- [ ] Public launch copy describes OpenVA as a resolver-first public-source metadata infrastructure launch.
- [ ] Public launch copy distinguishes the static/browser-local resolver UI from any hosted upload service, central API, vendor rating, live verification, or completeness claim.
- [ ] Spreadsheet and local/self-hosted workflows are documented without requiring users to upload private vendor inventories to OpenVA.
- [ ] Browser resolver UI is static and read-only over public metadata.
- [ ] Site is deployed to GitHub Pages from static build output.
- [ ] Site clearly separates loaded public metadata from observation events.
- [ ] Site clearly displays release tag or commit SHA for loaded public metadata.
- [ ] Site clearly displays snapshot/staleness disclosure.
- [ ] Site clearly labels observation events as machine-generated, non-advisory public-source facts when shown.
- [ ] Site deployment/update cadence is documented.
- [ ] Site has no upload form, account system, workspace persistence, hosted private-inventory processing, or server-side matching.
- [ ] Site does not use localStorage or sessionStorage for selections.
- [ ] Site exports selected OpenVA public metadata only.
- [ ] Site displays non-advisory boundary text on every page.
- [ ] Site links users to browser-local, local, or self-hosted matching for private inventories.
- [ ] GitHub Pages deployment workflow includes `contents: read`, `pages: write`, and `id-token: write` permissions.
- [ ] Hosted page uses compiled/sharded static outputs instead of requiring one large runtime database.
- [ ] `vendor-search.min.json` excludes heavy source arrays.
- [ ] Vendor detail records are generated as `data/vendors/{vendor_id}.json`.
- [ ] Site export still works from loaded vendor shards.
- [ ] Browser-local resolver still processes private inventories in memory only.

Public launch should describe OpenVA as:

```text
A resolver-first, public-source-only, metadata-first project for vendor-published assurance source references.
```

Also state:

```text
OpenVA v0.1.0 is an infrastructure launch, not a completeness claim.

The initial public metadata set is useful for testing importer workflows, resolving public vendor assurance source references, and contributing public-source metadata, but it should not be treated as complete vendor assurance coverage.

OpenVA does not currently operate a production central matching service, hosted private-inventory upload service, or public live-verify endpoint. The repository ships optional API-key-gated verify transport for self-hosted use and future hosted deployment. Until hosted deployment gates are completed, private vendor inventories should remain browser-local, local, or inside a consumer-controlled self-hosted environment. The browser UI offers static public metadata lookup, browser-local CSV resolution, configurable source-pack field selection, and export, but private inventory data should remain inside the user's browser session, local environment, or self-hosted environment.
```

Do not describe OpenVA as:

```text
a vendor risk scoring system
a compliance database
a legal document archive
a certification authority
a procurement recommendation engine
a vendor approval service
a live document monitoring service
```
