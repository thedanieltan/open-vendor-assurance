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

### Vendor catalog update

Use for requests to add vendors, add public sources, or correct factual public vendor-source metadata.

Examples:

- new vendor has suitable public sources;
- public source should be added to an existing vendor;
- source URL changed;
- vendor legal name changed;
- public subprocessor page moved;
- language classification needs correction.

The contribution intake agent comments automated checks on catalog update issues and may open a reviewed `Catalog:` PR for low-risk existing-vendor source updates. That comment is a handoff aid only; catalog data changes still require a reviewed `Catalog:` PR.

### Source claim submission

Use for structured claims filed through the `submission` issue forms: new vendor candidates, new assurance sources, broken or moved sources, vendor renames or domain changes, subprocessor update feeds, and machine-readable source surfaces.

Submissions are claims, not catalog changes. They are non-authoritative until verified, and catalog data changes only through reviewed pull requests. The forms collect the triage basics up front (vendor, domain, URL, source type, public access posture), so maintainers should not need to ask for missing basics.

Routing:

- forms apply `status:needs-triage` plus a `submission:` label;
- submission issues stay out of the catalog-agent lane: they do not carry `area:catalog` or `lane:` labels and do not use the `Catalog update:` title prefix;
- apply `submission:needs-triage` manually to submissions that are misfiled or cannot be classified into a type;
- gated submissions keep only the fact that a gated source exists; never ask the reporter to paste gated contents.

See `docs/submission-intake.md` for contributor guidance.

### Scope or boundary question

Use for questions about whether a source, request, or contribution is public, gated, private, vendor-controlled, advisory, out of scope, or otherwise suitable for OpenVA.

Boundary questions should be resolved before any data is added.

### Bug

Use for validator, pack, schema, observation, fixture, or tooling defects.

### Documentation

Use for unclear README, contributor, policy, protocol, or fixture documentation.

### Security

Use only for public-safe security process issues. Do not ask reporters to disclose secrets, credentials, vulnerabilities, or exploit details in public issues.

### Blocked by scope

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
scope:blocked

submission:new-vendor
submission:new-source
submission:broken-source
submission:vendor-identity
submission:machine-readable
submission:needs-triage

candidate:verified
candidate:needs-review
candidate:duplicate
candidate:gated
candidate:ambiguous
candidate:rejected
candidate:fetch-failed

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
