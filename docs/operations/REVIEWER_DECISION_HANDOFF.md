# Reviewer Decision Handoff

This page explains how reviewer decisions move from a spreadsheet into reviewed evidence without giving reviewers direct catalog access.

## Boundary

The reviewer spreadsheet is staging input. It is useful, but it is not catalog truth.

Validated JSON under `maintenance/reviewed/` is reviewed evidence. Catalog files under `data/vendors/**` change only through controlled PRs, validators, and CI.

## Reviewer inbox

Reviewers receive one artifact:

```text
openva-source-reviewer-inbox
```

That artifact contains one file:

```text
source-review-decision-sheet.csv
```

Reviewers should only edit the reviewer columns:

- `review_decision`
- `approved_replacement_url`
- `reviewer_note`
- `reviewed_by`
- `reviewed_at`

Do not edit identity, source-context, run-binding, or checksum columns.

## Maintainer-agent handoff

The completed CSV is untrusted input. It is checked before anything is committed.

The maintainer-agent must retrieve the matching source-review-triage-plan.json from the same run's openva-source-maintenance-report artifact.

The controlled flow is:

```text
receive completed source-review-decision-sheet.csv
→ retrieve matching source-review-triage-plan.json from openva-source-maintenance-report
→ run validate-sheet
→ stop if validation finds invalid rows
→ run export-reviewed-artifacts only after validation passes
→ open a PR containing only reviewed artifacts under maintenance/reviewed/
→ wait until CI passes
→ run source-repair-pr.yml later only from committed reviewed evidence
```

The CSV itself is not committed to the repo. The repo stores validated review evidence, not the raw spreadsheet.

## Run binding

The original `source-review-triage-plan.json` is required for validation.

Do not validate a completed sheet against a different triage plan. The reviewer sheet, triage plan, and reviewed artifacts must remain bound to the same `source-maintenance-report.yml` run.

## Commands

Validate a completed sheet against the matching original triage plan:

```bash
python -m tools.openva.source_review_decisions validate-sheet \
  --triage-plan source-review-triage-plan.json \
  --decision-sheet source-review-decision-sheet.csv \
  --output-json source-review-decision-validation.json \
  --output-md source-review-decision-validation-summary.md
```

Export reviewed artifacts only after validation has zero invalid rows:

```bash
python -m tools.openva.source_review_decisions export-reviewed-artifacts \
  --validation source-review-decision-validation.json \
  --output-dir maintenance/reviewed/generated
```

## What changes the catalog

Validated review evidence does not mutate `data/vendors/**`.

If a reviewer approved source repairs, a later controlled repair PR applies those changes. That PR is reviewed and checked like any other catalog change.

Do not apply automerge labels to reviewed-evidence PRs. A reviewed-evidence PR must be merged only after CI passes and the reviewed artifacts stay under `maintenance/reviewed/`.

## Stop conditions

Stop and request human maintainer review when:

- the completed CSV does not validate,
- the sheet was mixed with rows from another run,
- a replacement URL fails verification,
- a reviewer changed non-reviewer columns,
- exported files would be written outside `maintenance/reviewed/`,
- a policy decision is required.

## Non-goals

This handoff does not:

- let reviewers directly edit catalog files,
- automatically mutate source records from the CSV,
- automatically apply no-replacement truth-state,
- generate repair PRs directly from the CSV,
- relax validation, source-health, PR safety, release, or automerge gates.
