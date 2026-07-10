# OpenVA public launch checklist

Use this checklist before a public release, major announcement, or material change to the public resolver.

## Product and licensing

- [ ] Public copy describes OpenVA as resolver-first, public-source-only, and metadata-first.
- [ ] Public copy states that OpenVA is not legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice.
- [ ] The browser-local resolver is distinguished from any future operated hosted service.
- [ ] The software licence is identified as MIT.
- [ ] OpenVA-authored catalog metadata is identified as CC0 1.0.
- [ ] Third-party vendor documents, trademarks, and webpages are expressly excluded from OpenVA's licence grant.
- [ ] Forking, modification, redistribution, self-hosting, and commercial use are described accurately.

## Public-source boundary

- [ ] Canonical source records refer only to public materials.
- [ ] No source requires login, credentials, NDA, customer status, sales approval, support-ticket access, private portal access, form submission, or anti-bot bypass.
- [ ] Raw documents, screenshots, portal exports, SOC reports, private certificates, and copied full text are not committed by default.
- [ ] Non-English sources preserve native-language context where practical.
- [ ] Source wording remains factual and non-advisory.

## User experience

- [ ] The GitHub Pages resolver loads successfully.
- [ ] Browser CSV processing remains local to the user's browser.
- [ ] The source-pack builder allows users to add or remove source fields.
- [ ] Direct source lookup and exports work from the compiled static shards.
- [ ] Snapshot identity and staleness disclosures are visible.
- [ ] Observation and source-health labels are clearly separated from vendor conclusions.
- [ ] The page contains no account system, workspace persistence, or hosted private-inventory upload.

## Data and release integrity

- [ ] Generated indexes and `openva-pack.json` are current.
- [ ] Release CSV and JSON manifests contain the expected files and checksums.
- [ ] Deterministic timestamp semantics are documented.
- [ ] Consumer conformance fixtures pass.
- [ ] Invalid fixtures fail for the expected reasons.
- [ ] Candidate and unavailable records are not presented as canonical or advisory conclusions.

## Automation and governance

- [ ] Pull-request scope guards pass.
- [ ] Workspace affected-test planning passes.
- [ ] Existing workflow, repository-integrity, release, and weighted-review gates remain active.
- [ ] No workflow writes directly to `main`.
- [ ] Candidate admission remains fail-closed and independently verified.
- [ ] Canonical catalog mutation remains pull-request-bound and reversible.
- [ ] Workflows use least-privilege permissions and require no credentials for ordinary public-source collection.

## Hosted deployment claims

OpenVA may describe the provider-neutral hosted application path and optional self-hosted verify transport. It must not claim an operated production hosted resolver until provider, region, identity, secrets, DNS/TLS, spend controls, staging, production deployment, production smoke evidence, and operational ownership are complete.

Current public wording should remain equivalent to:

```text
OpenVA ships a static/browser-local resolver UI plus local, MCP, and self-hostable components. It does not currently operate a production central matching service or hosted private-inventory upload service.
```

## Release positioning

- [ ] OpenVA v0.1.0 is described as an infrastructure launch with a seed dataset, not a completeness claim.
- [ ] Catalog breadth and depth are described as continuously improving.
- [ ] Missing catalog data is not described as evidence that a source does not exist.
- [ ] Recorded sources are not described as vendor approval, compliance, adequacy, security, suitability, or recommendation.
- [ ] The optional, API-key-gated verify transport for self-hosted use is not confused with a public production endpoint.

## Required validation commands

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

## Final repository checks

- [ ] `README.md`, `docs/licensing.md`, `DISCLAIMER.md`, `CONTRIBUTING.md`, `GOVERNANCE.md`, `MAINTAINERS.md`, and `SECURITY.md` agree on the product boundary.
- [ ] `docs/roadmap.md` reflects current priorities rather than completed implementation history.
- [ ] `docs/release-downloads.md` matches the current release assets.
- [ ] The GitHub Pages structured data identifies catalog metadata as CC0 rather than MIT.
- [ ] Open issues and pull requests do not overstate completeness, hosted deployment, live verification, or automation authority.
