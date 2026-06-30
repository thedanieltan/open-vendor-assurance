# Assurance Evidence Set v1

## Purpose

Evidence-set state answers one narrow question:

> Is the admitted evidence set sufficiently complete and internally coherent under policy?

It does not determine verification conclusion, verification freshness,
instrument lifecycle, supersession, source availability, acquisition success, or
publication readiness.

## Machine-Readable Basis

The v1 policy uses only structured assurance-observation fields:

- `evaluation.verification_outcome`;
- `observed_fields.stated_valid_from`;
- `observed_fields.stated_valid_until`;
- `observed_fields.stated_identifier`;
- `observed_fields.stated_issuer_name`;
- `observed_fields.stated_scope_description`;
- `observed_fields.stated_as_of_date`;
- `observed_fields.stated_reporting_period`.

It does not infer evidence from free text, URLs, filenames, HTTP status,
source-health state, acquisition status, or source availability.

## States

The v1 states are:

- `no_evidence`
- `incomplete`
- `complete`
- `conflicted`

All are determined classifications. Invalid inputs fail closed rather than
being downgraded to `no_evidence` or `incomplete`.

## Admission

The target assurance and assurance observations are admitted only when:

```text
recorded_at <= knowledge_cutoff
```

Effective-time applicability uses the same structured observation fields as
verification state. No system clock is read.

## Policy

The normative policy is `config/assurance-evidence-set-policy.yaml`.

It maps structured observation fields to evidence dimensions and defines the
required dimensions by assurance class. Missing class coverage is invalid input
and fails closed.

The policy reuses the verification policy's authority tier ordering. Lower
authority observations do not override higher authority observations for the
same dimension.

## Conflict Handling

An unresolved policy-defined conflict takes precedence over completeness.
Evidence conflicts are based on machine-readable
`evaluation.verification_outcome: evidence_conflict` mapped to a structured
dimension. Source failures, old evidence, instrument expiry, and supersession do
not create evidence-set conflicts.

## Provenance

Results cite the target assurance and only assurance observations materially
used in the completeness or conflict decision. Source observations remain empty
because the evaluator consumes assurance observations, not source-observation
content.

## Boundary

Evidence-set state remains outside `openva.assurance-lifecycle.v1`, which
continues to implement exactly `instrument_state` and `supersession_state`.
This slice introduces no events, materialization, scheduler, API, MCP, site, or
publication surface.
