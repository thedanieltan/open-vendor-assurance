# Security Policy

## Reporting

Report security issues privately to the repository owner. Do not open public issues for vulnerabilities involving credentials, tokens, workflow privilege escalation, parser sandbox escapes, or data leakage.

## Security boundaries

OpenVA must not require or store credentials for source collection.

OpenVA must not:

- scrape authenticated portals;
- bypass anti-bot systems;
- collect NDA-gated content;
- execute remote vendor JavaScript as trusted code;
- store secrets in source files, logs, fixtures, or generated indexes;
- allow automation to merge directly to main;
- mirror raw vendor documents by default.

## Automation posture

Automation may only operate on public URLs and must open pull requests for human review.

Any automation that encounters login walls, access denied pages, bot challenges, or customer-only portals must stop and mark the source as out of scope or review required.
