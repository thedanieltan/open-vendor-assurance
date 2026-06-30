# Assurance Verification State v1

Operational metadata only. This document is not legal, compliance,
procurement, security, KYC, AML, audit, or vendor-risk advice.

## Purpose

Assurance verification state answers:

> What conclusion is supported by admitted assurance observations?

It is separate from instrument lifecycle, supersession, freshness, evidence
completeness, source health, acquisition success, and publication.

This slice defines contracts, policy, fixtures, and semantic validation only. It
does not implement `project_verification_state()` or emit verification events.

## State Vocabulary

The verification-state vocabulary contains exactly:

* `no_conclusion`: no admitted eligible observation supports a conclusion.
* `confirmed`: decisive observations at the highest authority tier support the
  assurance observation.
* `contradicted`: decisive observations at the highest authority tier explicitly
  contradict it.
* `inconclusive`: decisive observations conflict, or the highest authority tier
  is explicitly inconclusive.

All four are determined classifications and use:

```yaml
determination: determined
```

Contradiction requires explicit negative assurance evidence, represented by the
machine-readable `verification_outcome: evidence_conflict`. It is never inferred
from source unavailability, HTTP failure, old evidence, an expired instrument, a
superseded instrument, missing evidence, or acquisition failure.

## Admission

Future verification evaluation admits inputs by repository knowledge time:

```text
assurance.recorded_at <= knowledge_cutoff
observation.recorded_at <= knowledge_cutoff
```

`observed_at` remains evidence observation time. It is not knowledge time.

Observation applicability to `effective_at` may use only fields already present
in the assurance-observation contract, especially `observed_fields`. Missing
`observed_fields` means the observation remains structurally applicable under
the v1 policy. The contract does not invent new temporal fields.

## Authority Policy

The normative policy is `config/assurance-verification-policy.yaml`.

The current assurance-observation schema has no separate authority object. The
policy therefore uses existing machine-readable `evaluation.verification_outcome`
values as the authority signal:

1. Admit by `knowledge_cutoff`.
2. Select observations linked to the target assurance.
3. Filter by `effective_at` using existing observation fields only.
4. Select the highest authority tier present.
5. Evaluate every observation at that tier.
6. Lower authority never overrides higher authority.
7. Conflicting decisive outcomes produce `inconclusive`.

The configured order is:

1. `authoritative`: `authoritative_status_confirmed`
2. `corroborating`: `evidence_consistent`, `evidence_conflict`
3. `first_party`: `first_party_claim_observed`
4. `indeterminate`: `insufficient_evidence`, `verification_unavailable`

`not_evaluated` is ignored and does not itself produce a verification
conclusion.

## Result Contract

An assurance verification-state result contains:

* `value`
* `determination`
* `reason_codes`
* `caused_by`
* request context (`assurance_id`, `effective_at`, `knowledge_cutoff`, policy)
* `input_digest`
* `advisory_boundary: non_advisory`

The target assurance is always cited in `caused_by.assurance_ids`. Only
observations decisive to the result are cited in
`caused_by.assurance_observation_ids`. Excluded observations and future-recorded
observations are not cited. `source_observation_ids` remains empty until a
future evaluator directly consumes source observations.

## Lifecycle Boundary

`openva.assurance-lifecycle.v1` remains a two-axis profile:

```yaml
implemented_axes:
  - instrument_state
  - supersession_state
```

Verification state is an assurance-intelligence contract. It is not added to
the lifecycle projection profile in this slice.

## Semantic Validation

The repository validates assurance-observation references supported by current
fields:

* the referenced assurance must exist;
* the observation vendor must match the referenced assurance vendor.

No observation supersession, retraction, freshness, or evidence-set semantics
are introduced by this contract.
