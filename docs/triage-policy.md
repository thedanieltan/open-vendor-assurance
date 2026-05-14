# Triage Policy

This policy defines how maintainers should classify, route, and close OpenVA issues and pull requests.

## Triage goals

Triage should protect OpenVA's boundaries:

- public-source-only;
- metadata-first;
- non-advisory;
- no gated or private materials;
- no vendor approval or risk scoring;
- reproducible generated outputs;
- PR-based automation with human review.

## Issue categories

Use these categories when triaging issues.

### Source correction

Use for factual corrections to existing public source metadata.

Examples:

- source URL changed;
- vendor legal name changed;
- public subprocessor page moved;
- language classification needs correction.

### Catalog request

Use for requests to add vendors or artifact references.

A catalog request is acceptable only when the requested vendor has suitable public sources.

### Boundary question

Use for questions about whether a source is public, gated, private, vendor-controlled, or suitable for OpenVA.

Boundary questions should be resolved before any data is added.

### Bug

Use for validator, pack, schema, observation, fixture, or tooling defects.

### Documentation

Use for unclear README, contributor, policy, protocol, or fixture documentation.

### Security

Use only for public-safe security process issues. Do not ask reporters to disclose secrets, credentials, vulnerabilities, or exploit details in public issues.

### Out of scope

Use when the issue asks for:

- legal advice;
- compliance advice;
- procurement recommendations;
- vendor scoring;
- private document analysis;
- customer-specific terms;
- gated trust-center materials;
- bypassing bot protection or access controls.

## Pull request categories

### Core-lane PR

Core-lane PRs may touch substrate, schemas, validators, workflows, governance, observation logic, pack contracts, fixtures, and security posture.

They require maintainer review.

### Catalog-lane PR

Catalog-lane PRs should start with:

```text
Catalog:
```

Catalog-lane PRs must follow:

```text
docs/catalog-agent-protocol.md
```

They should normally touch only:

```text
data/vendors/**
indexes/**
openva-pack.json
docs/coverage-map.md
docs/vendor-expansion-backlog.md
```

### Vendor-submitted PR

Vendor-submitted PRs are welcome only for factual public metadata corrections.

They must not contain promotional, advisory, self-certifying, or approval language.

## Label taxonomy

Recommended labels:

```text
area:catalog
area:docs
area:governance
area:schemas
area:validator
area:pack
area:observation
area:fixtures
area:security
area:automation

lane:core
lane:catalog-agent
lane:vendor-submitted

status:needs-triage
status:needs-source-review
status:needs-language-review
status:needs-maintainer-review
status:blocked
status:ready-to-merge

scope:public-source-only
scope:gated-material
scope:metadata-only
scope:non-advisory
scope:out-of-scope

priority:p0
priority:p1
priority:p2
priority:p3

good-first-issue
help-wanted
```

## Closing rules

Close issues as not planned when they request:

- private or gated materials;
- legal/compliance determinations;
- vendor risk scores;
- procurement recommendations;
- scraping or bypassing access controls;
- customer-specific agreement handling.

Close issues as completed when:

- a factual correction is merged;
- documentation is updated;
- the request is already satisfied by existing policy or tooling.

## Security and abuse

If a report includes secrets, credentials, private customer content, or exploit details, maintainers should:

1. avoid quoting the sensitive content;
2. direct the reporter to the private security reporting process;
3. remove or minimize public exposure where possible;
4. treat any affected automation or workflow as security-sensitive.

## Vendor disputes

If a vendor disputes metadata:

1. ask for a public vendor-controlled source;
2. compare the current record against the public source;
3. accept factual corrections;
4. reject promotional or advisory wording;
5. preserve public change history where appropriate.

OpenVA does not adjudicate bespoke agreements or private customer commitments.
