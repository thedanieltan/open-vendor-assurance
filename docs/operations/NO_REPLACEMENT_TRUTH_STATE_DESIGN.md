# No-Replacement Truth-State Design

This document defines the design posture for reviewed no-replacement source decisions. It is intentionally scoped to vendor-assurance intake and evidence preparation. OpenVA provides a canonical public evidence dataset; users decide how to apply that dataset in their own vendor-assurance workflows.

No catalog source YAML is mutated by this design. No reviewed no-replacement decision is automatically applied from reviewer sheets.

## Problem

`source_review_decisions validate-sheet` can produce reviewed no-replacement evidence when a reviewer marks `mark_no_replacement_available` and validation has zero invalid rows. That evidence is useful, but it must not become catalog truth without durable provenance, lifecycle, freshness, and validation semantics.

## Current decision

Reviewed no-replacement decisions may become durable unavailable-source state only through the first-class unavailable-source structure under `data/vendors/**/unavailable_sources/*.yaml`.

`data/vendors/**/sources/*.yaml` remains reserved for canonical available source references. No-replacement truth-state must not be written into source records; source records remain reserved for canonical available sources.

Reviewed no-replacement state remains distinct from source repairs, deletion instructions, or proof that a vendor will never publish a replacement source.

## Approved storage location

### First-class unavailable-source structure

Durable reviewed no-replacement state belongs under:

```text
data/vendors/{vendor_id}/unavailable_sources/{unavailable_source_id}.yaml
```

Benefits:

- Separates canonical available sources from unavailable-source truth-state.
- Preserves historical review evidence and re-check cadence.
- Avoids overloading source records.
- Keeps unavailable-source state in generated indexes, pack outputs, and vendor manifests.

## Rejected storage location

### `data/vendors/**/sources/*.yaml`

Do not place no-replacement truth-state inside source records.

Risks:

- Blurs the line between a broken source and a reviewed unavailable source.
- Encourages mutation from reviewer sheets.
- Makes available-source coverage harder to distinguish from unavailable-source evidence.

## Reviewed evidence holding area

`maintenance/reviewed/` remains the controlled reviewed-evidence handoff location.

Reviewed artifacts under `maintenance/reviewed/` are evidence. They are not durable catalog state until a later controlled application path creates or updates unavailable-source records and passes validation.

## Durable fields

Durable reviewed no-replacement state must preserve:

- `vendor_id`
- `source_type`
- `truth_state`
- `truth_state_status`
- `source_review_decision_id`
- `reviewed_by`
- `reviewed_at`
- `reviewer_note`
- `reviewed_artifact_path`
- `validation_report_path`
- `source_maintenance_run_id`
- `original_source`
- `next_review_after`
- `candidate_urls_checked`, if available
- `superseded_by_source_id`, when superseded
- `superseded_at`, when superseded
- `not_advice`

## Forbidden fields and behaviors

A durable no-replacement structure must not include:

- self-certifying `eligible` fields,
- automerge eligibility fields,
- unverified replacement URLs,
- raw document text,
- screenshots,
- customer-specific evidence,
- private portal material,
- legal advice or vendor-risk conclusions.

It must not:

- delete existing source records,
- rewrite source URLs,
- mark a vendor as non-compliant,
- suppress future discovery,
- bypass source-health gates,
- bypass PR safety checks,
- convert reviewer input directly into catalog truth.

## Validity and re-check cadence

A no-replacement decision is time-bound. It should expire or require re-check.

Default design posture:

- `next_review_after` is required.
- `truth_state_status` distinguishes `current`, `stale`, `expired`, and `superseded` state.
- Re-check cadence should be no longer than 90 days unless the source type has a documented exception.
- Any new candidate source found by discovery invalidates the stale no-replacement assumption and requires review.
- Release/site consumers must distinguish current reviewed no-replacement state from stale state.

## If discovery later finds a replacement

If discovery later finds a valid replacement:

1. The no-replacement evidence remains historical evidence.
2. The replacement must go through normal validation and reviewed repair flow.
3. The current no-replacement state must not block repair.
4. Durable unavailable-source state must be superseded, not silently overwritten.
5. The catalog must retain provenance of the change.

## Site representation

The site may eventually show unavailable-source state only if the schema defines:

- whether the state is current or stale,
- reviewer provenance,
- next review date,
- source type affected,
- public-safe explanation,
- no advisory conclusion.

The site must not state that the vendor lacks compliance, security, privacy, or assurance posture solely because a public source has no replacement.

## Release readiness consumption

Release readiness may eventually consume reviewed no-replacement state, but only after policy approval.

Allowed future consumption:

- distinguish unresolved source debt from reviewed unavailable-source state,
- flag stale no-replacement decisions,
- prevent stale decisions from masking source debt.

Forbidden future consumption:

- treating no-replacement evidence as a passing source check forever,
- lowering source-health gates without explicit policy,
- bypassing `source-maintenance-report.yml`.

## Validators required before application

Before any no-replacement decision can be applied to durable catalog unavailable-source state, validators must enforce:

1. Reviewed evidence is committed under `maintenance/reviewed/`.
2. Validation has zero invalid rows.
3. Reviewer metadata is present.
4. Original immutable source context matches the current catalog record.
5. No replacement URL is present for no-replacement decisions.
6. `next_review_after` is present.
7. Stale reviewed evidence is rejected or flagged.
8. No source record is deleted.
9. Generated indexes and pack outputs are rebuilt.
10. PR safety loop passes.

## Implementation status

Implemented in the schema-hardening package:

- additive unavailable-source schema fields for durable truth-state,
- required reviewed evidence/provenance fields when `truth_state` is `reviewed_no_replacement_available`,
- validator checks for reviewed evidence paths, human/hybrid review, original source context, and supersession references.

Not implemented yet:

- application code that converts reviewed artifacts into unavailable-source records,
- catalog mutation from reviewer sheets,
- source YAML mutation,
- site UI changes,
- release-gate changes,
- scheduled workflows.
