# OpenVA free data source distribution guide

Work-Package: WP-OPENVA-CANONICAL-SITE-01

OpenVA can be published as a free, public-source vendor assurance metadata dataset.

## Positioning

OpenVA is a public-source-only metadata dataset for vendor-published assurance references.

It records factual source-reference metadata such as vendor names, domains, trust centers, privacy pages, security pages, subprocessor pages, status pages, public certification references, and related public URLs.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product. It does not approve, score, certify, monitor, or assess vendors.

## Distribution targets

| Target | Purpose | Repo-side asset |
| --- | --- | --- |
| GitHub / GitHub Pages | Source of truth and browser use | `README.md`, existing GitHub Pages site, existing schema.org metadata |
| Hugging Face Datasets | AI/agent builders and data consumers | `docs/huggingface-dataset-card.md` |
| Kaggle Datasets | Analysts and dataset search traffic | `docs/kaggle-dataset-metadata.json` |
| Zenodo | DOI, archival citation, release snapshot | `docs/zenodo-metadata.json`, `docs/dataset-citation.cff` |
| DataHub / open-data directories | Discovery listing copy | `docs/open-data-directory-listing.md` |

## Release package shape

Prefer one clean GitHub release before mirroring to other platforms.

```text
openva-dataset-v0.1/
├── openva-pack.json
├── indexes/summary.json
├── indexes/vendors.json
├── indexes/sources.json
├── dist/vendors/*.json
├── docs/free-data-source-distribution.md
├── docs/huggingface-dataset-card.md
├── docs/kaggle-dataset-metadata.json
├── docs/zenodo-metadata.json
├── docs/dataset-citation.cff
└── README.md
```

Do not publish generated claims as advisory outputs. Keep the boundary wording visible on every external listing.

## Manual publishing checklist

### GitHub

1. Confirm the public site works.
2. Create a release, for example `v0.1.0-dataset`.
3. Attach or reference the static package files.
4. Keep GitHub as the source of truth.

### Hugging Face Datasets

1. Create a dataset repo named `open-vendor-assurance` or `openva-public-assurance-sources`.
2. Copy `docs/huggingface-dataset-card.md` into the Hugging Face dataset repo as `README.md`.
3. Upload the dataset files or link back to GitHub Pages/GitHub release artifacts.
4. Keep the non-advisory boundary in the card.

### Kaggle Datasets

1. Create a Kaggle dataset.
2. Use `docs/kaggle-dataset-metadata.json` as the starting `dataset-metadata.json`.
3. Upload a release package or selected JSON/CSV exports.
4. Keep the subtitle factual and non-advisory.

### Zenodo

1. Connect the GitHub repository to Zenodo.
2. Archive a GitHub release.
3. Use `docs/zenodo-metadata.json` as the metadata source.
4. Use `docs/dataset-citation.cff` as the citation source if promoting citation from GitHub.

### Open-data directories

Use `docs/open-data-directory-listing.md` as the listing copy.

## Boundary text to reuse

```text
OpenVA is a free public-source metadata dataset for vendor-published assurance source references. It records factual locator metadata only. It does not certify, approve, score, monitor, assess, or advise on vendors and does not replace legal, compliance, procurement, security, audit, KYC, AML, sanctions, regulatory, or vendor-risk review.
```
