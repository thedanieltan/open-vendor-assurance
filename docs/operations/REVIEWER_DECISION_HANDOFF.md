# Reviewer Decision Handoff

This page explains how a reviewer helps clean up source records without needing direct catalog access.

The short version:

```text
Reviewer fills the spreadsheet
→ Maintainer checks it
→ Maintainer commits validated review evidence
→ A later repair PR changes the catalog if needed
```

Reviewers do **not** need to understand GitHub Actions, JSON artifacts, or catalog internals. Their job is to review the rows in the spreadsheet and fill only the reviewer columns.

## For reviewers

You will receive one file:

```text
source-review-decision-sheet.csv
```

Open it in a spreadsheet editor and review the rows assigned to you.

Only edit these columns:

| Column | What to enter |
|---|---|
| `review_decision` | The decision you are making. |
| `approved_replacement_url` | A replacement URL, only if you are approving a replacement. Otherwise leave blank. |
| `reviewer_note` | A short note explaining your decision. |
| `reviewed_by` | Your name, handle, or email. |
| `reviewed_at` | Review date/time, preferably ISO format such as `2026-05-26T00:00:00Z`. |

Do not edit the other columns. They identify the row and bind the sheet back to the source report that generated it.

Allowed `review_decision` values:

| Decision | Use when |
|---|---|
| `replace_with_url` | You found and approve a replacement public URL. |
| `mark_no_replacement_available` | You reviewed the source context and did not find a public replacement. |
| `defer_access_ambiguous` | The source may exist, but access or public availability is unclear. |
| `defer_needs_vendor_confirmation` | The row needs confirmation from the vendor or another reviewer. |
| `reject_candidate_mismatch` | The proposed replacement does not match the source type or vendor. |
| `keep_existing_source` | The current source should remain for now. |

Then return the completed CSV to the maintainer. Do not open a PR with the CSV.

## For maintainers

The completed CSV is reviewer input. It is checked before anything is committed.

The maintainer flow is:

```text
receive completed CSV
→ validate it against the matching source-review-triage-plan.json
→ stop if validation finds invalid rows
→ export reviewed artifacts if validation passes
→ commit only reviewed artifacts under maintenance/reviewed/
→ run the later source repair process if repairs were approved
```

The CSV itself is not committed to the repo. The repo stores validated review evidence, not the raw spreadsheet.

## Why the CSV is not committed

The spreadsheet is easy for humans to edit, but it is not catalog truth. Keeping it out of the repo prevents accidental catalog changes from typos, stale rows, copied sheets, or edited source context.

The repo records the reviewed result only after validation. Actual catalog changes happen later through a separate repair PR.

## Safety checks

The reviewer sheet contains hidden-in-plain-sight binding columns:

- `source_maintenance_run_id`
- `triage_plan_sha256`
- `decision_sheet_generated_at`

Reviewers should not edit these columns.

When the maintainer validates the sheet, OpenVA checks that:

- the sheet belongs to the matching source report,
- the sheet matches the original triage plan,
- all rows come from the same generated sheet,
- row identity and source context were not changed,
- replacement URLs are independently verified,
- invalid rows stop the process.

These checks let contributors use a simple spreadsheet while keeping catalog updates controlled.

## Commands for maintainers

Build a blank reviewer sheet from the triage plan:

```bash
python -m tools.openva.source_review_decisions build-sheet \
  --triage-plan source-review-triage-plan.json \
  --output-csv source-review-decision-sheet.csv \
  --output-md source-review-decision-sheet-summary.md
```

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

## What gets committed

Commit reviewed artifacts such as:

```text
maintenance/reviewed/<batch-name>/reviewed-repair-plan.json
maintenance/reviewed/<batch-name>/reviewed-no-replacement-decisions.json
maintenance/reviewed/<batch-name>/reviewed-deferred-decisions.json
```

Do not commit:

```text
source-review-decision-sheet.csv
```

## What changes the catalog

Validated review evidence does not directly change `data/vendors/**`.

If a reviewer approved source repairs, a later controlled repair PR applies those changes. That PR is reviewed and checked like any other catalog change.

## Stop conditions

Stop and ask for maintainer review if:

- the completed CSV does not validate,
- the sheet was mixed with rows from another run,
- a replacement URL fails verification,
- a reviewer changed non-reviewer columns,
- exported files would be written outside `maintenance/reviewed/`.

## Non-goals

This handoff does not:

- let reviewers directly edit catalog files,
- automatically mutate source records,
- automatically apply no-replacement truth-state,
- generate repair PRs directly from the CSV,
- relax validation, source-health, PR safety, release, or automerge gates.
