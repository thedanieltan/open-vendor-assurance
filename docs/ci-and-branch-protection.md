# CI and Branch Protection Readiness

This document defines the expected CI and branch-protection posture for OpenVA before public launch.

OpenVA is a public-source-only, metadata-first registry. Its CI must protect source integrity, generated pack integrity, contribution boundaries, and automation safety without requiring credentials or private vendor access.

## Required CI checks

The primary validation workflow is still one workflow:

```text
validate
```

It runs on pull requests and pushes to `main`, but it is partitioned into named ownership jobs so unrelated failures do not appear as one generic failure.

Required status contexts should be:

```text
validate / pr-change-classifier
validate / repository-integrity
validate / workflow-operating-model
validate / catalog-growth
validate / source-maintenance
validate / catalog-quality
validate / release-site
validate / mcp-integration
validate / google-sheets-integration
validate / pr-scope-guard
```

Historical note: the previous single-job required context was `validate / validate`. After partitioning, do not keep that old status context as a required branch-protection check because it is no longer emitted by the validation workflow.

The ownership contract is:

```text
.github/validation-ownership.yaml
```

The jobs preserve the old protection strength while improving failure ownership:

| Job | Owns | Core checks |
|---|---|---|
| `repository-integrity` | Canonical records and generated outputs. | Validator, index rebuild, generated drift check. |
| `workflow-operating-model` | Workflow inventory, operating-model docs, and machine-readable contracts. | CI readiness, workflow model, future operation specs, contract tests. |
| `catalog-growth` | Discovery queue, seed/candidate posture, reviewed promotion. | Catalog growth and promotion tests. |
| `source-maintenance` | Source health, source review, source repair, and source preflight. | Source maintenance and repair tests. |
| `catalog-quality` | Catalog guardrails and advisory automation checks. | Catalog-facing tests and automation rules. |
| `release-site` | Release assets, site output, and consumer adapter contract. | Release, site, and adapter tests. |
| `mcp-integration` | MCP server, adapter chain, protocol, hardening, and conformance. | MCP and adapter tests with local integration dependencies. |
| `google-sheets-integration` | Google Sheets pure-function integration surface. | Node test runner over the Apps Script test fixtures. |
| `pr-scope-guard` | Work-package path boundary. | Trusted-base scope guard on pull requests. |
| `full-regression-shards` | Non-PR broad regression signal. | Sharded pytest selections on push to `main`, manual dispatch, and weekly schedule. |

Repository integrity must verify:

```bash
python -m tools.openva.validate validate
python -m tools.openva.validate build-indexes
git diff --exit-code openva-pack.json indexes/ dist/
```

Broad regression remains available, but it must not be a monolithic required PR
gate. The `full-regression-shards` matrix runs only outside pull requests and
uses focused pytest selections with per-shard timeouts so slow areas are visible.

## Catalog PR guard

Catalog-agent PRs must start with:

```text
Catalog:
```

Those PRs should also pass:

```text
catalog-pr-guard / catalog-pr-guard
```

The catalog guard enforces the catalog-agent file boundary and then runs validation and tests.

Catalog PRs should not modify substrate, governance, workflow, schema, validator, observation, release, or security files unless explicitly moved into the core operating loop.

## Catalog agent PR workflow

The catalog agent PR workflow is manual-only:

```text
catalog agent PR / propose-catalog-update
workflow_dispatch
```

It may request `contents: write` and `pull-requests: write` only to create or update a catalog proposal pull request. It must not merge pull requests, change branch protection, publish releases, or write directly to `main`.

Catalog agent PR inputs must preserve these boundaries:

- `manifest_path` must point to a catalog batch manifest under `catalog-batches/`;
- `branch_name` must start with `agent-`;
- `pr_title` must start with `Catalog:`;
- generated pull requests must remain human-reviewed.

## Contribution intake agent

The contribution intake agent processes catalog update issues:

```text
contribution-intake-agent
issues
workflow_dispatch
```

It may request `contents: write`, `pull-requests: write`, and `issues: write` only to comment intake decisions and create or update human-reviewed `Catalog:` pull requests for low-risk existing-vendor source updates. It must not merge pull requests, change branch protection, publish releases, write directly to `main`, bypass access controls, or remove catalog sources because of automated fetch failures.

## Source maintenance report

The source maintenance report workflow is the consolidated scheduled maintenance layer:

```text
source-maintenance-report / source-maintenance-report
workflow_dispatch
schedule
```

It is read-only and produces a workflow artifact named:

```text
openva-source-maintenance-report
```

The artifact includes a maintainer-readable summary, JSON reports, CSV exports, and cleanup proposal Markdown. It consolidates source health inventory, public-source verification, source discovery, promotion planning, and cleanup proposal output.

It must not write observation records, open pull requests, change repository state, bypass access controls, or make advisory claims.

## Observation report

Observation reporting is the single scheduled observation workflow:

```text
observe-report / observe-report
workflow_dispatch
schedule
```

It must not run on every pull request by default because it performs public network fetch attempts and may encounter transient source behavior.

Observation reporting must remain read-only and must not write observation records.

## Workflow permissions

Default workflow posture:

```yaml
permissions:
  contents: read
```

Additional read-only permissions may be used only when needed.

Example:

```yaml
permissions:
  contents: read
  pull-requests: read
```

Workflows must not request write permissions unless a maintainer explicitly approves a core operating-loop workflow change and the workflow has a narrow, documented output.

Disallowed by default:

```yaml
contents: write
pull-requests: write
issues: write
actions: write
id-token: write
```

Approved write scopes are limited to:

- proposal PR workflows that create human-reviewed pull requests;
- issue handoff or queue workflows that create or update maintainer-facing issues or comments;
- publication workflows that deploy Pages or release assets without mutating catalog truth.

Proposal PR workflows may use:

```yaml
contents: write
pull-requests: write
```

solely to create or update human-reviewed catalog proposal pull requests.

Contribution intake workflows may additionally use:

```yaml
issues: write
```

solely to comment agent check results on the source issue.

Issue handoff or queue workflows may use:

```yaml
contents: read
issues: write
```

solely to create or update issue comments or maintainer queue issues. They must not write catalog files, open pull requests, or change `main`.

## Branch protection expectations

Before public launch, protect `main` with these expectations:

- require pull requests before merging;
- require the PR `validate / ...` status checks listed above;
- require branches to be up to date before merge where practical;
- require conversation resolution before merge;
- restrict force pushes;
- restrict branch deletion;
- require CODEOWNERS review for owned paths where available;
- do not allow automation to merge directly to `main` outside explicitly approved automerge policy;
- keep admin bypass exceptional and documented.

Catalog PRs should also be held to the catalog guard when the PR title starts with `Catalog:`.

## Weighted advisory review

Catalog PRs also run:

```text
agent-weighted-review
```

The workflow posts four independent validator scores and a summary comment. During the advisory rollout it does not merge, close, or mutate catalog files. Future merge behavior is governed by `docs/weighted-merge-policy.md` and remains disabled until maintainers explicitly approve the rollout change.

## Generated-file protection

The validation workflow must rebuild generated outputs and fail when these files are stale:

```text
openva-pack.json
indexes/
dist/
```

This prevents catalog changes from merging without regenerated pack/index/site-consumable outputs.

## Secrets and credentials

OpenVA CI should not require vendor credentials, customer-portal credentials, private trust-center access, tokens for public-source collection, or secrets for observation.

If a future workflow requires secrets, it must be reviewed as a security-sensitive core operating-loop change.

## Network posture

Validation, tests, pack conformance, catalog guards, and source health inventory reports should not depend on live vendor network access.

The only workflows that may attempt public network fetches are observation/reporting workflows, the contribution intake agent's transparent public-source check, and the weighted-review source accessibility agent. They must not use credentials, submit forms, solve CAPTCHAs, rotate proxies, or bypass access controls.

## Release readiness

Before tagging a release, run the release checklist:

```text
docs/release-checklist.md
```

At minimum:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

## Non-advisory boundary

CI checks protect repository integrity. They do not certify, approve, recommend, score, or verify any vendor for any organization, jurisdiction, workload, control, or legal obligation.
