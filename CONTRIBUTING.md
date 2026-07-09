# Contributing

Contributions are welcome, but this repository uses strict evidence, source, and wording rules.

## Fastest way to contribute a vendor or source

Use the `Vendor catalog update` GitHub issue form when you want to:

- suggest a new public vendor;
- add a public source to an existing vendor;
- correct a moved or broken public source URL;
- correct factual public vendor/source metadata.

A good submission includes:

```text
Vendor: Example Vendor / example-vendor
Official website: https://vendor.example
Public source URL: https://vendor.example/legal/dpa
Requested change: Add this public DPA page to the catalog.
Why authoritative: It is published on the vendor's official domain.
```

Humans and agents should submit the same evidence shape: vendor identity, official domain, public source URL, source role if known, and short factual context. Contributors do not need to know OpenVA's internal source schema.

## What this project accepts

OpenVA accepts factual metadata about public vendor-published assurance materials, including:

- public DPA references;
- public subprocessor list references;
- public privacy notices;
- public trust-center landing pages;
- public security or compliance pages;
- public certification reference pages;
- public KYC or AML statements where relevant;
- public AI/data terms where relevant;
- source observation metadata;
- factual questionnaire or evidence request templates.

## What this project rejects

Do not submit:

- bespoke agreements;
- customer-specific contracts;
- order forms;
- private customer documents;
- NDA-gated materials;
- authenticated trust-center exports;
- private SOC reports;
- private ISO certificates;
- customer portal downloads;
- content requiring login, sales approval, customer status, support ticket access, or credentials;
- legal conclusions;
- compliance conclusions;
- procurement recommendations;
- vendor risk scores;
- security ratings;
- claims that a vendor is compliant, safe, certified, adequate, approved, suitable, or recommended.

## Source rules

A source must be public. Public means accessible without login, credentials, NDA, customer status, sales approval, private portal access, support ticket access, or anti-bot bypass.

If a public page points to gated documents, record only the public page metadata. Do not include gated contents, gated document hashes, summaries of gated documents, or extracted gated text.

## Repository layout

Common paths:

```text
data/vendors/                canonical vendor, source, artifact, change, and entity metadata
catalog-batches/             reviewed batch manifests used to generate catalog records
schemas/openva/              JSON Schemas for OpenVA records and pack contracts
tools/openva/                validation, indexing, catalog, maintenance, and release tooling
adapters/python/             pack reader, CSV, SQLite, JSONL, and inventory matcher adapters
services/openva_match_service/ optional self-hosted HTTP wrapper for inventory matching
docs/                        policy, workflow, adapter, service, and maintainer documentation
.github/workflows/           CI, catalog guard, maintenance, discovery, observation, and release workflows
fixtures/packs/              consumer conformance fixture packs
```

Generated public outputs:

```text
indexes/
dist/vendors/
openva-pack.json
```

When catalog records change, regenerate and commit the generated outputs. Adapter and service changes should not alter catalog data unless the PR is explicitly scoped for that.

## Non-technical catalog updates

If you are not opening a pull request, use the `Vendor catalog update` GitHub issue form to add a vendor, add a public source, or correct factual catalog metadata.

The issue is an intake request, not canonical catalog data. You do not need to classify source types, artifact types, source language, access class, or rights class. The contribution intake agent classifies metadata during PR preparation, comments its checks on the issue, and opens a machine-gated `Catalog:` PR only for low-risk existing-vendor source updates.

Use the `Scope or boundary question` issue form first when you are unsure whether a source or request is in scope.

## Human and agent contribution boundary

Human and agent contributions are welcome, but neither path writes catalog truth directly.

```text
issue or agent request
→ intake / verification
→ catalog or candidate PR
→ validation, catalog guard, generated-output checks, release gates
→ controlled merge path
→ active catalog
```

Low-risk public-source updates can proceed through machine gates without default human review. Ambiguous, gated, private, advisory, conflicting, or unsupported submissions are blocked or routed as non-canonical evidence instead of being merged by assumption.

## Submitting source claims

To submit a candidate vendor, a candidate assurance source, a broken or moved URL, a vendor rename or domain change, a subprocessor update feed, or a machine-readable source surface, use the `submission` issue forms. These submissions are claims: they enter verification and do not change catalog data directly.

See `docs/submission-intake.md` for which form to use and what happens after you submit.

## Language rules

The native-language source remains authoritative.

For non-English sources:

1. preserve native title where practical;
2. preserve native factual summary where practical;
3. mark English summaries as convenience metadata;
4. do not convert translation into advice or legal interpretation.

## Wording rules

Use factual wording:

- "Vendor publishes a public page describing..."
- "The public source references..."
- "The source is a public DPA page..."

Avoid advisory wording:

- "compliant"
- "safe"
- "approved"
- "adequate"
- "recommended"
- "suitable"
- "satisfies obligations"
- "meets requirements"

## Pull requests

Pull requests must:

- identify the public source;
- classify source access;
- classify rights status;
- preserve native-language context where relevant;
- avoid advisory language;
- explain whether any generated files were updated;
- pass validation checks.

## Repository hygiene

Repository history and documentation should describe the technical change and its evidence, not the tool used to produce it.

Do not add:

- model or tool co-author trailers;
- tool-prefixed branch names;
- chat, session, or shared-conversation links;
- prompt transcripts or internal scratch notes;
- statements that files were generated, written, or reviewed by a named model;
- implementation diaries, work-package closeouts, or superseded planning snapshots when an active contract, runbook, roadmap, or changelog already records the durable state.

Operational automation artifacts are allowed when they are part of the product or control plane, including `AGENTS.md`, bot authority contracts, workflow definitions, MCP integration documentation, and bounded execution prompts. Those files must specify executable behavior or governance boundaries rather than narrate how the repository was built.

Published commit and release identities are not rewritten for cosmetic cleanup. Remove obsolete material from the current tree, make corrections forward, and preserve released snapshot integrity.

## Catalog-agent pull requests

Catalog-agent PRs must follow:

```text
docs/catalog-agent-protocol.md
```

Catalog-agent PRs should use the catalog PR template and title format:

```text
Catalog: add <category> vendor batch <N>
Catalog: update <vendor-id> public source metadata
Catalog: add <region> vendor batch <N>
Catalog: fix <vendor-id> catalog metadata
```

Catalog-agent PRs are limited to small metadata-only batches, normally three to five vendors, and must not modify substrate, schema, workflow, policy, governance, or observation tooling unless an assigned work package explicitly authorizes that work.
