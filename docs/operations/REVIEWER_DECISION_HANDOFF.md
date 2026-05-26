# Reviewer Decision Handoff

Reviewer decision sheets are untrusted input. A human reviewer can be mistaken, and a submitted sheet can be malicious or malformed. Editing a sheet never mutates `data/vendors/**`, never proves a source is valid, and never creates a repair PR by itself.

## Required Agent Steps

After reviewer submits completed decision sheet, the agent must:

1. Treat the submitted sheet as untrusted input.
2. Validate it against the original triage plan.
3. Reject rows where immutable context changed.
4. Reject rows with invalid enum decisions.
5. Reject rows with unsafe URLs, duplicate IDs, unexpected columns, or self-certifying fields.
6. For `replace_with_url` rows, independently verify the replacement URL.
7. Reject replacement rows that fail source verification, semantic match, authority, access, safety, soft-404, or canonical-final checks.
8. Produce `source-review-decision-validation.json` and summary.
9. If approved repairs exist, export reviewed repair plan artifacts.
10. If no-replacement decisions exist, export no-replacement reviewed decision artifacts.
11. If defer/reject decisions exist, export defer/rejection artifacts.
12. Open a PR containing only reviewed artifacts under `maintenance/reviewed/` if and only if the validation output has zero invalid rows.
13. Do not mutate `data/vendors/**` directly from a reviewer sheet.
14. Do not run `source-repair-pr` until reviewed artifacts are committed and CI passes.
15. Do not apply automerge labels to any PR created from a reviewer decision sheet.
16. Do not treat no-replacement or defer decisions as source repairs.
17. After reviewed repair artifacts are merged, run `source-repair-pr` manually or through existing reviewed workflow.
18. Inspect generated repair PR before merge.
19. Re-run `source-maintenance-report` after repair PRs merge.
20. Confirm public source health reflects the updated state.

## Explicit Warnings

- `approved_replacement_url` is not truth until independently verified.
- No-replacement decisions are truth-state candidates, not deletion instructions.
- Access-ambiguous decisions are not proof the source is valid.
- Repair PRs remain separate from decision validation.

## Commands

Build a blank reviewer sheet from the triage plan:

```bash
python -m tools.openva.source_review_decisions build-sheet \
  --triage-plan source-review-triage-plan.json \
  --output-csv source-review-decision-sheet.csv \
  --output-md source-review-decision-sheet-summary.md
```

Validate a completed sheet:

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
