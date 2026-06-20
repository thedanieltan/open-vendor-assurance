# Public Launch Checklist

Use this checklist before making OpenVA public or announcing broader contribution.

## Repository posture

- [ ] Repository description states public-source-only, metadata-first scope.
- [ ] README states OpenVA is not legal, compliance, procurement, security, KYC, AML, or risk advice.
- [ ] README states gated/private/customer-specific materials are excluded.
- [ ] LICENSE and metadata/code licensing posture are clear.
- [ ] SECURITY.md explains private reporting and automation boundaries.
- [ ] GOVERNANCE.md explains maintainer duties and human-review requirements.
- [ ] MAINTAINERS.md exists and is current.
- [ ] CONTRIBUTING.md references catalog-agent protocol and source rules.
- [ ] CODEOWNERS covers governance-sensitive paths.

## Contribution readiness

- [ ] General PR template is current.
- [ ] Catalog PR template is current.
- [ ] Issue templates use a small public-facing set: vendor catalog updates, scope or boundary questions, bugs, and docs.
- [ ] Catalog update issues receive contribution-intake agent comments and either a reviewed `Catalog:` PR or a clear human-review decision.
- [ ] Label taxonomy is documented.
- [ ] Good-first-issue policy is documented.
- [ ] Vendor-submitted update rules are documented.
- [ ] Public update pathway is documented.

## Automation and CI

- [ ] Validation workflow passes on main.
- [ ] Catalog PR guard workflow is active.
- [ ] Observation report workflow is read-only and does not write observation records.
- [ ] Source maintenance report workflow is read-only and publishes maintainer-readable summary, JSON, and CSV artifacts.
- [ ] Automation cannot merge directly to main.
- [ ] Candidate intake is autonomous and fail-closed: the consuming job recomputes eligibility and identity from each persisted candidate (never trusting the stored `eligibility_state`); the selected candidate is bound by id/path/SHA-256 digest/origin/vendor through to the candidate-bound mutation (selected == mutated), and stale, forged, or changed records create no canonical catalogue PR.
- [ ] Candidate records remain non-canonical; catalogue truth changes only through the established PR path, and promotion to a terminal status remains the independent quorum (candidate intake never writes `data/vendors/**` directly and never merges).
- [ ] Workflows use least-privilege permissions.
- [ ] No workflow requires credentials for public source collection.
- [ ] No workflow bypasses anti-bot systems, CAPTCHAs, login gates, form gates, or portals.

## Data and pack integrity

- [ ] Generated indexes are current.
- [ ] `openva-pack.json` is current.
- [ ] Pack integrity verification passes.
- [ ] Deterministic timestamp semantics are documented.
- [ ] Adapter outputs expose `catalog_tier` and `review_state`.
- [ ] Match service responses expose tier-aware non-advisory fields.
- [ ] Consumer conformance fixtures pass.
- [ ] Invalid conformance fixtures fail for expected reasons.
- [ ] No raw documents, screenshots, portal exports, SOC reports, ISO certificates, or extracted full text are committed by default.

## Catalog posture

- [ ] All catalog sources are public.
- [ ] All catalog sources are vendor-controlled, regulator-controlled, standards-body-controlled, or explicitly excepted.
- [ ] No source requires login, NDA, customer status, sales approval, support ticket access, private portal access, form submission, or anti-bot bypass.
- [ ] Source and artifact records use non-advisory wording.
- [ ] Non-English sources preserve native-language context where practical.
- [ ] Hashes remain `sha256:TBD` unless produced by approved OpenVA observation tooling.

## Open issue and PR hygiene

- [ ] Open catalog PRs are labelled or reviewed.
- [ ] Open governance-sensitive PRs are reviewed or clearly blocked.
- [ ] Issues requesting private/gated materials are closed or labelled as blocked by scope.
- [ ] Issues requesting legal/compliance/procurement/risk advice are closed or labelled as blocked by scope.
- [ ] Security-sensitive reports are not exposed publicly.

## Hosted deployment readiness (ADR-0006, decision-ready — not yet live)

The hosted deployment is **specified, not provisioned**. ADR-0006 is Proposed; no
provider is accepted and no endpoint is live. Before any hosted launch:

- [ ] ADR-0006 (`docs/architecture/decisions/ADR-0006-hosted-public-read-deployment.md`) is accepted by a maintainer and recorded as Accepted in the ADR index.
- [ ] The maintainer external decisions (provider, region, domain, DNS/TLS, registry, secrets/identity, spend ceiling, production permissions) are made — see `docs/operations/hosted-deployment-decision.md` §13.
- [ ] The engineered cost ceiling (instance/concurrency cap + edge rate limit + budget-alert kill-switch) is configured — no vendor offers a hard spend cap.
- [ ] The GitHub App key lives only in a managed secret store (never repo/browser/artifacts/logs); least-privilege App (no merge); break-glass revocation tested.
- [ ] Durable job/result records validate against `schemas/openva/hosted-job-record.schema.json` and carry no uploaded inventory, vendor identity, or request bodies.
- [ ] No prohibited telemetry field appears in any log, trace, or metric label (`docs/operations/hosted-deployment-observability.md`).
- [ ] The hosted path proposes candidates only through the existing PR-bound lifecycle; it never writes `data/**` or merges.
- [ ] Static exports + static MCP + cached operation keep working with the hosted service disabled (kill-switch + rollback drills pass).
- [ ] Production smoke evidence (A/B/C) exists before any "live" claim, and the seven positioning files are revised in lockstep with the first transport merge (preserving the seven required limitation phrases).

## Launch note

- [ ] Public launch copy describes OpenVA as an infrastructure launch.
- [ ] Public launch copy distinguishes the hosted read-only catalog viewer/browser-local matcher from any hosted upload service, central API, vendor rating, or completeness claim.
- [ ] Spreadsheet and local/self-hosted workflows are documented without requiring users to upload private vendor inventories to OpenVA.
- [ ] Hosted catalog viewer is read-only.
- [ ] Site is deployed to GitHub Pages from static build output.
- [ ] Site clearly separates reviewed catalog records from live observation events.
- [ ] Site clearly displays release tag or commit SHA for reviewed catalog data.
- [ ] Site clearly displays catalog snapshot/staleness disclosure.
- [ ] Site clearly labels live feed events as machine-generated, non-canonical observations.
- [ ] Live feed UI shell displays an empty state until observation ledger/feed generation ships.
- [ ] Site deployment/update cadence is documented for both reviewed catalog and live feed.
- [ ] Site has no upload form, account system, workspace persistence, or private inventory processing.
- [ ] Site does not use localStorage or sessionStorage for selections.
- [ ] Site exports selected OpenVA public metadata only.
- [ ] Site displays non-advisory boundary text on every page.
- [ ] Site links users to local/self-hosted matching for private inventories.
- [ ] GitHub Pages deployment workflow includes `contents: read`, `pages: write`, and `id-token: write` permissions.
- [ ] Hosted site uses compiled/sharded catalog outputs instead of requiring one large `catalog-data.json`.
- [ ] `vendor-search.min.json` excludes heavy source arrays.
- [ ] Vendor detail records are generated as `data/vendors/{vendor_id}.json`.
- [ ] Site export still works from loaded vendor shards.
- [ ] Browser-local matcher still processes private inventories in memory only.

Public launch should describe OpenVA as:

```text
A public-source-only, metadata-first registry of vendor-published assurance references.
```

Also state:

```text
OpenVA v0.1.0 is an infrastructure launch, not a completeness claim.

The initial catalog is a seed dataset. It is useful for testing importer
workflows, matching public vendor assurance references, and contributing
public-source metadata, but it should not be treated as complete vendor
assurance coverage.

OpenVA does not operate a hosted private inventory upload service or central hosted matching service. The hosted site may offer a read-only viewer and browser-local matcher, but private inventory data should remain inside the user's browser session, local environment, or self-hosted environment.
```

Do not describe OpenVA as:

```text
a vendor risk scoring system
a compliance database
a legal document archive
a certification authority
a procurement recommendation engine
```
