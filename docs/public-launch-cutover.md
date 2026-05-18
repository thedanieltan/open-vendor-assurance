# Public Launch Cutover Guide

This guide describes the maintainer steps for moving OpenVA from private development to public contribution posture.

It does not change repository visibility by itself and does not tag a release. It is an operational guide for maintainers.

## Launch positioning

Use this positioning:

```text
OpenVA is a public-source-only, metadata-first registry of vendor-published assurance references.
```

Do not use these descriptions:

```text
compliance database
legal document archive
vendor risk scoring system
certification authority
procurement recommendation engine
KYC provider
AML provider
security assessor
```

## Before changing repository visibility

Confirm:

- [ ] `docs/v0.1.0-release-candidate.md` is complete.
- [ ] `docs/public-launch-checklist.md` is complete or remaining gaps are intentionally documented.
- [ ] `docs/ci-and-branch-protection.md` branch-protection expectations are applied or tracked.
- [ ] `validate / validate` passes on `main`.
- [ ] `openva-pack.json` and `indexes/` are current.
- [ ] No raw documents, screenshots, private portal exports, SOC reports, ISO certificates, or extracted full text are committed by default.
- [ ] No public issue contains credentials, gated material, or private customer content.
- [ ] Issue templates are enabled and blank issues are disabled.
- [ ] CODEOWNERS is current.
- [ ] SECURITY.md is current.
- [ ] Release/versioning docs are current.

## Visibility cutover

When maintainers are ready, change repository visibility through GitHub repository settings.

Recommended sequence:

1. Confirm branch protection on `main`.
2. Confirm required check `validate / validate`.
3. Confirm CODEOWNERS review expectations.
4. Confirm issue templates render correctly.
5. Confirm SECURITY.md private reporting guidance.
6. Change repository visibility to public.
7. Open a public tracking issue for launch feedback.
8. Pin or reference `docs/index.md` in launch communications.
9. Avoid promising completeness, coverage, or legal/compliance utility.

## Launch announcement template

```md
# OpenVA v0.1.0 release candidate

OpenVA is a public-source-only, metadata-first registry of vendor-published assurance references.

It records factual metadata about public vendor sources such as DPAs, subprocessor pages, trust-center pages, privacy notices, security pages, certification references, AI/data terms, and other public assurance references.

OpenVA does not provide legal, compliance, procurement, audit, security, privacy, KYC, AML, sanctions, regulatory, or vendor-risk advice. It does not include private, gated, customer-specific, NDA, portal, SOC report, ISO certificate, or bespoke agreement materials.

Start here:

- README.md
- docs/index.md
- CONTRIBUTING.md
- DISCLAIMER.md
- docs/versioning-policy.md
- docs/consumer-conformance-fixtures.md
```

## First public issues to expect

Maintainers should expect and triage:

- vendor catalog updates;
- boundary questions;
- documentation fixes;
- scope questions for legal/compliance/vendor-risk advice requests;
- vendor-submitted corrections;
- requests to include gated trust-center materials.

Use:

```text
docs/triage-policy.md
.github/ISSUE_TEMPLATE/
```

## Post-launch first week

Recommended maintainer actions:

- review new issues daily for scope violations;
- close or redirect private/gated material requests quickly;
- let the contribution intake agent turn catalog update issues into either a clear reviewed `Catalog:` PR or a human-review decision;
- label catalog update and scope question issues consistently;
- avoid merging large catalog batches until public contribution behavior is understood;
- keep automation PR-based and human-reviewed;
- monitor whether README and DISCLAIMER prevent advisory misunderstanding;
- collect docs friction into small follow-up issues.

## Emergency rollback posture

If public launch exposes private material, credentials, or serious workflow issues:

1. stop merging non-critical PRs;
2. remove or redact sensitive public content where possible;
3. move sensitive discussion to private reporting channels;
4. review SECURITY.md and workflow permissions;
5. document the incident as a governance issue without repeating sensitive content.

## Non-advisory boundary

Public launch does not change OpenVA's role. OpenVA remains a best-effort public metadata registry and does not certify, approve, recommend, score, or determine any vendor's suitability for any organization, jurisdiction, workload, control, or legal obligation.
