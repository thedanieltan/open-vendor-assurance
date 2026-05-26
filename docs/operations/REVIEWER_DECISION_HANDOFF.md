# Reviewer Decision Handoff

Reviewer decision sheets are untrusted input. A human reviewer can be mistaken, and a submitted sheet can be malicious or malformed. Editing a sheet never mutates `data/vendors/**`, never proves a source is valid, and never creates a repair PR by itself.

This handoff is part of Lane A source cleanup. It is a controlled evidence path between `source-maintenance-report.yml` and `source-repair-pr.yml`; it is not a scheduled workflow, not an automerge lane, and not a catalog truth generator.

## Handoff Boundary

The required operating path is:

```text
source-maintenance-report.yml
→ download openva-source-reviewer-inbox
→ reviewer edits only source-review-decision-sheet.csv
→ operator retrieves matching source-review-triage-plan.json from openva-source-maintenance-report
→ run validate-sheet against the original triage plan
→ validate-sheet recomputes triage_plan_sha256 and checks source_maintenance_run_id
→ invalid rows stop the process
→ zero invalid rows allow reviewed artifact export
→ reviewed artifacts are committed under maintenance/reviewed/
→ CI passes on the reviewed-artifacts PR
→ source-repair-pr.yml may be run manually from committed reviewed repair evidence
```

The reviewer inbox artifact is `openva-source-reviewer-inbox`. It contains exactly one reviewer-editable file: `source-review-decision-sheet.csv`.

The original `source-review-triage-plan.json` is required for validation. It comes from the full `openva-source-maintenance-report` artifact produced by the same `source-maintenance-report.yml` run. Do not validate a completed sheet against a different triage plan.

## Machine-Enforced Run Binding

The reviewer sheet contains immutable binding columns:

- `source_maintenance_run_id`
- `triage_plan_sha256`
- `decision_sheet_generated_at`

`validate-sheet` recomputes `triage_plan_sha256` from the supplied `source-review-triage-plan.json` and compares it to every row. It also checks that `source_maintenance_run_id` matches the triage plan metadata and that all rows share one `decision_sheet_generated_at` value.

Rows fail validation if binding fields are missing, changed, mixed across rows, or inconsistent with the supplied triage plan. This turns the same-run requirement from a procedural instruction into a machine-checked guardrail.

## Required Agent Steps

After a reviewer submits a completed decision sheet, the agent must:

1. Treat the submitted sheet as untrusted input.
2. Validate it against the original `source-review-triage-plan.json` from the matching `openva-source-maintenance-report` artifact.
3. Reject rows where immutable context changed, including run-binding columns.
4. Reject rows with invalid enum decisions.
5. Reject rows with unsafe URLs, duplicate IDs, unexpected columns, or self-certifying fields.
6. Reject rows whose `triage_plan_sha256` or `source_maintenance_run_id` does not match the supplied triage plan.
7. Reject sheets that mix multiple `decision_sheet_generated_at` values.
8. For `replace_with_url` rows, independently verify the replacement URL.
9. Reject replacement rows that fail source verification, semantic match, authority, access, safety, soft-404, or canonical-final checks.
10. Produce `source-review-decision-validation.json` and `source-review-decision-validation-summary.md`.
11. Stop if `source-review-decision-validation.json` contains any invalid rows.
12. If validation has zero invalid rows and approved repairs exist, export reviewed repair plan artifacts.
13. If validation has zero invalid rows and no-replacement decisions exist, export no-replacement reviewed decision artifacts.
14. If validation has zero invalid rows and defer/reject decisions exist, export defer/rejection artifacts.
15. Open a PR containing only reviewed artifacts under `maintenance/reviewed/` if and only if the validation output has zero invalid rows.
16. Do not mutate `data/vendors/**` directly from a reviewer sheet.
17. Do not run `source-repair-pr.yml` until reviewed repair artifacts are committed under `maintenance/reviewed/` and CI passes.
18. Do not apply automerge labels to any PR created from a reviewer decision sheet.
19. Do not treat no-replacement or defer decisions as source repairs.
20. After reviewed repair artifacts are merged, run `source-repair-pr.yml` manually or through an existing reviewed path.
21. Inspect the generated repair PR before merge.
22. Re-run `source-maintenance-report.yml` after repair PRs merge.
23. Confirm public source health reflects the updated state.

## Explicit Warnings

- `approved_replacement_url` is not truth until independently verified.
- No-replacement decisions are truth-state candidates, not deletion instructions.
- Access-ambiguous decisions are not proof the source is valid.
- Repair PRs remain separate from decision validation.
- `validate-sheet` is report-only; it does not mutate `data/vendors/**` and does not mutate catalog source YAML.
- `export-reviewed-artifacts` writes reviewed evidence only; it does not apply source repairs.
- `source-repair-pr.yml` is the later controlled write path for reviewed repair evidence.

## Artifact Roles

| Artifact or file | Producer | Operator role | May be edited by reviewer? | Mutates catalog? |
|---|---|---|---:|---:|
| `openva-source-reviewer-inbox` | `source-maintenance-report.yml` | Reviewer inbox artifact. | No, artifact itself is downloaded only. | No |
| `source-review-decision-sheet.csv` | `source-maintenance-report.yml` | Single reviewer-editable CSV with immutable run-binding columns. | Yes, but only editable decision fields should change. | No |
| `openva-source-maintenance-report` | `source-maintenance-report.yml` | Full operator and machine artifact package. | No | No |
| `source-review-triage-plan.json` | `source-maintenance-report.yml` | Required original context for validation and SHA-256 binding. | No | No |
| `source-review-decision-validation.json` | `validate-sheet` | Independent validation evidence including source maintenance run and triage SHA-256. | No | No |
| `maintenance/reviewed/**` | Reviewed-artifacts PR | Committed reviewed evidence consumed by later controlled paths. | No | No |
| `source-repair-pr.yml` output PR | `source-repair-pr.yml` | Later repair PR generated only from committed reviewed repair evidence. | No | Yes, in PR branch only |

## Commands

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

## Stop Conditions

Stop and do not export reviewed artifacts if any of the following are true:

- The original `source-review-triage-plan.json` is missing.
- The decision sheet came from a different source maintenance run than the triage plan.
- The sheet `triage_plan_sha256` does not match the supplied triage plan.
- Rows have mixed `decision_sheet_generated_at` values.
- `validate-sheet` returns a non-zero exit code.
- `source-review-decision-validation.json` reports one or more invalid rows.
- A replacement URL fails independent verification.
- The proposed reviewed-artifacts PR contains files outside `maintenance/reviewed/`.

## Non-goals

This handoff does not:

- create a new scheduled workflow,
- automatically mutate catalog source records,
- apply no-replacement truth-state to catalog records,
- generate source repair PRs directly from reviewer sheets,
- relax source-health, validation, PR safety, release, or automerge gates.
