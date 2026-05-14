# Public Roadmap

This roadmap communicates OpenVA direction without creating a support, legal, compliance, or vendor-certification commitment.

OpenVA is a public-source-only, metadata-first vendor assurance registry. It is not a legal, compliance, security, procurement, KYC, AML, or vendor-risk advisory service.

## Current maturity

OpenVA is pre-public-launch infrastructure.

Current focus:

- stable metadata schemas;
- public-source-only contribution workflow;
- reproducible generated indexes;
- export pack contract;
- observation dry-run quality;
- catalog-agent guardrails;
- consumer conformance fixtures;
- public governance readiness.

## Near-term phases

### Governance before public launch

Goal: make contribution boundaries clear before the repository is public.

Includes:

- maintainer guide;
- triage policy;
- issue templates;
- public launch checklist;
- label taxonomy;
- public roadmap;
- first-good-issue policy.

### Release and versioning discipline

Goal: define how consumers should pin and reason about OpenVA packs.

Includes:

- release policy;
- versioning policy;
- schema-version rules;
- profile-version rules;
- changelog expectations;
- compatibility expectations.

### Catalog expansion

Goal: expand coverage through small metadata-only PRs.

Rules:

- public sources only;
- 3-5 vendors per catalog-agent PR;
- no gated materials;
- no raw document mirroring;
- no advisory language;
- generated indexes and pack updated before merge.

### Observation hardening

Goal: make observation records safe enough for downstream trust signals.

Includes:

- result taxonomy;
- dry-run summaries;
- URL safety;
- no anti-bot bypass;
- no raw content storage;
- clear handling of bot-protected, size-limited, failed, or quarantined results.

### Consumer compatibility

Goal: help downstream importers validate packs safely.

Includes:

- conformance fixtures;
- import-safety checks;
- invalid-pack examples;
- stable pack contract documentation.

## Not on the roadmap

OpenVA does not plan to provide:

- legal advice;
- compliance advice;
- procurement recommendations;
- vendor risk scoring;
- vendor approval badges;
- vendor rankings;
- customer-specific agreement analysis;
- gated trust-center collection;
- SOC report collection from private portals;
- credentialed scraping;
- anti-bot bypass tooling;
- raw document mirroring by default.

## Good first issues

Good first issues should be low-risk and bounded.

Examples:

- clarify documentation wording;
- improve examples;
- add tests around existing behavior;
- fix typos;
- add public-source metadata for one clearly public source after maintainer approval;
- improve fixture documentation.

Not good first issues:

- schema changes;
- workflow permission changes;
- pack contract changes;
- observation fetch changes;
- non-English legal-source interpretation;
- KYC/AML records;
- vendor-submitted promotional updates;
- large vendor catalog batches.

## Public launch readiness

Before public launch, maintainers should confirm:

- README accurately states scope and limitations;
- CONTRIBUTING and GOVERNANCE are current;
- SECURITY is current;
- CODEOWNERS covers governance-sensitive paths;
- issue templates route users correctly;
- PR templates communicate source and non-advisory checks;
- validation workflow is green;
- catalog-agent guard is active;
- consumer conformance fixtures pass;
- open PRs that may confuse launch state are resolved or clearly labelled.
