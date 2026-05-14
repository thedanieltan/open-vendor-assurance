# Governance

open-vendor-assurance is maintained as a public-good metadata registry for public vendor assurance references.

It is not a legal, compliance, procurement, security, KYC, AML, or vendor-risk advisory service.

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
- keeping automation constrained to pull-request proposals;
- applying issue and PR triage rules consistently.

See also:

```text
MAINTAINERS.md
docs/triage-policy.md
docs/public-launch-checklist.md
```

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

## Pull request lanes

### Core lane

Core-lane PRs may affect schemas, validators, pack contracts, observation behavior, workflows, governance, security posture, conformance fixtures, and release semantics.

Core-lane PRs require maintainer review.

### Catalog lane

Catalog-lane PRs should start with:

```text
Catalog:
```

Catalog-lane PRs must follow:

```text
docs/catalog-agent-protocol.md
```

They should remain metadata-only and small, normally three to five vendors per PR.

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

## Public launch posture

Before public launch, maintainers should confirm the checklist in:

```text
docs/public-launch-checklist.md
```

Open issues and PRs that could confuse the project boundary should be triaged, labelled, closed, or documented before launch.
