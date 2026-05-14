# CI and Branch Protection Readiness

This document defines the expected CI and branch-protection posture for OpenVA before public launch.

OpenVA is a public-source-only, metadata-first registry. Its CI must protect source integrity, generated pack integrity, contribution boundaries, and automation safety without requiring credentials or private vendor access.

## Required CI checks

The primary required check should be:

```text
validate / validate
```

This check runs on pull requests and pushes to `main`.

It must verify:

```bash
python -m tools.openva.validate validate
python -m tools.openva.validate build-indexes
git diff --exit-code openva-pack.json indexes/
pytest -q
```

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

Catalog PRs should not modify substrate, governance, workflow, schema, validator, observation, release, or security files unless explicitly moved into the core lane.

## Observation dry run

Observation dry run must remain manual-only:

```text
workflow_dispatch
```

It must not run on every pull request by default because it performs public network fetch attempts and may encounter transient source behavior.

Observation dry run must remain read-only and must not write observation records.

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

Workflows must not request write permissions unless a maintainer explicitly approves a core-lane workflow change.

Disallowed by default:

```yaml
contents: write
pull-requests: write
issues: write
actions: write
id-token: write
```

## Branch protection expectations

Before public launch, protect `main` with these expectations:

- require pull requests before merging;
- require the `validate / validate` status check;
- require branches to be up to date before merge where practical;
- require conversation resolution before merge;
- restrict force pushes;
- restrict branch deletion;
- require CODEOWNERS review for owned paths where available;
- do not allow automation to merge directly to `main`;
- keep admin bypass exceptional and documented.

Catalog PRs should also be held to the catalog guard when the PR title starts with `Catalog:`.

## Generated-file protection

The validation workflow must rebuild generated outputs and fail when these files are stale:

```text
openva-pack.json
indexes/
```

This prevents catalog changes from merging without regenerated pack/index outputs.

## Secrets and credentials

OpenVA CI should not require vendor credentials, customer-portal credentials, private trust-center access, tokens for public-source collection, or secrets for observation.

If a future workflow requires secrets, it must be reviewed as a security-sensitive core-lane change.

## Network posture

Validation, tests, pack conformance, and catalog guards should not depend on live vendor network access.

The only workflow that may attempt public network fetches is the manual observation dry-run workflow.

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
