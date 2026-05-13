# Governance

open-vendor-assurance is maintained as a public-good metadata registry for public vendor assurance references.

## Governance principles

Maintainers must preserve the following project boundaries:

- public-source-only;
- metadata-first;
- factual and non-advisory;
- native-language-aware;
- no private customer materials;
- no gated trust-center contents;
- no vendor scoring or approval claims;
- no tenant-specific compliance decisions.

## Maintainer duties

Maintainers are responsible for:

- enforcing public-source-only rules;
- reviewing schema and vocabulary changes;
- reviewing rights classification changes;
- reviewing access classification changes;
- reviewing non-English source interpretation;
- rejecting advisory, promotional, or conclusory wording;
- ensuring generated indexes are reproducible;
- keeping automation constrained to pull-request proposals.

## Human review required

Human review is required for:

- new vendors;
- new official domains;
- new artifact types;
- rights classification changes;
- public access classification changes;
- non-English summaries;
- KYC, AML, sanctions, or regulated-finance records;
- workflow changes;
- schema changes;
- export compatibility profiles.

## Automation rule

Automation may discover sources, compute hashes, detect changes, and open pull requests.

Automation must not:

- merge directly to main;
- classify legal sufficiency;
- score vendor risk;
- approve vendors;
- summarize private or gated materials;
- bypass access controls;
- rewrite project doctrine.

## Dataset maturity

Records are best-effort public metadata. A record being present in OpenVA does not mean a vendor is approved, compliant, suitable, or recommended.
