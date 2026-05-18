# Observation Reporting

OpenVA can periodically observe public source URLs and compile a human-review report without mutating the catalog.

This is an operational reporting loop, not a legal, compliance, procurement, audit, security, KYC, AML, or vendor-risk assessment.

## What the report does

The scheduled report:

1. validates the current catalog;
2. runs a public-source observation dry run across all catalog sources;
3. converts the dry-run YAML into Markdown, JSON, and CSV reports;
4. uploads the report as a GitHub Actions artifact;
5. prints the Markdown summary in the workflow log.

It does not:

- write observation records into `data/vendors/**`;
- create pull requests;
- open issues;
- fetch gated materials;
- bypass anti-bot systems;
- store raw vendor documents;
- compute hashes for blocked, failed, oversized, or quarantined responses;
- draw conclusions about vendor compliance, risk, security posture, or suitability.

## Workflow

The workflow is:

```text
.github/workflows/observe-report.yml
```

It runs:

```bash
python -m tools.openva.observe observe-all --dry-run --emit-yaml > /tmp/openva-observations.yaml
python -m tools.openva.observation_report /tmp/openva-observations.yaml \
  --markdown-out reports/observation-report.md \
  --json-out reports/observation-report.json
```

The workflow has read-only repository permissions.

## Schedule

The default schedule is weekly:

```yaml
schedule:
  - cron: "0 2 * * 1"
```

Maintainers can also run it manually through `workflow_dispatch`.

## Human-review queue

The report flags ambiguous observation results for human review:

```text
bot_protected
size_limited
fetch_failed
quarantined
```

These results do not mean a vendor is unsafe, non-compliant, unsuitable, unavailable, or problematic. They only describe what happened during OpenVA's transparent public-source fetch attempt.

## Output files

The workflow uploads:

```text
reports/observation-report.md
reports/observation-report.json
reports/observation-review-queue.csv
```

The Markdown report is for maintainers. The JSON report is for downstream automation or dashboards. The CSV export is for quick reviewer filtering and sorting.

## Maintainer use

Use the report to decide whether to:

- refine a source URL;
- mark a public source as difficult for automation;
- switch a source to a more stable public landing page;
- run a manual human review;
- leave the record unchanged.

Do not use the report to make vendor approval, legal, procurement, audit, risk, or compliance conclusions.

## Writing ambiguous observations

OpenVA intentionally does not write ambiguous observations by default.

A maintainer can intentionally write ambiguous observations with:

```bash
python -m tools.openva.observe observe-all --allow-ambiguous-write
```

Use that only when the ambiguous result itself should become durable public metadata.
