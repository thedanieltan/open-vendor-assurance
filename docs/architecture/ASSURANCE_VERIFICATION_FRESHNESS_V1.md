# Assurance Verification Freshness v1

## Purpose

Verification freshness answers one narrow question:

> How current is the decisive observation basis supporting the verification result?

It does not say whether an assurance is active, superseded, confirmed, reachable,
complete, or publication-ready. Source-health failures, acquisition outcomes,
instrument expiry, supersession, evidence age outside the decisive basis, and
missing evidence do not directly determine freshness.

## Inputs

Freshness consumes a previously validated verification-state result and the
assurance observations it cites. It uses only:

- the target assurance;
- the decisive `assurance_observation_ids` in
  `verification_state.caused_by.assurance_observation_ids`;
- each decisive observation's `observed_at`;
- `recorded_at` only for knowledge-cutoff admission.

Lower-authority observations and observations excluded from verification-state
causality are ignored.

## Bitemporal Admission

The target assurance and every decisive observation must be known at the
projection cutoff:

```text
recorded_at <= knowledge_cutoff
```

`observed_at` remains the time the underlying evidence was observed. It is the
freshness anchor, not the knowledge-admission timestamp.

## State Vocabulary

The v1 freshness states are:

- `no_basis`
- `current`
- `aging`
- `stale`

All four are determined classifications. Invalid or inconsistent inputs fail
closed and are not represented as `no_basis`.

## Policy

The normative policy is
`config/assurance-verification-freshness-policy.yaml`.

The v1 basis rule is:

```text
basis_observed_at = oldest observed_at among decisive observations
```

This conservative rule prevents one fresh observation from hiding an older
observation that remains part of the decisive basis.

The v1 thresholds are:

- `current_max_age_seconds: 7776000` (90 days)
- `stale_min_age_seconds: 15552000` (180 days)

Boundary semantics are lower-bound inclusive and upper-bound exclusive:

```text
0 <= age_seconds < current_max_age_seconds          -> current
current_max_age_seconds <= age_seconds < stale_min_age_seconds -> aging
stale_min_age_seconds <= age_seconds                -> stale
```

If `effective_at` is before `basis_observed_at`, the input is invalid. The
system does not create negative freshness ages.

## Reevaluation

`next_reevaluation_at` is a planning hint, not a scheduler:

- `current` reevaluates at the aging threshold boundary;
- `aging` reevaluates at the stale threshold boundary;
- `stale` and `no_basis` have no time-derived reevaluation boundary.

No implicit clock, queue, daemon, API, MCP tool, publication surface, or
background scheduler is introduced by this contract.

## Boundary

Verification freshness remains outside
`openva.assurance-lifecycle.v1`, which continues to implement exactly
`instrument_state` and `supersession_state`.
