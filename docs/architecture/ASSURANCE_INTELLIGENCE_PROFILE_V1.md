# Assurance Intelligence Profile v1

## Purpose

`openva.assurance-intelligence.v1` is a pure, non-advisory projection profile
that combines five already-defined axes:

1. `instrument_state`
2. `supersession_state`
3. `verification_state`
4. `verification_freshness`
5. `evidence_set_state`

The existing lifecycle profile, `openva.assurance-lifecycle.v1`, remains
unchanged and continues to implement exactly `instrument_state` and
`supersession_state`.

## Inputs

The request supplies:

- target `assurance_id`;
- `effective_at`;
- `knowledge_cutoff`;
- profile ID;
- policy identities for lifecycle, verification, verification freshness, and
  evidence-set policies.

Each supplied policy document is checked against the request identity using the
canonical policy digest:

```text
sha256_bytes(canonical_json(policy))
```

## Orchestration

The unified projector calls the existing axis evaluators:

- `project_assurance()` for lifecycle axes;
- `project_verification_state()` for verification state;
- `project_verification_freshness()` using the verification-state result;
- `project_evidence_set_state()` independently over structured evidence fields.

No axis overwrites another axis's semantics. The orchestrator does not
reimplement axis rules.

## Digest

The unified `input_digest` is derived from a deterministic semantic manifest
containing:

- profile ID;
- target assurance ID;
- normalized `effective_at`;
- normalized `knowledge_cutoff`;
- all validated policy identities;
- target vendor;
- lifecycle-admitted assurance/source records;
- admitted assurance observations used by observation-driven axes.

It excludes `projected_at`, file paths, filenames, runtime object identity,
derived axis outputs, events, and materialized artifacts.

## Reevaluation

The envelope `next_reevaluation_at` is the earliest non-null boundary from:

- lifecycle `instrument_state`;
- `verification_freshness`.

Supersession state, verification state, and evidence-set state do not currently
provide autonomous time boundaries.

## Stability

For identical semantic inputs, changing only `projected_at` changes only
`projected_at`. Axis outputs and `input_digest` remain stable.

## Boundary

This profile is pure orchestration. It introduces no diffing, lifecycle events,
materialization, index migration, acquisition integration, API, MCP, site,
export, scheduler, queue, or publication surface.
