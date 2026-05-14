# Source Refinement Workflow

The source refinement queue turns an OpenVA observation report JSON file into a maintainer review queue.

It does not mutate catalog records, write observation records, create issues, or bypass access controls.

## Purpose

As the catalog grows, observation reports may identify sources with ambiguous fetch results:

```text
bot_protected
size_limited
fetch_failed
quarantined
```

These results do not mean a vendor is unsafe, non-compliant, unsuitable, unavailable, or problematic. They only describe what happened during OpenVA's transparent public-source observation attempt.

The source refinement queue helps maintainers decide whether a public source URL should be reviewed or refined.

## Command

Run:

```bash
python -m tools.openva.source_refinement_queue reports/observation-report.json \
  --markdown-out reports/source-refinement-queue.md \
  --json-out reports/source-refinement-queue.json
```

## Workflow

The manual workflow is:

```text
.github/workflows/source-refinement-queue.yml
```

It expects an observation report JSON file to be available in the checked-out repository path provided by the `observation_report_json` input.

Default input:

```text
reports/observation-report.json
```

The workflow has read-only repository permissions and uploads:

```text
reports/source-refinement-queue.md
reports/source-refinement-queue.json
```

as workflow artifacts.

## Output

The Markdown queue contains:

- total observed source count from the observation report;
- human-review count;
- counts by ambiguous result;
- vendor/source rows;
- HTTP status and final URL where available;
- operational suggested action.

The JSON queue contains the same machine-readable items plus safety guarantees:

```json
{
  "does_not_mutate_catalog": true,
  "does_not_write_observations": true,
  "does_not_bypass_access_controls": true,
  "does_not_make_advisory_claims": true
}
```

## Suggested actions

Suggested actions are operational only, such as:

```text
manual review
check whether the failure is transient
look for a clearer public vendor-controlled source
consider a source metadata PR
```

They are not vendor-risk, legal, compliance, procurement, audit, security, KYC, or AML findings.

## Maintainer decisions

After reviewing the queue, a maintainer may:

- leave the source unchanged;
- manually check whether the source remains public to humans;
- ask a source refinement agent to identify a better public vendor-controlled source;
- open a `Catalog:` PR to update source metadata;
- record an ambiguous observation only when that state itself should become durable public metadata.

## Boundaries

Do not use this workflow to:

- bypass bot protection, CAPTCHAs, login gates, customer portals, or access controls;
- fetch gated or private materials;
- write ambiguous observations by default;
- make compliance, risk, security, audit, KYC, AML, procurement, or vendor approval conclusions;
- automatically replace canonical source URLs without PR review.

## Future enhancement

A later phase may download the latest `observe-report` workflow artifact automatically and feed it into this queue. This PR intentionally keeps the workflow manual and read-only so maintainers can inspect the observation report before producing a refinement queue.
