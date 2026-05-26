# No-Replacement Truth-State Design

This document defines the design posture for reviewed no-replacement source decisions. It is intentionally a design document, not an implementation package.

No catalog source YAML is mutated by this design. No no-replacement decision is applied to `data/vendors/**` yet.

## Problem

`source_review_decisions validate-sheet` can produce reviewed no-replacement evidence when a reviewer marks `mark_no_replacement_available` and validation has zero invalid rows. That evidence is useful, but the project has not yet approved where durable no-replacement truth-state belongs.

Until the schema is decided, no-replacement decisions remain reviewed maintenance evidence under `maintenance/reviewed/`.

## Current decision

For now, reviewed no-replacement decisions live under `maintenance/reviewed/` as reviewed evidence only.

They are not catalog truth. They are not source repairs. They are not deletion instructions. They are not proof that a vendor will never publish a replacement source.

## Candidate storage locations

### Option 1: `maintenance/reviewed/`

This is the current approved holding area.

Benefits:

- Keeps reviewed evidence separate from canonical catalog records.
- Preserves reviewer metadata and validation posture.
- Avoids premature schema changes.
- Avoids accidentally deleting or downgrading source records.

Limitations:

- Release readiness and site display must consume it explicitly if it should affect confidence.
- Evidence may become stale without a re-check policy.

### Option 2: `data/vendors/**/sources/*.yaml`

This would place truth-state directly on existing source records.

Benefits:

- Keeps source state close to the source record.
- Easier for validators and indexes to consume once approved.

Risks:

- Can blur the line between a broken source and a reviewed unavailable source.
- Can encourage mutation from reviewer sheets.
- Requires careful validator changes and migration rules.

Do not implement this option until a schema PR defines exact fields and validators.

### Option 3: First-class unavailable-source structure

This would introduce a dedicated unavailable-source structure, for example under vendor records or a new catalog path.

Benefits:

- Separates canonical available sources from unavailable-source truth-state.
- Can preserve historical review evidence and re-check cadence.
- Avoids overloading source records.

Risks:

- Requires new schema, validators, indexes, and site/release semantics.
- Requires clear migration rules from `maintenance/reviewed/` evidence.

This is the preferred future direction if no-replacement decisions need durable catalog representation.

### Option 4: Derived index

This would keep evidence under `maintenance/reviewed/` and build a derived unavailable-source index.

Benefits:

- Avoids mutating canonical source records.
- Allows release/site consumers to read a normalized index.

Risks:

- Derived state may be mistaken for canonical truth if not clearly labeled.
- Requires freshness and provenance metadata.

## Required fields for any future durable schema

A future no-replacement truth-state schema must preserve:

- `vendor_id`
- `source_id`
- `source_type`
- original `source_url`
- `truth_state`
- `source_review_decision_id`
- `reviewed_by`
- `reviewed_at`
- `reviewer_note`
- validation report reference
- original triage plan reference or run identifier
- re-check cadence
- `next_review_after`
- candidate URLs checked, if available
- reason codes
- generated-at timestamp

## Forbidden fields and behaviors

A future no-replacement structure must not include:

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

- `next_review_after` is required for durable no-replacement truth-state.
- Re-check cadence should be no longer than 90 days unless the source type has a documented exception.
- Any new candidate source found by discovery invalidates the stale no-replacement assumption and requires review.
- Release/site consumers must distinguish current reviewed no-replacement state from stale state.

## If discovery later finds a replacement

If discovery later finds a valid replacement:

1. The no-replacement evidence remains historical evidence.
2. The replacement must go through normal validation and reviewed repair flow.
3. The current no-replacement state must not block repair.
4. Any durable unavailable-source state must be superseded, not silently overwritten.
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

Release readiness may eventually consume reviewed no-replacement state, but only after schema approval.

Allowed future consumption:

- distinguish unresolved source debt from reviewed unavailable-source state,
- flag stale no-replacement decisions,
- prevent stale decisions from masking source debt.

Forbidden future consumption:

- treating no-replacement evidence as a passing source check forever,
- lowering source-health gates without explicit policy,
- bypassing `source-maintenance-report.yml`.

## Validators required before application

Before any no-replacement decision can be applied to durable catalog truth-state, validators must enforce:

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

This package documents the design only.

Do not implement:

- catalog source YAML mutation,
- unavailable-source schema writes,
- no-replacement application code,
- site UI changes,
- release-gate changes,
- scheduled workflows.
