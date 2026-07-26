---
license: mit
language:
- en
tags:
- open-data
- vendor-assurance
- procurement
- grc
- third-party-risk
- public-sources
- metadata
- json
- csv
pretty_name: OpenVA public vendor assurance source references
size_categories:
- 1K<n<10K
---

# Dataset Card for OpenVA public vendor assurance source references

## Dataset description

OpenVA is a public-source-only metadata dataset for vendor-published assurance references.

It records factual locator metadata about public vendor assurance materials such as trust centers, privacy pages, security pages, data processing addenda, subprocessor lists, status pages, public certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product. It does not approve, score, certify, monitor, or assess vendors.

## Homepage

- GitHub: `https://github.com/thedanieltan/open-vendor-assurance`
- Browser app: `https://thedanieltan.github.io/open-vendor-assurance/`

## Data fields

OpenVA records vendor and source-reference metadata, including fields such as:

- vendor identity fields
- domain and public URL locators
- source type labels
- source availability / health metadata where recorded
- provenance and generated index metadata

Exact machine-readable contracts remain in the GitHub repository under `schemas/openva/` and generated public artifacts under `indexes/`, `dist/`, and `openva-pack.json`.

## Intended uses

Appropriate uses:

- resolving a local vendor list against known public vendor assurance URLs
- building public-source vendor metadata workflows
- bootstrapping procurement or security-questionnaire research
- testing AI agents that need factual public vendor-source locator metadata
- data analysis of vendor-published assurance source coverage

Out-of-scope uses:

- legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice
- vendor approval, certification, scoring, monitoring, or assessment
- replacing human review of source documents

## Source and update policy

OpenVA uses public-source-only records and generated indexes. The GitHub repository is the source of truth.

## License

The repository is published under the MIT License unless a later dataset-specific license file is added.

## Citation

Use the GitHub repository or the latest archived release DOI if a Zenodo release has been created.

## Limitations

OpenVA is metadata-first. It may contain stale, incomplete, unavailable, redirected, or superseded public URLs. Public availability of a vendor source does not mean a vendor is compliant, secure, approved, certified, or suitable for any use case.
