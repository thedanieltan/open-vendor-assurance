# OpenVA Site

This directory contains the static OpenVA browser resolver UI.

Browser resolver UI: https://thedanieltan.github.io/open-vendor-assurance/

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
live discovery job, or server-side workspace persistence. Boundary shorthand:
no upload endpoint, no live verification, no live discovery, no server-side
workspace persistence.

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

The public site should present the product as a resolver-first source-pack UI:

```text
Resolve vendor sources
Source Lookup
Configurable source-pack builder
Source pack preview
Export Source Pack
```

Role labels such as CISO, DPO, and procurement are preset shortcuts only. They
preselect source fields; users can add or remove fields before export.

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
openva-matched-inventory.csv
openva-matched-inventory.json
not_advice
```

## Browser-local resolver

The browser-local resolver lets users choose a CSV from their own computer and
resolve it against OpenVA public metadata in browser memory. The CSV stays in
the user's browser session and match results can be downloaded as CSV or JSON.

Supported input columns:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

The downloaded result preserves user-provided columns and appends OpenVA public
metadata fields such as matched vendor ID, match method, confidence, source
types, source URLs, result state, mode, and the non-advisory boundary.

The browser-local resolver is cached/static: it reports loaded static/public metadata
and never claims live verification, live discovery, or server-side lifecycle
routing. Hosted/self-hosted live resolution is described by the resolver
contract — see `docs/vendor-resolution.md` and `docs/resolver-api.md`.

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

The static browser resolver UI is deployed to GitHub Pages from `site/dist/`
when a release tag matching `v*` is pushed. The build checks out the tagged
commit, runs OpenVA validation, builds the static site from the tagged pack/index
files, uploads the GitHub Pages artifact, and deploys it through the official
Pages deployment action.

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
