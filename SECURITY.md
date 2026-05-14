# Security Policy

## Reporting

Report security issues privately to the repository owner. Do not open public issues for vulnerabilities involving credentials, tokens, workflow privilege escalation, parser sandbox escapes, private materials, or data leakage.

If a public issue accidentally contains credentials, private customer content, gated portal content, SOC reports, ISO certificates, or exploit details, maintainers should avoid quoting the sensitive content and should move the discussion to a private channel where possible.

## Security boundaries

OpenVA must not require or store credentials for source collection.

OpenVA must not:

- scrape authenticated portals;
- bypass anti-bot systems;
- collect NDA-gated content;
- collect customer-specific agreements;
- collect private SOC reports;
- collect private ISO certificates;
- execute remote vendor JavaScript as trusted code;
- store secrets in source files, logs, fixtures, or generated indexes;
- allow automation to merge directly to main;
- mirror raw vendor documents by default.

## Automation posture

Automation may only operate on public URLs and must open pull requests for human review.

Any automation that encounters login walls, access denied pages, bot challenges, form gates, sales gates, customer-only portals, or private trust centers must stop and mark the source as out of scope or review required.

## Public issue hygiene

Public issues are appropriate for:

- documentation bugs;
- validator bugs;
- public-source metadata corrections;
- catalog requests using public sources;
- boundary questions that do not disclose sensitive material.

Public issues are not appropriate for:

- credentials;
- tokens;
- exploit details;
- private customer data;
- gated trust-center content;
- portal downloads;
- SOC reports;
- ISO certificates;
- customer-specific agreements;
- NDA materials.

## Workflow and supply-chain expectations

Workflow changes are security-sensitive and require maintainer review.

Maintainers should review workflow changes for:

- unnecessary write permissions;
- direct pushes to main;
- credential use;
- untrusted code execution;
- unsafe artifact handling;
- uncontrolled network access;
- attempts to bypass access controls.
