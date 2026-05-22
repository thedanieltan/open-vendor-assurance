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

## Launch note

- [ ] Public launch copy describes OpenVA as an infrastructure launch.
- [ ] Public launch copy does not imply a hosted catalog, central service, vendor rating, or completeness claim.
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

OpenVA does not operate a public upload service or central hosted matching
service. HTTP access is available only through the optional self-hosted match
service. Users should keep private vendor inventories inside their own
environment.
```

Do not describe OpenVA as:

```text
a vendor risk scoring system
a compliance database
a legal document archive
a certification authority
a procurement recommendation engine
```
