# CI/CD optimization work package

Work package: `WP-CI-CD-OPTIMIZATION-01`

## Objective

OpenVA CI should be fast by default and heavy only when catalog authority, source authority, workflow authority, release/export contracts, or agent-facing integration contracts are touched.

The previous posture treated most pull requests as if they could affect catalog authority. That was safe, but slow. The optimized posture keeps hard gates on authority-sensitive surfaces while allowing product, docs, UI, adapter, MCP, and Sheets changes to run only the validation lanes they actually touch.

## Slices

### Slice 1: path-aware validation routing

Implemented in PR #508.

The `validate.yml` workflow now starts with `pr-change-classifier`, which emits lane booleans from the PR diff. The always-on `repository-integrity` job still runs repository hygiene, while the expensive validator, index rebuild, generated-output drift check, and PR release gates run only for authority-sensitive changes or pushes to `main`.

Targeted validation lanes now run only when their path domain is touched:

- `workflow-operating-model`
- `catalog-growth`
- `source-maintenance`
- `catalog-quality`
- `release-site`
- `mcp-integration`
- `google-sheets-integration`

### Slice 2: weighted-review slimming

Implemented by reducing `agent-weighted-review.yml` from four install-heavy parallel agent jobs plus a summary job into one classified `weighted-review` job.

The job still produces the same four validator result files plus one summary, but validators that are irrelevant to the changed paths write explicit skipped result payloads instead of running unnecessary checks.

Validator routing:

| Validator | Runs when | Skips when |
|---|---|---|
| `schema-conformance-agent` | catalog, schema, config, adapter, generated export, or validation logic changed | docs/site/workflow-only changes |
| `source-accessibility-agent` | changed vendor source or artifact URL records | no source/artifact URL records changed |
| `advisory-wording-agent` | public-claim surfaces changed, including docs, site, README, data, indexes, dist, adapters | workflow-only or non-public operational surfaces changed |
| `provenance-completeness-agent` | provenance-bearing vendor records changed | no provenance-bearing vendor records changed |

The summary comment is now the single PR comment surface for weighted review. Per-agent comments are intentionally removed to reduce PR noise.

### Slice 3: merge and branch-protection policy

Branch protection cannot be changed from this file-backed PR. The intended repository settings are:

- Keep `validate / repository-integrity` required.
- Keep `validate / pr-scope-guard` required.
- Add or keep `validate / pr-change-classifier` required.
- Treat path-routed validation lanes as required only if GitHub branch protection is configured to tolerate skipped checks for unaffected paths.
- Keep `catalog-pr-guard` required only for catalog-titled PRs if the repository ruleset can express that; otherwise keep it advisory and rely on generated catalog automerge eligibility for catalog PRs.
- Keep `agent-weighted-review` advisory unless the PR is catalog/source/schema authority-sensitive.

If GitHub branch protection cannot express path-aware required checks cleanly, use a future single `merge-gate` job as the branch-protection target. That job should depend on `pr-change-classifier`, inspect check conclusions, and fail only when the classified required lanes fail or are missing.

## Required-check recommendation

Minimum required checks after this work package:

```text
validate / pr-change-classifier
validate / repository-integrity
validate / pr-scope-guard
```

Conditional or advisory checks:

```text
validate / workflow-operating-model
validate / catalog-growth
validate / source-maintenance
validate / catalog-quality
validate / release-site
validate / mcp-integration
validate / google-sheets-integration
agent-weighted-review / weighted-review
catalog-pr-guard / catalog-pr-guard
```

## Non-goals

This work package does not weaken catalog authority gates. It does not allow catalog data, generated exports, source records, schemas, release gates, automerge logic, or workflow authority changes to bypass validation.

It also does not change OpenVA's non-advisory boundary. Weighted review remains advisory only and does not merge, close, or mutate catalog records.

## Smoke-test procedure

Use small pull requests that touch one low-risk surface at a time to verify routing after CI changes land. For an operations-doc-only change under `docs/operations/`, expected validation is:

- `validate / pr-change-classifier`: runs
- `validate / pr-scope-guard`: runs
- `validate / repository-integrity`: runs
- `validate / workflow-operating-model`: runs
- unrelated catalog, source-maintenance, release-site, MCP, and Google Sheets lanes: skipped
- `agent-weighted-review / weighted-review`: runs once, with only relevant validators active

## Expected impact

Low-risk PRs should avoid unnecessary catalog growth, source maintenance, release/site, MCP, Sheets, and weighted-review fan-out.

Authority-sensitive PRs should continue to receive the relevant heavy validation lanes.

The intended result is lower queue time and lower GitHub Actions consumption without removing protections from catalog or automation authority surfaces.
