# Public Launch Checklist

Use this checklist before making OpenVA public or announcing broader contribution.

## Repository posture

- [ ] Repository description states public-source-only, metadata-first scope.
- [ ] README states OpenVA is not legal, compliance, procurement, security, KYC, AML, or risk advice.
- [ ] README states gated/private/customer-specific materials are excluded.
- [ ] LICENSE and metadata/code licensing posture are clear.
- [ ] SECURITY.md explains private reporting and automation boundaries.
- [ ] GOVERNANCE.md explains maintainer duties and human-review requirements.
- [ ] MAINTAINERS.md exists and is current.
- [ ] CONTRIBUTING.md references catalog-agent protocol and source rules.
- [ ] CODEOWNERS covers governance-sensitive paths.

## Contribution readiness

- [ ] General PR template is current.
- [ ] Catalog PR template is current.
- [ ] Issue templates use a small public-facing set: vendor catalog updates, scope or boundary questions, bugs, and docs.
- [ ] Catalog update issues receive a maintainer or catalog-agent handoff checklist before any catalog PR is opened.
- [ ] Label taxonomy is documented.
- [ ] Good-first-issue policy is documented.
- [ ] Vendor-submitted update rules are documented.
- [ ] Public update pathway is documented.

## Automation and CI

- [ ] Validation workflow passes on main.
- [ ] Catalog PR guard workflow is active.
- [ ] Observation dry-run workflow is manual-only.
- [ ] Automation cannot merge directly to main.
- [ ] Workflows use least-privilege permissions.
- [ ] No workflow requires credentials for public source collection.
- [ ] No workflow bypasses anti-bot systems, CAPTCHAs, login gates, form gates, or portals.

## Data and pack integrity

- [ ] Generated indexes are current.
- [ ] `openva-pack.json` is current.
- [ ] Pack integrity verification passes.
- [ ] Consumer conformance fixtures pass.
- [ ] Invalid conformance fixtures fail for expected reasons.
- [ ] No raw documents, screenshots, portal exports, SOC reports, ISO certificates, or extracted full text are committed by default.

## Catalog posture

- [ ] All catalog sources are public.
- [ ] All catalog sources are vendor-controlled, regulator-controlled, standards-body-controlled, or explicitly excepted.
- [ ] No source requires login, NDA, customer status, sales approval, support ticket access, private portal access, form submission, or anti-bot bypass.
- [ ] Source and artifact records use non-advisory wording.
- [ ] Non-English sources preserve native-language context where practical.
- [ ] Hashes remain `sha256:TBD` unless produced by approved OpenVA observation tooling.

## Open issue and PR hygiene

- [ ] Open catalog PRs are labelled or reviewed.
- [ ] Open governance-sensitive PRs are reviewed or clearly blocked.
- [ ] Issues requesting private/gated materials are closed or labelled as blocked by scope.
- [ ] Issues requesting legal/compliance/procurement/risk advice are closed or labelled as blocked by scope.
- [ ] Security-sensitive reports are not exposed publicly.

## Launch note

Public launch should describe OpenVA as:

```text
A public-source-only, metadata-first registry of vendor-published assurance references.
```

Do not describe OpenVA as:

```text
a vendor risk scoring system
a compliance database
a legal document archive
a certification authority
a procurement recommendation engine
```
