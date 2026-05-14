# Maintainers

OpenVA maintainers preserve the project boundary: public-source-only, metadata-first, non-advisory, native-language-aware vendor assurance metadata.

This file describes maintainer expectations before public launch.

## Maintainer responsibilities

Maintainers are responsible for:

- enforcing public-source-only scope;
- rejecting private, gated, customer-specific, NDA, portal, or login-required materials;
- rejecting legal, compliance, procurement, security, KYC, AML, or risk advice;
- reviewing source authority and source accessibility;
- preserving metadata-only records;
- preserving native-language authority for non-English sources;
- reviewing schema and export contract changes;
- reviewing workflow, automation, and security-sensitive changes;
- keeping generated indexes and pack output reproducible;
- keeping automation PR-based and human-reviewed.

## Review requirements

At least one maintainer review is required for:

- new vendors;
- new source domains;
- new artifact types;
- source access-class changes;
- rights-class changes;
- non-English source interpretation;
- observation writes;
- generated pack/index changes;
- catalog-agent PRs;
- public roadmap changes.

Explicit owner review is required for:

- schema changes;
- validator changes;
- pack contract changes;
- observation behavior changes;
- workflow and permission changes;
- security policy changes;
- license changes;
- governance, contributor, and public-source policy changes.

## Merge rules

A PR should not merge unless:

- CI is green;
- generated files are current when required;
- the PR scope matches its lane;
- source, rights, and non-advisory checks are satisfied;
- any required human review has been completed;
- any unresolved maintainer review threads are resolved.

Maintainers should prefer squash or merge commits consistently with repository settings. Do not merge PRs that rely on local-only generated output or uncommitted index changes.

## Automation rules

Automation may:

- discover public sources;
- prepare metadata-only changes;
- regenerate indexes;
- run validators and tests;
- open PRs;
- summarize factual diffs.

Automation must not:

- merge directly to `main`;
- use credentials or private access;
- bypass bot protection, CAPTCHAs, login gates, form gates, or customer portals;
- classify legal sufficiency;
- score vendor risk;
- make approval, suitability, or recommendation claims;
- rewrite governance, security, license, or schema policy without explicit maintainer instruction.

## Conflict of interest and vendor submissions

Vendor-originated contributions are welcome only when they improve factual public metadata.

Vendor-originated PRs must not include:

- promotional wording;
- self-certification by OpenVA;
- claims of approval, suitability, adequacy, or recommendation;
- private customer materials;
- gated trust-center content;
- negotiated or bespoke terms.

A vendor may point maintainers to public vendor-controlled sources. The public source remains the authority.

## Triage cadence

Before public launch, maintainers should review open issues and PRs at least weekly.

Recommended triage order:

1. security and abuse reports;
2. boundary/scope violations;
3. broken CI or validator failures;
4. source correction requests;
5. catalog-agent PRs;
6. documentation and onboarding issues;
7. backlog and feature proposals.

## Maintainer escalation

Escalate to owner review when:

- a source is hard to classify as public or gated;
- a non-English source has jurisdiction-specific meaning;
- a change may affect downstream importer compatibility;
- an issue asks for legal/compliance conclusions;
- a vendor disputes metadata;
- a contributor repeatedly violates scope boundaries;
- a PR modifies workflows, schemas, validators, or pack semantics.
