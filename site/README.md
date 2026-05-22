# OpenVA Site

This directory contains the static OpenVA Catalog Viewer.

Hosted catalog viewer: https://thedanieltan.github.io/open-vendor-assurance/

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

The viewer is static and GitHub Pages-ready. It has no backend, database,
account system, upload endpoint, private inventory processing, or server-side
workspace persistence.

Selections are held in browser memory only. They are not written to
`localStorage`, `sessionStorage`, a server, or a database.

## Browser-local inventory matcher

The Local Matcher page lets users choose a CSV from their own computer and match it against OpenVA public metadata in browser memory. The CSV stays in the user's browser session and match results can be downloaded as CSV or JSON.

Supported input columns:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

The downloaded match result preserves user-provided columns and appends OpenVA public metadata fields such as matched vendor ID, match method, confidence, source types, canonical source URLs, review state, and the non-advisory boundary.

Local match results are not vendor approval, compliance findings, risk scores, procurement recommendations, legal opinions, or suitability determinations.

## Feed contract

The live observation feed is generated as:

```text
site/dist/data/observation-feed.json
```

The v1 feed ships with an empty state because the observation ledger workflow
has not shipped yet. Real feed activation requires a later observation
ledger/feed generation PR.

Observation events must be non-canonical and preserve:

```text
catalog_tier: observation
review_state: auto_observed or human_review_required
canonical: false
advisory_boundary: non_advisory
```

Do not add real observation events by hand. Do not promote observation events
into canonical catalog records from the site.

## Deployment and update cadence

The reviewed catalog site is deployed to GitHub Pages from `site/dist/` when a
release tag matching `v*` is pushed. The build checks out the tagged commit,
runs OpenVA validation, builds the reviewed catalog site from the tagged
pack/index files, uploads the GitHub Pages artifact, and deploys it through the
official Pages deployment action.

The live feed shell is deployed through the same GitHub Pages static site
output. The placeholder workflow runs on `workflow_dispatch` and on the weekly
cron `0 3 * * 0` while the observation ledger is still pending. It confirms the
feed events array is empty instead of faking observation events.

## Compiled catalog distribution

The site is generated as a compiled catalog distribution rather than a single
large runtime database.

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

This keeps the non-dev hosted site usable as OpenVA grows, while release assets
continue to serve bulk CSV and internal tooling use cases.