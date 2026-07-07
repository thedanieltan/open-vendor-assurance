# OpenVA Site

This directory contains the static OpenVA contract and community-index browser.
It is a documentation, discovery, local resolver entry-point, and source-reference
preview surface. It is not the OpenVA product runtime.

Static site: https://thedanieltan.github.io/open-vendor-assurance/

The site is built from committed OpenVA public pack and index files:

```text
openva-pack.json
indexes/
```

Build output is written to:

```text
site/dist/
```

Build locally:

```bash
python site/build.py
```

The page is static and GitHub Pages-ready. It has no backend, database, account
system, upload endpoint, private inventory processing, live verification job,
live discovery job, hosted resolver worker, or server-side workspace
persistence. Boundary shorthand: no backend, database, account system, upload
endpoint; no live verification job; no live discovery job; no hosted resolver
worker; no server-side workspace persistence.

Canonical boundary phrase: no backend, database, account system, upload endpoint.
Canonical boundary phrase: no hosted resolver worker.

## Discovery surface

The same build also emits a static discovery layer for search engines and
machine consumers:

```text
vendors/{vendor_id}/index.html   one page per vendor reference
agents/index.html                agent and machine integration guide
.well-known/openva.json          typed discovery manifest with content digest
sitemap.xml
robots.txt
llms.txt
assets/openva-pages.css          shared stylesheet for the generated pages
```

These files are generated from committed public metadata and
`config/publication.yaml`; they are deterministic and must not be hand-edited.
Each vendor page links to that vendor's JSON export and keeps the original
vendor-published source URLs. To change the published base URL, edit
`config/publication.yaml` rather than the generators.

Selections and browser-local CSV rows are held in browser memory only. They are
not written to `localStorage`, `sessionStorage`, a server, or a database.

## Public route terminology

The public site should present OpenVA as a browser-local tool for populating
vendor lists with indexed public assurance source references:

```text
Vendor list enrichment
Source reference lookup
Human export presets
Agent / MCP / API templates
Export source references
```

Role labels such as CISO, DPO, security, privacy, and procurement are preset
shortcuts only. They preselect source fields; users can add or remove fields
before export.

Legacy strings may still appear in tests or non-visible compatibility notes
until the site test suite is fully reconciled. Do not expand those strings into
new user-facing copy:

```text
Reviewed Catalog
Live Observation Feed
Reviewed catalog snapshot
No live observation events are available yet.
observation ledger workflow
Local Matcher
```

Boundary phrases that must remain true across the site and documentation:

```text
Your CSV is processed locally in your browser. It is not uploaded to OpenVA.
not a live monitoring feed
indexed public assurance source references
not_advice
```

## Browser-local vendor-list enrichment

The browser-local resolver lets users choose a CSV from their own computer and
match it against OpenVA public metadata in browser memory. The CSV stays in the
user's browser session and match results can be downloaded as CSV or JSON.

Supported input columns:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

Only one identity field is required for matching. OpenVA should preserve user
columns where practical and append the selected OpenVA output preset.

Default human preset:

```csv
openva_match,openva_vendor_name,openva_domain,dpa_url,privacy_notice_url,subprocessors_url,security_page_url,trust_center_url,status_page_url,openva_notes
```

Other human presets are documented in [`../docs/output-templates.md`](../docs/output-templates.md):

```text
Source URLs
Privacy / DPA Review
Security Review
Procurement Quick Check
Minimal Match Only
Full Human Export
```

Do not include these diagnostic fields in the default human export:

```text
match_confidence
catalog_membership
catalog_tier
review_state
freshness_mode
advisory_boundary
candidate_source_count
unavailable_source_count
```

The JSON download is for agents and machine consumers. New consumers should use
the simplified `identity` + `source_references` template documented in
`docs/output-templates.md` and `docs/resolver-result-pack-contract.md`.
Compatibility fields such as `match`, `sources`, `primary_source_by_type`, and
`source_urls_by_type` may remain for older adapters.

The browser-local resolver is static: it reports loaded public metadata and
never claims live verification, live discovery, server-side lifecycle routing,
server-side CSV upload, or server-side persistence. Known indexed URLs are
source references from the loaded OpenVA index, not live monitoring results.

Local resolution results are not vendor approval, compliance findings, risk
scores, procurement recommendations, legal opinions, security conclusions, or
suitability determinations.

## Observation feed shell

The static build emits:

```text
site/dist/data/observation-feed.json
```

Observation events are machine-generated public-source facts, not vendor
approval, compliance findings, risk findings, procurement recommendations,
legal opinions, or materiality determinations.

The static site must not add real observation events by hand, promote
observation events into public source records, or imply continuous document
monitoring.

## Deployment and update cadence

The static site is deployed to GitHub Pages from `site/dist/` when a release tag
matching `v*` is pushed. The build checks out the tagged commit, runs OpenVA
validation, builds the static site from the tagged pack/index files, uploads the
GitHub Pages artifact, and deploys it through the official Pages deployment
action. This deployment publishes contract documentation, a community index
browser, local resolver entry points, and source-reference previews; it does not
run a hosted OpenVA resolver or process user inventories for OpenVA.

## Compiled public-metadata distribution

The site is generated as a compiled static distribution rather than a runtime
database.

Initial page load uses:

```text
site/dist/data/meta.json
site/dist/data/vendor-search.min.json
site/dist/data/source-types.json
site/dist/data/coverage-summary.json
```

Vendor details are loaded on demand from:

```text
site/dist/data/vendors/{vendor_id}.json
```

This keeps the non-dev hosted page usable as OpenVA grows, while release assets
continue to serve bulk CSV and internal tooling use cases.
