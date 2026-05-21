# Catalog Agent Protocol

This protocol governs catalog-agent pull requests that add or update vendor metadata in OpenVA.

The catalog agent lane exists to expand and maintain the public vendor catalog without changing OpenVA's substrate, schemas, pack contract, observation behavior, release policy, or governance posture.

## Role boundary

A catalog agent may work on:

```text
vendor additions
public source URL discovery
DPA, subprocessor, privacy, security, trust-center, AI terms, KYC, AML, or certification metadata
regional vendor expansion
index regeneration
small catalog-only PRs
```

A catalog agent must not work on:

```text
schemas
validators
pack contract
pack integrity logic
observation fetch behavior
release policy
security policy
licensing
CODEOWNERS
CI workflow policy
public-source policy
retention policy
non-advisory policy
```

Those belong to the core OpenVA lane unless a maintainer explicitly assigns the change.

## Batch size

Catalog-agent PRs must remain small.

Default batch size:

```text
3-5 vendors per PR
```

A catalog-agent PR may contain fewer than three vendors when:

- the source language requires extra review;
- the vendor has unusual source structure;
- the source is region-specific;
- the update corrects existing metadata;
- the agent finds boundary concerns and needs maintainer review.

A catalog-agent PR should not exceed five vendors unless a maintainer explicitly authorizes it before work begins.

## Allowed files

Catalog-agent PRs may modify:

```text
data/vendors/**
indexes/**
openva-pack.json
```

Catalog-agent PRs may modify these documentation files only when the change is directly related to catalog expansion bookkeeping:

```text
docs/coverage-map.md
docs/vendor-expansion-backlog.md
```

Catalog-agent PRs must not modify:

```text
schemas/**
tools/**
tests/**
.github/workflows/**
.github/CODEOWNERS
docs/*policy*.md
docs/doctrine.md
docs/rights-policy.md
LICENSE
SECURITY.md
README.md
CONTRIBUTING.md
```

Exception: a maintainer may explicitly ask the agent to update docs or tests in a named PR.

## Source selection rules

Every source must be:

- public;
- vendor-controlled, regulator-controlled, or standards-body-controlled;
- accessible without login, credentials, NDA, sales approval, customer status, support ticket access, private portal access, or anti-bot bypass;
- directly relevant to the vendor record or artifact record;
- stable enough to be rechecked later.

Preferred source types:

- vendor legal page;
- vendor trust center page;
- vendor security/compliance page;
- vendor DPA or data protection terms page;
- vendor subprocessor page;
- vendor privacy notice page;
- vendor AI/data terms page;
- vendor KYC/AML help or legal page where relevant;
- public standards-body or certification registry page.

Disallowed source types:

- law-firm summaries;
- consultant blogs;
- news articles;
- third-party mirrors;
- scraped copies;
- customer portal exports;
- SOC reports behind a portal;
- private ISO certificates;
- sales-gated documents;
- documents requiring login, form submission, customer status, NDA, or support ticket access.

## Metadata-only rule

Catalog-agent PRs are metadata-only.

The agent must not commit:

- raw PDFs;
- raw HTML snapshots;
- screenshots;
- extracted full text;
- portal exports;
- copied contract bodies;
- SOC reports;
- ISO certificates;
- customer-specific terms;
- bespoke agreements.

Hashes should remain:

```text
sha256:TBD
```

unless approved observation tooling produced a hash.

## Non-advisory wording rules

Catalog-agent records must describe source facts only.

Allowed wording:

```text
Vendor publishes a public page describing its subprocessors.
Vendor publishes a public DPA page.
The source is a public trust-center landing page.
The public source references security and compliance materials.
```

Disallowed wording:

```text
compliant
safe
approved
adequate
recommended
suitable
meets requirements
satisfies obligations
low risk
high risk
certified by OpenVA
verified by OpenVA
```

A vendor may be described as publishing a certification reference only when the source itself is public and the wording is framed as a source fact, not an OpenVA endorsement.

## Native-language handling

For non-English sources, the agent should preserve native-language context.

Minimum expectations:

- record `source_language` accurately;
- preserve native title where practical;
- avoid English-only interpretation when the native source carries jurisdiction-specific meaning;
- mark English summaries as convenience metadata if summaries are present;
- stop for maintainer review when the agent cannot confidently interpret the native source.

The native-language source remains authoritative.

## Required commands

Before opening or updating a catalog-agent PR, run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
```

The generated files must be committed when catalog data changes:

```text
indexes/**
openva-pack.json
```

## PR title format

Use one of these formats:

```text
Catalog: add <category> vendor batch <N>
Catalog: update <vendor-id> public source metadata
Catalog: add <region> vendor batch <N>
Catalog: fix <vendor-id> catalog metadata
```

Examples:

```text
Catalog: add payments vendor batch 1
Catalog: add APAC SaaS vendor batch 1
Catalog: update microsoft public source metadata
```

## PR body requirements

Every catalog-agent PR must include:

- vendor list;
- source URLs used;
- confirmation that all sources are public;
- confirmation that no gated or private materials were used;
- confirmation that no raw documents were committed;
- confirmation that no advisory language was introduced;
- commands run;
- notes on native-language interpretation, if applicable;
- any sources that were rejected and why.

## When to stop

The catalog agent must stop and ask for maintainer review when:

- the useful source is gated;
- the source requires login, form submission, customer status, NDA, sales approval, support ticket access, or anti-bot bypass;
- the source is not vendor-controlled, regulator-controlled, or standards-body-controlled;
- the vendor's public material is mostly marketing language and lacks useful assurance metadata;
- the source language cannot be interpreted confidently;
- a new schema field or artifact type seems necessary;
- more than five vendors are needed in one PR;
- a source appears to contradict existing metadata;
- the change could affect pack guarantees, observation behavior, or public policy boundaries.

## Review posture

Catalog-agent PRs should be reviewed as factual data changes, not as product design or legal review.

Maintainers should check:

- source authority;
- public accessibility;
- metadata-only compliance;
- non-advisory wording;
- generated indexes and pack updates;
- validation and tests;
- regional and language handling.

## Relationship to observation tooling

Catalog-agent PRs should not run live observation writes unless a maintainer requests it.

Catalog expansion may add source records that are later observed by the core lane. Initial hashes should usually remain `sha256:TBD`.

## Relationship to public update pathway

Vendor-submitted corrections and public-source updates remain governed by:

```text
docs/public-update-pathway.md
docs/vendor-contributions.md
docs/vendor-public-manifest.md
```

The catalog agent may use public vendor manifests as discovery aids, but the same source and wording rules still apply.
